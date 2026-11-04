"""Henter fontene bildet bruker, fra der de ligger på nettet.

Fontene ligger ikke i dette repoet. Skriptet laster dem ned fra faste, låste adresser
og sjekker at hver fil er nøyaktig den vi har testet (SHA-256-sjekksum). Er en fil endret
eller ødelagt underveis, lagres den ikke.

    python hent_fonter.py           # hent fontene som mangler
    python hent_fonter.py --sjekk   # bare sjekk fontene du har, uten nedlasting

Uten fonter virker programmet likevel, men da brukes maskinens egne fonter (og emojiene
kan se annerledes ut, eller mangle).

Kilder (alle under SIL Open Font License 1.1, lisensteksten lastes ned sammen med fontene):
- Cormorant Garamond og Jost: fra smart-frame-tv, commit b124b8e
- Noto Color Emoji 2.055: fra Google Fonts sitt repo, commit c08cd28 (ca. 25 MB)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

FONTS = Path(__file__).resolve().parent / "render" / "static" / "fonts"

_SMART = ("https://raw.githubusercontent.com/Seagey/smart-frame-tv/"
          "b124b8e7475f9a9cba56b161db518f1070504bba/smartframe/fonts/")
_NOTO = ("https://raw.githubusercontent.com/google/fonts/"
         "c08cd288696d8ca30bf0296dc214d80d33a65d8f/ofl/notocoloremoji/")

# (filnavn her, adresse, SHA-256)
FILES: list[tuple[str, str, str]] = [
    ("CormorantGaramond-Medium.ttf", _SMART + "CormorantGaramond-Medium.ttf",
     "1724047c8988ca5155bff667bc48fa52e97d57aabc6b42eebbf986f21a4be20b"),
    ("CormorantGaramond-MediumItalic.ttf", _SMART + "CormorantGaramond-MediumItalic.ttf",
     "14efb9443652199ade5bc6ba8637b4084acce40a58368a3808f84f55667e3e90"),
    ("CormorantGaramond-SemiBold.ttf", _SMART + "CormorantGaramond-SemiBold.ttf",
     "69e7ae35cba23d962227b86f99217c250e642e4c6f6104b4f3ec465039e4e2d8"),
    ("Jost-Medium.ttf", _SMART + "Jost-Medium.ttf",
     "d6ff7726ec21576cf2fdac55080b2d43832780fa981f03f0b66d2723a7c1ea09"),
    ("Jost-Regular.ttf", _SMART + "Jost-Regular.ttf",
     "c3143e923ed1ca7bdf27f96c351fbafaebcbd3cf3f4c2d30d03e6c7f98e73d7a"),
    ("OFL-CormorantGaramond.txt", _SMART + "OFL-CormorantGaramond.txt",
     "b2306305139223cbc000c2b9feffaa741687056066c227ba34de31c98eda0814"),
    ("OFL-Jost.txt", _SMART + "OFL-Jost.txt",
     "13ab39f8a41a040f24348b09885c1c7e16b8ffb63ca89046630a9da65c35a276"),
    ("NotoColorEmoji-Regular.ttf", _NOTO + "NotoColorEmoji-Regular.ttf",
     "4d82a18d8d95f60ba883ce242bbadbf84a576e987745dd7ba38d71c67cff2d73"),
    ("OFL-NotoColorEmoji.txt", _NOTO + "OFL.txt",
     "ac564676d10054a8445923dfc2dfb13c042d97888bd27c1b6ec6dfe89a9d8d62"),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "family-secretary-fonts/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check(folder: Path = FONTS) -> dict[str, str]:
    """Returnerer {filnavn: "ok" | "mangler" | "endret"}."""
    status = {}
    for name, _url, digest in FILES:
        path = folder / name
        if not path.exists():
            status[name] = "mangler"
        else:
            status[name] = "ok" if sha256(path.read_bytes()) == digest else "endret"
    return status


def download(folder: Path = FONTS, fetcher=fetch) -> int:
    """Henter filene som mangler eller er endret. Returnerer antall feil."""
    folder.mkdir(parents=True, exist_ok=True)
    errors = 0
    for name, url, digest in FILES:
        path = folder / name
        if path.exists() and sha256(path.read_bytes()) == digest:
            print(f"  OK       {name} (finnes)")
            continue
        try:
            data = fetcher(url)
        except Exception as exc:          # nettfeil, 404 osv.
            print(f"  FEIL     {name}: kunne ikke laste ned ({type(exc).__name__})")
            errors += 1
            continue
        if sha256(data) != digest:
            print(f"  FEIL     {name}: sjekksummen stemmer ikke – filen er ikke lagret")
            errors += 1
            continue
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print(f"  HENTET   {name} ({len(data) // 1024} kB)")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Henter fontene bildet bruker.")
    parser.add_argument("--sjekk", action="store_true", help="bare sjekk, ikke last ned")
    args = parser.parse_args(argv)
    if args.sjekk:
        status = check()
        for name, s in status.items():
            print(f"  {s.upper():8} {name}")
        bad = sum(s != "ok" for s in status.values())
        print("Alle fontene er på plass." if not bad else f"{bad} fil(er) mangler eller er endret – kjør python hent_fonter.py")
        return 0 if not bad else 1
    print(f"Henter fonter til {FONTS} …")
    errors = download()
    print("Ferdig – alle fontene er på plass." if not errors
          else f"{errors} fil(er) feilet. Sjekk nettforbindelsen og prøv igjen.")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
