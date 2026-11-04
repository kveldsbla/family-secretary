"""Ikoner for «Ute i dag» – så de minste forstår hvorfor vi sier som vi sier.

Hver av de tre opplysningene (føles som, nedbør, vind) får ett ikon og et kort ord.
Tallene står fortsatt på bildet for oss voksne.

Temperaturtrinnene og nedbørsgrensen er de samme som i klesrådet (logic/clothing.py),
så ikonet og klesrådet aldri sier noe forskjellig. Alt kan overstyres i config.yaml
under «ute:» (og grensene under «klesrad:»).
"""
from __future__ import annotations

import copy

from logic.clothing import load_rules, precip_types, temperature_step

DEFAULTS: dict = {
    "foles": {
        "iskaldt":      ["🧊", "Iskaldt"],          # under −20
        "veldig_kaldt": ["🥶", "Veldig kaldt"],     # −20 til −11
        "kaldt":        ["⛄", "Kaldt"],            # −10 til −1
        "kjolig":       ["🧣", "Kjølig"],
        "mildt":        ["🙂", "Mildt"],
        "varmt":        ["😎", "Varmt"],
    },
    "nedbor": {
        "ingen":  ["🌂", "Tørt"],          # lukket paraply: ingen trengs
        "litt":   ["💧", "Litt"],          # under regngrensen i klesrådet (1 mm)
        "regn":   ["☔", "Regn"],
        "sludd":  ["🌨️", "Sludd"],
        "sno":    ["❄️", "Snø"],
    },
    "nedbor_min_mm": 0.1,                  # mindre enn dette regnes som tørt
    "vind": {
        "rolig":  ["🍃", "Rolig"],
        "litt":   ["💨", "Litt vind"],
        "mye":    ["🌬️", "Mye vind"],
    },
    "vind_litt_ms": 4,                     # fra og med dette: «litt vind»
    # «mye vind» følger klesrad.vind_ms (standard 8), så vindtett-rådet og ikonet henger sammen
}


def load_ute(override: dict | None) -> dict:
    rules = copy.deepcopy(DEFAULTS)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(rules.get(key), dict):
            rules[key].update(value)
        else:
            rules[key] = value
    return rules


def _pair(value) -> dict:
    emoji, text = value
    return {"emoji": str(emoji), "tekst": str(text)}


def outdoor_icons(raw: dict | None, ute: dict | None = None, klesrad: dict | None = None) -> dict | None:
    """Rådata for skoletiden → {«foles»|«nedbor»|«vind»: {emoji, tekst}}. None uten data."""
    if not raw or raw.get("feels_min") is None:
        return None
    rules = load_ute(ute)
    cloth = load_rules(klesrad)

    step = temperature_step(float(raw["feels_min"]), cloth["grenser"])

    precip = float(raw.get("precip") or 0.0)
    types = precip_types(raw.get("symbols") or [])
    if precip < float(rules["nedbor_min_mm"]):
        rain_key = "ingen"
    elif "sno" in types:
        rain_key = "sno"
    elif "sludd" in types:
        rain_key = "sludd"
    elif precip > float(cloth["regn_mm"]):
        rain_key = "regn"
    else:
        rain_key = "litt"

    wind = raw.get("wind_max")
    if wind is None:
        wind_icon = {"emoji": "", "tekst": ""}
    else:
        wind = float(wind)
        if wind > float(cloth["vind_ms"]):
            wind_key = "mye"
        elif wind >= float(rules["vind_litt_ms"]):
            wind_key = "litt"
        else:
            wind_key = "rolig"
        wind_icon = _pair(rules["vind"][wind_key])

    return {
        "foles": _pair(rules["foles"][step]),
        "nedbor": _pair(rules["nedbor"][rain_key]),
        "vind": wind_icon,
    }
