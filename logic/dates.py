"""Norske dag- og månedsnavn og ukenummer.

Vi bruker egne lister i stedet for operativsystemets språkinnstillinger (locale),
fordi de er forskjellige på Windows og Raspberry Pi.
"""
from __future__ import annotations

from datetime import date

UKEDAGER = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MANEDER = [
    "januar", "februar", "mars", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "desember",
]


def norsk_dato(d: date) -> dict:
    """Returnerer tekstbitene til datolinjen, f.eks. Mandag / 2. november / uke 45."""
    return {
        "ukedag": UKEDAGER[d.weekday()].capitalize(),
        "dato": f"{d.day}. {MANEDER[d.month - 1]}",
        "uke": d.isocalendar().week,  # ISO-ukenummer, slik vi bruker i Norge
        "aar": d.year,
    }
