"""Leser hemmeligheter fra .env (NØKKEL=verdi per linje).

Bevisst enkel, så vi slipper et ekstra bibliotek:
- tomme linjer og linjer som starter med # hoppes over
- anførselstegn rundt verdien fjernes
- verdier skrives aldri til logg eller skjerm
"""
from __future__ import annotations

from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    """Returnerer {NØKKEL: verdi}. Mangler filen, returneres en tom dict."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():   # -sig: tåler BOM fra Notisblokk
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values
