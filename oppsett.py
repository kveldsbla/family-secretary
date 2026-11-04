"""Oppsett: svar på noen spørsmål, så lages innstillingene for deg.

    python oppsett.py          # hele oppsettet (kan kjøres på nytt når som helst)
    python oppsett.py --par    # bare koble til (pare med) TV-en på nytt

Skriptet lager:
- config.yaml     – DINE innstillinger. Det eneste dokumentet du trenger å åpne senere.
- .env            – kalenderlenken (hemmelig, som et passord).
- skolerute.yaml  – fridager i skolen, kopiert fra eksempelet (sjekk datoene for din kommune).
- data/token.txt  – nøkkelen TV-en gir når du trykker «Tillat».

Ingen av disse filene legges i Git. Alt annet har standardverdier; se config.example.yaml
hvis du vil endre mer (klesråd, tider, tekster).
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_KEY = "FAMILIEKALENDER_ICS"          # samme som i sources/calendar.py
TV_NAME = "Family Secretary"             # navnet TV-en viser når den spør om «Tillat»

# Personfarger (dag, kveld). Skiller seg også for fargesvake. Flere enn fem personer: fargene gjentas.
PALETTE = [("#6d5a4a", "#dbb996"), ("#2f6aa8", "#6aa5e0"), ("#1e8a6e", "#9ee4c6"),
           ("#c96f22", "#e28030"), ("#a64d86", "#d68aaf")]
MARK_BAD = set(" \t&+,/:")


# ------------------------------------------------------------------ spørsmål

def ask(prompt: str, default: str | None = None, parse=None, inp=input):
    """Spør til svaret er gyldig. parse(text) returnerer verdien eller kaster ValueError med forklaring."""
    hint = f" [{default}]" if default not in (None, "") else ""
    while True:
        text = inp(f"{prompt}{hint}: ").strip()
        if not text and default is not None:
            text = str(default)
        try:
            return parse(text) if parse else text
        except ValueError as exc:
            print(f"  ! {exc}")


def ask_yes(prompt: str, default: bool = True, inp=input) -> bool:
    def parse(text: str) -> bool:
        t = text.casefold()
        if t in ("j", "ja", "y", "yes"):
            return True
        if t in ("n", "nei", "no"):
            return False
        raise ValueError("svar j (ja) eller n (nei)")
    return ask(prompt + " (j/n)", "j" if default else "n", parse, inp)


def parse_coord(text: str, lo: float, hi: float) -> float:
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        raise ValueError("skriv et tall, f.eks. 59.9133") from None
    if not lo <= value <= hi:
        raise ValueError(f"tallet må være mellom {lo} og {hi}")
    return round(value, 4)                   # MET vil ha maks 4 desimaler


def parse_email(text: str) -> str:
    if "@" not in text or " " in text or "eksempel" in text or text.startswith("@") or text.endswith("@"):
        raise ValueError("skriv en ekte e-postadresse – MET Norway (Yr) krever kontaktinfo")
    return text


def parse_ip(text: str) -> str:
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        raise ValueError("skriv adressen som fire tall med punktum, f.eks. 192.168.1.50") from None


def parse_name(text: str) -> str:
    if not text:
        raise ValueError("skriv et navn")
    return text


def parse_count(text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 12:
        raise ValueError("skriv et tall fra 1 til 12")
    return int(text)


def parse_link(text: str) -> str:
    if text and not text.startswith(("https://", "webcal://")):
        raise ValueError("lenken skal starte med https:// eller webcal:// (eller la feltet stå tomt)")
    return text


def default_mark(name: str, used: set[str]) -> str:
    """Første bokstav i navnet, eller neste ledige bokstav i navnet."""
    for ch in name:
        if ch.isalpha() and ch.upper() not in used:
            return ch.upper()
    return ""


def parse_mark(text: str, used: set[str]) -> str:
    if not text:
        raise ValueError("skriv et merke (vanligvis initialen)")
    if any(c in MARK_BAD for c in text):
        raise ValueError("merket kan ikke ha mellomrom eller tegnene & + , / :")
    if text.upper() in used:
        raise ValueError(f"«{text}» er allerede brukt av en annen")
    return text.upper()


# ------------------------------------------------------------------ filer

def _q(text: str) -> str:
    """Trygg YAML-tekst med æ, ø og å."""
    return json.dumps(text, ensure_ascii=False)


def config_text(lat: float, lon: float, email: str, ip: str, persons: list[dict]) -> str:
    lines = [
        "# Dine innstillinger – dette er filen du endrer.",
        f"# Laget av oppsett.py {date.today():%d.%m.%Y}. Legges aldri i Git (koordinater og e-post).",
        "# Alt som ikke står her, har standardverdier. Se config.example.yaml for alt du kan endre,",
        "# og kopier bare linjene du vil endre hit.",
        "",
        "sted:",
        "  # Hjemmets koordinater (maks 4 desimaler)",
        f"  lat: {lat}",
        f"  lon: {lon}",
        "",
        "yr:",
        "  # MET Norway (Yr) krever kontaktinfo i hver forespørsel",
        f"  user_agent: {_q('family-secretary/0.1 ' + email)}",
        "",
        "tv:",
        "  # TV-ens adresse på hjemmenettet. Gi den gjerne fast IP, så den ikke endres.",
        f"  ip: {_q(ip)}",
        "  port: 8002",
        f"  navn: {_q(TV_NAME)}",
        "",
        "personer:",
        "  # Merk kalenderhendelser med merket først i tittelen: «L Turdag», «E & L Foreldremøte».",
        "  # Hendelser uten merke er felles. farge = om dagen, farge_kveld = fra kl. 18.",
        "  # barn: true = vises på «Nå må du dra!»-bildet kl. 08:00–08:10 på skoledager.",
    ]
    for i, p in enumerate(persons):
        day, night = PALETTE[i % len(PALETTE)]
        lines += [f"  - navn: {_q(p['navn'])}",
                  f"    merke: {_q(p['merke'])}",
                  f"    farge: {_q(day)}",
                  f"    farge_kveld: {_q(night)}"]
        if p.get("barn"):
            lines.append("    barn: true")
    return "\n".join(lines) + "\n"


def write_env(path: Path, key: str, value: str) -> None:
    """Setter key=value i .env og beholder alle andre linjer."""
    old = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    kept = [l for l in old if l.split("=", 1)[0].strip() != key]
    path.write_text("\n".join(kept + [f"{key}={value}"]) + "\n", encoding="utf-8")


def copy_school_calendar(root: Path) -> bool:
    src, dst = root / "skolerute.example.yaml", root / "skolerute.yaml"
    if dst.exists() or not src.exists():
        return False
    shutil.copyfile(src, dst)
    return True


# ------------------------------------------------------------------ TV

class _Cfg(dict):
    """Det frame.pair/Frame trenger: cfg["frame"] og cfg.file("token.txt")."""
    def __init__(self, ip: str, data: Path):
        super().__init__(frame={"ip": ip, "port": 8002, "name": TV_NAME})
        self._data = data

    def file(self, name: str) -> str:
        return str(self._data / name)


def pair_tv(ip: str, data: Path) -> str:
    from tv.frame import FrameError, pair
    data.mkdir(exist_ok=True)
    try:
        result = asyncio.run(pair(_Cfg(ip, data)))
    except (FrameError, OSError, asyncio.TimeoutError) as exc:
        return f"Fikk ikke koblet til ({type(exc).__name__}). Sjekk at TV-en er på, og prøv igjen: python oppsett.py --par"
    if not (data / "token.txt").exists():
        return "TV-en ga ingen nøkkel. Prøv igjen: python oppsett.py --par"
    return f"Koblet til TV-en (Art API {result.get('api_version')})."


def _reachable(ip: str, port: int = 8002) -> bool:
    from tv.frame import reachable
    return reachable(ip, port)


def _pair_steps(ip: str, root: Path, pair, inp) -> None:
    print("\nKoble til TV-en:")
    print("  1. Slå på TV-en og sett den i Art Mode (kort trykk på av/på-knappen).")
    print("  2. Stå ved TV-en. Når den spør om å tillate «%s», velg Tillat (du har ca. 40 sekunder)." % TV_NAME)
    inp("  Trykk Enter når du er klar …")
    print("  " + pair(ip, root / "data"))


# ------------------------------------------------------------------ hovedløp

def run(root: Path = ROOT, inp=input, pair=pair_tv, reach=_reachable, fonts=None) -> int:
    print("Oppsett – svar på spørsmålene. Trykk Enter for å bruke forslaget i [klammer].\n")
    cfg_path = root / "config.yaml"
    if cfg_path.exists():
        if not ask_yes("Det finnes allerede en config.yaml. Lage en ny? (den gamle lagres som config.yaml.bak)",
                       False, inp):
            print("Ingenting er endret.")
            return 0

    print("\n1/5 Hjemmet – brukes til været fra Yr.")
    print("    Finn koordinatene ved å høyreklikke på huset i et kart (f.eks. norgeskart.no eller Google Maps).")
    lat = ask("    Breddegrad (lat)", None, lambda t: parse_coord(t, -90, 90), inp)
    lon = ask("    Lengdegrad (lon)", None, lambda t: parse_coord(t, -180, 180), inp)
    email = ask("    Din e-postadresse (sendes bare til MET Norway, som krever det)", None, parse_email, inp)

    print("\n2/5 TV-en.")
    print("    Adressen står på TV-en: Innstillinger → Generelt og personvern → Nettverk → Nettverksstatus → IP-innstillinger.")
    ip = ask("    TV-ens IP-adresse", None, parse_ip, inp)

    print("\n3/5 Familien – navnene vises på skjermen (gjester kan se dem, så fornavn eller kallenavn holder).")
    count = ask("    Hvor mange personer?", None, parse_count, inp)
    persons, used = [], set()
    for i in range(1, count + 1):
        navn = ask(f"    Person {i}: navn", None, parse_name, inp)
        merke = ask(f"    Person {i}: merke i kalenderen", default_mark(navn, used) or None,
                    lambda t: parse_mark(t, used), inp)
        used.add(merke)
        barn = ask_yes(f"    Er {navn} et barn?", False, inp)
        persons.append({"navn": navn, "merke": merke, "barn": barn})

    print("\n4/5 Familiekalenderen (valgfritt).")
    print("    Lim inn den offentlige .ics-lenken (iCloud: Del kalender → Offentlig kalender; Google: Hemmelig adresse i iCal-format).")
    print("    Lenken lagres bare i .env på denne maskinen. Tomt svar = hopp over.")
    link = ask("    Kalenderlenke", "", parse_link, inp)

    print("\n5/5 Skoleruta.")
    copy_school = False
    if (root / "skolerute.example.yaml").exists() and not (root / "skolerute.yaml").exists():
        copy_school = ask_yes("    Bruke eksempelskoleruta? (sjekk datoene mot din kommune etterpå)", True, inp)

    # -- skriv filene
    if cfg_path.exists():
        cfg_path.replace(root / "config.yaml.bak")
    cfg_path.write_text(config_text(lat, lon, email, ip, persons), encoding="utf-8")
    print("\nLaget config.yaml")
    if link:
        write_env(root / ".env", ENV_KEY, link)
        print("Lagret kalenderlenken i .env")
    if copy_school and copy_school_calendar(root):
        print("Laget skolerute.yaml – åpne den og sjekk datoene")
    (root / "bilder").mkdir(exist_ok=True)

    # -- fonter
    if fonts is None:
        import hent_fonter as fonts
    if set(fonts.check().values()) != {"ok"}:
        if ask_yes("\nHente fontene nå? (ca. 26 MB fra GitHub)", True, inp):
            fonts.download()

    # -- TV
    if reach(ip):
        if ask_yes("\nKoble til TV-en nå?", True, inp):
            _pair_steps(ip, root, pair, inp)
    else:
        print(f"\nTV-en på {ip} svarer ikke nå. Slå den på og kjør: python oppsett.py --par")

    print("\nFerdig! Prøv:")
    print("  python main.py --demo vinter --dry-run   # demobilde i output/, uten TV")
    print("  python main.py --dry-run                 # ekte data, uten TV")
    print("  python main.py                           # send bildet til TV-en")
    print("Vil du endre noe senere, åpne config.yaml.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Oppsett av innstillinger og TV.")
    parser.add_argument("--par", action="store_true", help="bare koble til TV-en på nytt")
    args = parser.parse_args(argv)
    if args.par:
        import yaml
        cfg_path = ROOT / "config.yaml"
        if not cfg_path.exists():
            print("Fant ikke config.yaml. Kjør først: python oppsett.py")
            return 1
        ip = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("tv", {}).get("ip")
        if not ip:
            print("config.yaml mangler tv: ip:")
            return 1
        if not _reachable(ip):
            print(f"TV-en på {ip} svarer ikke. Slå den på (Art Mode) og prøv igjen.")
            return 2
        _pair_steps(ip, ROOT, pair_tv, input)
        return 0
    try:
        return run()
    except (KeyboardInterrupt, EOFError):
        print("\nAvbrutt. Kjør python oppsett.py på nytt når du vil.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
