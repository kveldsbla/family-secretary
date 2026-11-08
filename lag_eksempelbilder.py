"""Lager eksempelbildene til README i docs/eksempler/ – bare med demodata.

Været, kalenderen og soltidene er oppdiktet (--demo), personene er oppdiktet, og fotoet vises ikke.
Ingenting sendes til TV-en. Nedtellingen bruker skolerute.example.yaml og datoen i dag.

Bruk (fra prosjektmappen, etter hent_fonter.py):
  .venv\\Scripts\\python lag_eksempelbilder.py        (Windows)
  .venv/bin/python lag_eksempelbilder.py            (Mac, Raspberry Pi)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent
UT = ROOT / "docs" / "eksempler"
OUTPUT = ROOT / "output"
CONFIG = OUTPUT / "_eksempel-config.yaml"   # output/ er utenfor Git
BREDDE, HOYDE = 1920, 1080                  # halv størrelse holder for README

# Oppdiktet familie med paletten fra config.example.yaml
PERSONER = [
    {"navn": "Eva", "merke": "E", "farge": "#6d5a4a", "farge_kveld": "#dbb996"},
    {"navn": "Ola", "merke": "O", "farge": "#2f6aa8", "farge_kveld": "#6aa5e0"},
    {"navn": "Jens", "merke": "J", "farge": "#1e8a6e", "farge_kveld": "#9ee4c6", "barn": True},
    {"navn": "Liv", "merke": "L", "farge": "#c96f22", "farge_kveld": "#e28030", "barn": True},
    {"navn": "Mia", "merke": "M", "farge": "#a64d86", "farge_kveld": "#d68aaf", "barn": True},
]

# filnavn, valg til main.py
BILDER = [
    ("dag", ["--demo", "vinter", "--tid", "07:00"]),
    ("kveld", ["--demo", "vinter", "--tid", "kveld"]),
    ("na-ma-du-dra", ["--demo", "vinter", "--dra"]),
    ("iskaldt", ["--demo", "iskaldt", "--tid", "07:00"]),
]


def main() -> int:
    OUTPUT.mkdir(exist_ok=True)
    UT.mkdir(parents=True, exist_ok=True)
    cfg = {"personer": PERSONER, "dra": {"skolerute": "skolerute.example.yaml"}, "foto": {"vis": False}}
    CONFIG.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        for navn, valg in BILDER:
            print(f"Lager {navn} …")
            kommando = [sys.executable, "main.py", *valg, "--dry-run", "--config", CONFIG.relative_to(ROOT).as_posix()]
            if subprocess.run(kommando, cwd=ROOT).returncode != 0:
                print(f"Stoppet: main.py feilet for «{navn}» – se meldingene over.")
                return 1
            fil = UT / f"{navn}.jpg"
            with Image.open(OUTPUT / "siste.png") as bilde:
                bilde.convert("RGB").resize((BREDDE, HOYDE), Image.LANCZOS).save(fil, quality=85, optimize=True)
            print(f"   {fil.relative_to(ROOT)} ({fil.stat().st_size // 1024} kB)")
    finally:
        CONFIG.unlink(missing_ok=True)
    print("Ferdig. Se på bildene før de committes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
