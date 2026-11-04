"""Klesråd: gjør været i skoletiden om til en værkategori og en huskeliste.

Inn: rådataene fra day_weather.summarize() (vaer["outdoor"]["raw"]):
    feels_min  kaldeste «føles som» i skoletiden (°C)
    precip     sum nedbør i skoletiden (mm)
    wind_max   sterkeste vind i skoletiden (m/s), kan være None
    symbols    MET-symbolkoder for hver time, f.eks. «lightsnow»

Ut: en dict med
    kategori     «kaldt» | «kjolig» | «mildt» | «varmt»  (styrer værfiguren)
    regn, sno    True/False – tillegg til værfiguren
    figur        emojiene som skal tegnes (fra config.yaml)
    huskeliste   plaggene som trengs, uten dubletter

Reglene kommer fra 02-Innhold-og-datakilder. Alle grenser, plagg og emojier
kan overstyres i config.yaml under «klesrad:», uten å endre koden.
Grensene sammenlignes med avrundet temperatur – samme tall som står på skjermen.
"""
from __future__ import annotations

import copy

# Standardregler. config.yaml kan overstyre hver nøkkel for seg.
DEFAULTS: dict = {
    # «Føles som»-grenser i °C. Avrundet temperatur UNDER grensen gir trinnet.
    #   under −20 → iskaldt · −20 til −11 → veldig_kaldt · −10 til −1 → kaldt
    #   0 til 7 → kjolig · 8 til 15 → mildt · over 15 → varmt
    "grenser": {"iskaldt": -20, "veldig_kaldt": -10, "kaldt": 0, "kjolig": 8, "mildt": 16},
    "regn_mm": 1.0,     # mer nedbør enn dette i skoletiden → regntøy
    "vind_ms": 8.0,     # sterkere vind enn dette → vindtett
    # Emojier i værfiguren.
    "figur": {
        "kaldt": ["🥶", "⛄"],
        "kjolig": ["🧥", "🧤"],
        "mildt": ["🧥"],
        "varmt": ["😎", "👕"],
        "regn": ["☔", "👢"],
        "sno": ["❄️"],
    },
    # Huskelisten.
    "huskeliste": {
        "iskaldt": ["Ull innerst", "Ullfleece", "Vinterdress", "Lue", "Balaklava",
                    "Tykke votter", "Vintersko", "Kuldekrem"],
        "veldig_kaldt": ["Ull innerst", "Ullfleece", "Vinterdress", "Lue", "Hals",
                         "Tykke votter", "Vintersko"],
        "kaldt": ["Ull innerst", "Vinterdress", "Lue", "Votter", "Vintersko"],
        "kjolig": ["Fleece eller tynn ull", "Høstjakke eller dress", "Lue", "Tynne votter"],
        "mildt": ["Genser", "Lett jakke"],
        "varmt": ["T-skjorte", "Tynn genser i sekken"],
        # Tillegg
        "regn": ["Regntøy", "Støvler"],
        "regn_kaldt": ["Vanntett ytterst", "Vanntette vintersko"],
        "sludd": ["Vanntett ytterst", "Ekstra votter i sekken"],
        "sno": ["Ekstra votter i sekken"],
        "vind": ["Vindtett ytterst", "Hals"],
        "sol": ["Solhatt"],
    },
}

CATEGORY_TEXT = {"kaldt": "Kaldt", "kjolig": "Kjølig", "mildt": "Mildt", "varmt": "Varmt"}
SUNNY = ("clearsky", "fair")


def load_rules(override: dict | None) -> dict:
    """Standardregler med det som står i config.yaml («klesrad:») lagt over."""
    rules = copy.deepcopy(DEFAULTS)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(rules.get(key), dict):
            rules[key].update(value)      # f.eks. bare figur.kaldt endret
        else:
            rules[key] = value
    return rules


def temperature_step(feels: float, limits: dict) -> str:
    """−4,6 → «kaldt». Bruker avrundet tall, som på skjermen."""
    t = round(feels)
    for step in ("iskaldt", "veldig_kaldt", "kaldt", "kjolig", "mildt"):
        if t < limits[step]:
            return step
    return "varmt"


def precip_types(symbols: list[str | None]) -> set[str]:
    """Hvilke typer nedbør symbolene nevner: {«regn», «sludd», «sno»}."""
    found = set()
    for code in symbols or []:
        base = (code or "").split("_")[0]
        if "sleet" in base:
            found.add("sludd")
        elif "snow" in base:
            found.add("sno")
        elif "rain" in base:
            found.add("regn")
    return found


def _unique(items: list[str]) -> list[str]:
    """Fjerner dubletter, men beholder rekkefølgen."""
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def clothing_advice(raw: dict | None, override: dict | None = None) -> dict | None:
    """Hovedfunksjonen. Returnerer None hvis det ikke finnes værdata for skoletiden."""
    if not raw or raw.get("feels_min") is None:
        return None
    rules = load_rules(override)
    lists = rules["huskeliste"]

    feels = float(raw["feels_min"])
    precip = float(raw.get("precip") or 0.0)
    wind = raw.get("wind_max")
    symbols = raw.get("symbols") or []

    step = temperature_step(feels, rules["grenser"])
    category = "kaldt" if step in ("iskaldt", "veldig_kaldt") else step
    cold = category == "kaldt"

    types = precip_types(symbols)
    wet = precip > float(rules["regn_mm"])
    rain = wet and ("regn" in types or not types)      # mye nedbør uten symbol: regn til sikkerhet
    sleet = "sludd" in types
    snow = "sno" in types
    windy = wind is not None and float(wind) > float(rules["vind_ms"])
    sunny = any((s or "").split("_")[0] in SUNNY for s in symbols)

    # Huskeliste: grunnlag etter temperatur, deretter tillegg.
    items = list(lists[step])
    if rain:
        items += lists["regn_kaldt"] if cold else lists["regn"]
    if sleet:
        items += lists["sludd"]
    if snow:
        items += lists["sno"]
    if windy:
        items += lists["vind"]
    if sunny and category == "varmt":
        items += lists["sol"]

    # Værfigur: kategori + regn (også ved sludd) + snø.
    show_rain = rain or sleet
    figure = list(rules["figur"][category])
    if show_rain:
        figure += rules["figur"]["regn"]
    if snow:
        figure += rules["figur"]["sno"]

    return {
        "kategori": category,
        "kategori_tekst": CATEGORY_TEXT[category],
        "trinn": step,
        "regn": show_rain,
        "sno": snow,
        "vind": windy,
        "figur": _unique(figure),
        "huskeliste": _unique(items),
    }


def summary_line(advice: dict | None) -> str:
    """Kort tekst til loggen, uten emojier (de vises dårlig i PowerShell)."""
    if not advice:
        return "ingen værdata for skoletiden"
    extras = [name for name in ("regn", "sno", "vind") if advice[name]]
    head = advice["trinn"].replace("_", " ") + "".join(f" + {e}" for e in extras)
    return f"{head} – {', '.join(advice['huskeliste'])}"
