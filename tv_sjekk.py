"""TV-sjekk: ser hvordan Frame-TV-en svarer – uten å endre noe på den.

Laster ikke opp bilder, bytter ikke bilde og skrur ikke på TV-en. Sjekker tre ting:
  1. Svarer TV-en på nettet?          (portene 8001 og 8002)
  2. Hva sier TV-en om strømmen?      (PowerState fra TV-ens nettside, f.eks. «on» eller «standby»)
  3. Åpner Art Mode-kanalen seg?      (den opplastingen trenger) – og står Art Mode på eller av?

Hver sjekk blir én linje i logs/tv-sjekk.csv, som kan åpnes i Excel eller Notisblokk.

Bruk (fra familiehub-mappen i PowerShell):
  .venv\\Scripts\\python tv_sjekk.py                        én sjekk nå
  .venv\\Scripts\\python tv_sjekk.py --merknad "test 1"     én sjekk med en merknad i loggen
  .venv\\Scripts\\python tv_sjekk.py --hver 5 --timer 14    sjekk hvert 5. minutt i 14 timer (Ctrl+C stopper)
  .venv\\Scripts\\python tv_sjekk.py --til-sovnet           sjekk hvert 2. minutt og si fra (melding + lyd)
                                                         når kunstappen har sovnet – eller dobbeltklikk tv-sovnet.cmd

Del av fase 6 (automatisering på PC-en): svarene avgjør kjøretider og nytt forsøk ved kode 2.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import socket
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
LOGG = ROOT / "logs" / "tv-sjekk.csv"
FELTER = ["tid", "merknad", "port_8001", "port_8002", "strom", "art_kanal", "art_mode", "sekunder", "konklusjon"]
KANAL_TIDSGRENSE = 20   # samme som opplastingen (tv/upload.py)


def les_tv_config() -> dict:
    path = ROOT / "config.yaml"
    if not path.exists():
        sys.exit("Fant ikke config.yaml i familiehub-mappen.")
    with path.open(encoding="utf-8") as f:
        tv = (yaml.safe_load(f) or {}).get("tv") or {}
    if not tv.get("ip"):
        sys.exit("Fant ikke TV-adressen (tv: ip:) i config.yaml.")
    return tv


def port_svarer(ip: str, port: int, timeout: float = 3.0) -> bool:
    try:
        socket.create_connection((ip, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def strom_status(ip: str) -> str:
    """Spør TV-ens enkle nettside (http://IP:8001/api/v2/) om PowerState. Ingen innlogging trengs."""
    try:
        with urllib.request.urlopen(f"http://{ip}:8001/api/v2/", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return str((data.get("device") or {}).get("PowerState") or "ukjent")
    except Exception as exc:  # TV-en av, eller svarer ikke
        return f"svarer ikke ({type(exc).__name__})"


async def _art_sjekk(tv_cfg: dict) -> tuple[str, str]:
    from tv.frame import FrameAsleep, FrameRefused
    from tv.upload import _frame

    try:
        frame = _frame(tv_cfg, ROOT / "data")
    except FrameRefused as exc:
        return f"nektet: {exc}", "–"
    try:
        await asyncio.wait_for(frame.open(), KANAL_TIDSGRENSE)
    except asyncio.TimeoutError:
        await frame.close()
        return f"svarte ikke innen {KANAL_TIDSGRENSE} s", "–"
    except FrameRefused:
        await frame.close()
        return "nektet (paring?)", "–"
    except FrameAsleep:
        await frame.close()
        return "svarer ikke", "–"
    try:
        mode = await asyncio.wait_for(frame.art_mode(), 15)
        return "ok", str(mode) if mode is not None else "ukjent"
    except asyncio.TimeoutError:
        return "ok", "svarte ikke"
    finally:
        await frame.close()


def art_kanal(tv_cfg: dict) -> tuple[str, str]:
    try:
        return asyncio.run(asyncio.wait_for(_art_sjekk(tv_cfg), 60))
    except asyncio.TimeoutError:
        return "tidsavbrudd (60 s)", "–"
    except Exception as exc:
        return f"feil: {type(exc).__name__}", "–"


def konklusjon(p8002: bool, kanal: str) -> str:
    if kanal == "ok":
        return "Opplasting ville trolig virket"
    if not p8002:
        return "TV-en er ikke på nettet (kode 2)"
    return "TV-en er på nettet, men Art Mode svarer ikke (kode 2)"


def sjekk(tv_cfg: dict, merknad: str) -> dict:
    ip, port = tv_cfg["ip"], int(tv_cfg.get("port", 8002))
    start = time.monotonic()
    rad = {"tid": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "merknad": merknad}
    rad["port_8001"] = "ja" if port_svarer(ip, 8001) else "nei"
    rad["port_8002"] = "ja" if port_svarer(ip, port) else "nei"
    rad["strom"] = strom_status(ip) if rad["port_8001"] == "ja" else "–"
    if rad["port_8002"] == "ja":
        rad["art_kanal"], rad["art_mode"] = art_kanal(tv_cfg)
    else:
        rad["art_kanal"], rad["art_mode"] = "hoppet over", "–"
    rad["sekunder"] = f"{time.monotonic() - start:.1f}"
    rad["konklusjon"] = konklusjon(rad["port_8002"] == "ja", rad["art_kanal"])
    return rad


def skriv(rad: dict) -> None:
    LOGG.parent.mkdir(exist_ok=True)
    ny = not LOGG.exists()
    # utf-8-sig og semikolon gjør at norsk Excel åpner filen riktig
    with LOGG.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FELTER, delimiter=";")
        if ny:
            w.writeheader()
        w.writerow(rad)
    print(f"{rad['tid']}  8001:{rad['port_8001']}  8002:{rad['port_8002']}  strøm:{rad['strom']}  "
          f"Art-kanal:{rad['art_kanal']}  Art Mode:{rad['art_mode']}  ({rad['sekunder']} s)")
    print(f"   → {rad['konklusjon']}" + (f"   [{rad['merknad']}]" if rad["merknad"] else ""))


def har_sovnet(rad: dict) -> bool:
    """Kunstappen har sovnet: TV-en er på nettet og ikke på, men Art Mode-kanalen svarer ikke."""
    return rad["port_8002"] == "ja" and rad["strom"] != "on" and rad["art_kanal"] != "ok"


def si_fra(tekst: str) -> None:
    """Lyd og en vanlig Windows-melding. Gjør ingenting på andre systemer."""
    print("\n" + "=" * 60 + f"\n  {tekst}\n" + "=" * 60)
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(880, 300)
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, tekst, "TV-sjekk", 0x40 | 0x40000)  # info-ikon, øverst
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sjekker hvordan Frame-TV-en svarer, uten å endre noe.")
    p.add_argument("--merknad", default="", help="tekst som skrives i loggen, f.eks. \"test 1\"")
    p.add_argument("--hver", type=float, help="gjenta hvert N. minutt")
    p.add_argument("--timer", type=float, default=14, help="hvor lenge gjentakelsen varer (standard 14 timer)")
    p.add_argument("--til-sovnet", action="store_true",
                   help="sjekk hvert 2. minutt (eller --hver) og si fra når kunstappen har sovnet")
    args = p.parse_args(argv)
    if args.til_sovnet:
        args.hver = args.hver or 2
        args.merknad = args.merknad or "venter på at TV-en sovner"

    tv_cfg = les_tv_config()
    print(f"Sjekker TV-en på {tv_cfg['ip']}. Logg: {LOGG}")
    if not args.hver:
        skriv(sjekk(tv_cfg, args.merknad))
        return 0
    slutt = time.monotonic() + args.timer * 3600
    try:
        while time.monotonic() < slutt:
            rad = sjekk(tv_cfg, args.merknad)
            skriv(rad)
            if args.til_sovnet and har_sovnet(rad):
                si_fra(f"Kunstappen på TV-en sovnet kl. {rad['tid'][11:16]}. Klar for tv_vekk-testen!")
                return 0
            time.sleep(args.hver * 60)
    except KeyboardInterrupt:
        print("Stoppet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
