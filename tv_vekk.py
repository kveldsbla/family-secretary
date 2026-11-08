"""TV-vekk: vekker Frame-TV-en fra standby og setter den i Art Mode – som appen gjør.

Bakgrunn (fase 6, tv-sjekk 4.–5. nov): TV-en er på Wi-Fi hele natta, men kunstappen sovner
rundt to timer etter at TV-en er slått av. Da svarer ikke Art Mode-kanalen, og opplasting feiler
(kode 2). Dette skriptet prøver å vekke den.

To metoder:
  wol   Wake-on-LAN: et standard «vekk»-signal over nettet. Kan bare skru PÅ, aldri av.
  tast  Av/på-tasten, sendt over nettet slik fjernkontrollen/appen gjør. Kan også skru AV,
        så den sendes bare når TV-en selv sier «standby».

Rekkefølge:
  1. Svarer Art Mode-kanalen allerede? Da settes bare Art Mode på.
  2. Står TV-en i TV-modus (strøm «on»)? Da gjøres ingenting – noen ser på TV.
     Unntak med --avbryt (automatisk.py bruker det kl. 08:00–08:10 på skoledager):
     kort trykk til Art Mode, så «Nå må du dra!» kommer fram.
  3. Ellers sendes signalet, og skriptet venter opptil 90 s på at kunstappen våkner.
  4. Når den svarer: Art Mode på.

Bruk (fra familiehub-mappen i PowerShell):
  .venv\\Scripts\\python tv_vekk.py                    vekk med av/på-tasten, så kort trykk til Art Mode
  .venv\\Scripts\\python tv_vekk.py --metode art-tast  bare kort trykk (TV-en står på i TV-modus)
  (wol og begge finnes fortsatt, men Wake-on-LAN vekket ikke kunstappen i testen 5. nov)

Returkode: 0 = TV-en er i Art Mode og klar for opplasting, 2 = ikke vekket.
Hver sjekk logges i logs/tv-sjekk.csv (samme logg som tv_sjekk.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import socket
import sys
import time
import urllib.request

from tv_sjekk import ROOT, art_kanal, les_tv_config, sjekk, skriv, strom_status

VENT_SEKUNDER = 90
KORT_TRYKK_ETTER = 3   # sekunder i TV-modus før kort trykk til Art Mode (TV-modus gir lyd)


def hent_mac(tv_cfg: dict) -> str | None:
    """MAC-adressen fra config (tv: mac:) eller fra TV-ens egen nettside (wifiMac)."""
    mac = tv_cfg.get("mac")
    if not mac:
        try:
            with urllib.request.urlopen(f"http://{tv_cfg['ip']}:8001/api/v2/", timeout=5) as r:
                mac = (json.loads(r.read().decode("utf-8", "replace")).get("device") or {}).get("wifiMac")
        except Exception:
            return None
    hexs = re.sub(r"[^0-9A-Fa-f]", "", str(mac or ""))
    return hexs.lower() if len(hexs) == 12 else None


def send_wol(tv_cfg: dict) -> bool:
    mac = hent_mac(tv_cfg)
    if not mac:
        print("   Fant ikke TV-ens MAC-adresse. Legg den inn som «mac:» under «tv:» i config.yaml.")
        return False
    pakke = bytes.fromhex("ff" * 6 + mac * 16)   # «magisk pakke»: 6 x FF og MAC-adressen 16 ganger
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            for mål in ("255.255.255.255", tv_cfg["ip"]):
                for port in (9, 7):
                    try:
                        s.sendto(pakke, (mål, port))
                    except OSError:
                        pass
            time.sleep(0.3)
    print(f"   Wake-on-LAN sendt til {mac[:2]}:…:{mac[-2:]}")
    return True


def send_tast(tv_cfg: dict) -> bool:
    try:
        from samsungtvws import SamsungTVWS
        tv = SamsungTVWS(host=tv_cfg["ip"], port=int(tv_cfg.get("port", 8002)),
                         token_file=str(ROOT / "data" / "token.txt"),
                         name=tv_cfg.get("navn") or "SmartFrame", timeout=10)
        tv.send_key("KEY_POWER")
        tv.close()
        print("   Av/på-tast sendt")
        return True
    except Exception as exc:
        print(f"   Av/på-tasten kunne ikke sendes: {type(exc).__name__}: {exc}")
        return False


async def _art_på(tv_cfg: dict) -> str:
    from tv.upload import _frame
    frame = _frame(tv_cfg, ROOT / "data")
    await asyncio.wait_for(frame.open(), 20)
    try:
        try:
            await asyncio.wait_for(frame.tv.set_artmode("on"), 15)
        except asyncio.TimeoutError:
            pass   # noen TV-er svarer ikke på selve kommandoen; vi sjekker etterpå
        await asyncio.sleep(3)
        return str(await frame.art_mode())
    finally:
        await frame.close()


def art_på(tv_cfg: dict) -> str:
    try:
        return asyncio.run(_art_på(tv_cfg))
    except Exception as exc:
        return f"feil: {type(exc).__name__}"


def vent_på_kunstappen(tv_cfg: dict, sekunder: float = VENT_SEKUNDER) -> bool:
    slutt = time.monotonic() + sekunder
    while time.monotonic() < slutt:
        kanal, _ = art_kanal(tv_cfg)
        if kanal == "ok":
            return True
        print(f"   … venter (Art-kanal: {kanal})")
        time.sleep(5)
    return False


def vent_på_strøm(tv_cfg: dict, sekunder: float = 30) -> bool:
    slutt = time.monotonic() + sekunder
    while time.monotonic() < slutt:
        if strom_status(tv_cfg["ip"]) == "on":
            return True
        time.sleep(2)
    return False


def kort_trykk_til_art(tv_cfg: dict) -> bool:
    """TV-en står på i TV-modus uten kunstapp: et kort trykk på av/på gir Art Mode på en Frame."""
    print("   TV-en er på i TV-modus – sender kort trykk på av/på for Art Mode")
    if not send_tast(tv_cfg):
        return False
    return vent_på_kunstappen(tv_cfg, 60)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vekker Frame-TV-en og setter den i Art Mode.")
    p.add_argument("--metode", choices=["tast", "art-tast", "wol", "begge"], default="tast",
                   help="tast: vekk med av/på + kort trykk til Art Mode (standard). "
                        "art-tast: bare kort trykk, når TV-en allerede står på i TV-modus")
    p.add_argument("--avbryt", action="store_true",
                   help="står TV-en på i TV-modus: avbryt med kort trykk til Art Mode (brukes kl. 08:00–08:10)")
    args = p.parse_args(argv)
    tv_cfg = les_tv_config()
    start = time.monotonic()

    før = sjekk(tv_cfg, f"vekk {args.metode}: før")
    skriv(før)
    if før["art_kanal"] != "ok":
        vekket = False
        if args.metode == "art-tast":
            if før["strom"] != "on":
                print("art-tast er bare for en TV som står på i TV-modus. Bruk --metode tast.")
                return 2
            vekket = kort_trykk_til_art(tv_cfg)
        elif før["strom"] == "on" and args.avbryt:
            # Noen ser på TV, men det er dra-tid: kort trykk avbryter og gir Art Mode (06 #71)
            print("TV-en er på i TV-modus, og det er dra-tid – avbryter med kort trykk til Art Mode")
            vekket = kort_trykk_til_art(tv_cfg)
        elif før["strom"] == "on":
            print("TV-en er på i TV-modus. Noen ser på TV – lar den være (avbryt bare i dra-tiden).")
            return 2
        else:
            for metode in (["wol", "tast"] if args.metode == "begge" else [args.metode]):
                print(f"Prøver {metode} (strøm: {strom_status(tv_cfg['ip'])})")
                if metode == "wol":
                    if send_wol(tv_cfg) and vent_på_kunstappen(tv_cfg):
                        vekket = True
                        break
                    continue
                if strom_status(tv_cfg["ip"]) == "on":
                    print("   TV-en har våknet til «on» – sender ikke av/på-tasten.")
                elif not send_tast(tv_cfg):
                    continue
                if not vent_på_strøm(tv_cfg):
                    print("   TV-en våknet ikke (strøm er fortsatt ikke «on»)")
                    continue
                print(f"   TV-en er på etter {time.monotonic() - start:.0f} s")
                # TV-en starter i TV-modus (med lyd) etter langt trykk; kunstappen starter ikke av seg selv
                # (test 5. nov). Derfor kort trykk nesten med en gang, uten å vente på kunstappen først.
                time.sleep(KORT_TRYKK_ETTER)
                if kort_trykk_til_art(tv_cfg):
                    vekket = True
                    break
        if not vekket:
            skriv(sjekk(tv_cfg, f"vekk {args.metode}: IKKE vekket"))
            print("Klarte ikke å vekke kunstappen.")
            return 2
        print(f"   Kunstappen svarer etter {time.monotonic() - start:.0f} s")

    print(f"Art Mode: {art_på(tv_cfg)}")
    etter = sjekk(tv_cfg, f"vekk {args.metode}: etter ({time.monotonic() - start:.0f} s)")
    skriv(etter)
    return 0 if etter["art_kanal"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
