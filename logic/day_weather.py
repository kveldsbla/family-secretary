"""Gjør værpunkter om til det som skal stå på skjermen.

Alt her er rene beregninger uten nett, så det er enkelt å teste.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sources.weather import Point

# MET-symbolkoder (uten _day/_night) → norsk tekst og emoji.
SYMBOLS = {
    "clearsky": ("Klarvær", "☀️"),
    "fair": ("Lettskyet", "🌤️"),
    "partlycloudy": ("Delvis skyet", "⛅"),
    "cloudy": ("Skyet", "☁️"),
    "fog": ("Tåke", "🌫️"),
    "lightrain": ("Lett regn", "🌧️"),
    "rain": ("Regn", "🌧️"),
    "heavyrain": ("Kraftig regn", "🌧️"),
    "lightrainshowers": ("Lette regnbyger", "🌦️"),
    "rainshowers": ("Regnbyger", "🌦️"),
    "heavyrainshowers": ("Kraftige regnbyger", "🌦️"),
    "lightsleet": ("Lett sludd", "🌨️"),
    "sleet": ("Sludd", "🌨️"),
    "heavysleet": ("Kraftig sludd", "🌨️"),
    "lightsleetshowers": ("Lette sluddbyger", "🌨️"),
    "sleetshowers": ("Sluddbyger", "🌨️"),
    "heavysleetshowers": ("Kraftige sluddbyger", "🌨️"),
    "lightsnow": ("Lett snø", "❄️"),
    "snow": ("Snø", "❄️"),
    "heavysnow": ("Kraftig snø", "❄️"),
    "lightsnowshowers": ("Lette snøbyger", "🌨️"),
    "snowshowers": ("Snøbyger", "🌨️"),
    "heavysnowshowers": ("Kraftige snøbyger", "🌨️"),
}
NIGHT_EMOJI = {"clearsky": "🌙", "fair": "🌙"}


def describe_symbol(code: str | None) -> tuple[str, str]:
    """«lightrainshowers_day» → («Lette regnbyger», «🌦️»)."""
    if not code:
        return ("", "")
    base, _, variant = code.partition("_")
    thunder = base.endswith("andthunder")
    if thunder:
        base = base[: -len("andthunder")]
    text, emoji = SYMBOLS.get(base, (base, "🌡️"))
    if variant == "night" and base in NIGHT_EMOJI:
        emoji = NIGHT_EMOJI[base]
    if thunder:
        return (f"{text} og torden", "⛈️")
    return (text, emoji)


def feels_like(temp: float, wind_ms: float | None) -> float:
    """Effektiv temperatur med vindavkjøling (formelen MET og Yr også bruker).

    Gjelder bare når det er kaldt (≤ 10 °C) og blåser litt (> 4,8 km/t).
    Ellers er «føles som» det samme som temperaturen.
    """
    if wind_ms is None:
        return temp
    v = wind_ms * 3.6  # m/s → km/t
    if temp > 10 or v <= 4.8:
        return temp
    return 13.12 + 0.6215 * temp - 11.37 * v**0.16 + 0.3965 * temp * v**0.16


# ---------------------------------------------------------------- tekstformat

def fmt_temp(value: float | None) -> str:
    """-3,4 → «−3°». Bruker ekte minustegn og unngår «−0°»."""
    if value is None:
        return "–"
    n = round(value)
    return f"−{abs(n)}°" if n < 0 else f"{n}°"


def fmt_num(value: float, decimals: int = 1) -> str:
    """2.5 → «2,5» (norsk desimalkomma)."""
    return f"{value:.{decimals}f}".replace(".", ",")


# ---------------------------------------------------------------- oppsummering

def target_day(now: datetime, switch_hour: int) -> tuple[date, str]:
    """Fra og med byttetimen (kveld, standard kl. 18 i main.py) viser vi morgendagen i stedet."""
    if now.hour >= switch_hour:
        return (now.date() + timedelta(days=1), "I morgen")
    return (now.date(), "I dag")


def summarize(points: list[Point], now: datetime, school_from: int = 8,
              school_to: int = 15, show_hours: list[int] | None = None,
              evening_from: int | None = None) -> dict | None:
    """Lager innholdet til værdelen av bildet. Returnerer None hvis det ikke finnes data.

    `evening_from` er timen da bildet bytter til i morgen (kveldsbildet). Uten den brukes
    slutten på skoletiden, slik det var før fase 5.
    """
    if not points:
        return None
    show_hours = show_hours or [8, 12, 16]
    day, day_label = target_day(now, school_to if evening_from is None else evening_from)

    # «Nå»: punktet nærmest nå (varselet starter vanligvis ved inneværende time).
    current = min(points, key=lambda p: abs((p.time - now).total_seconds()))
    cur_text, cur_emoji = describe_symbol(current.symbol)

    # Små bokser for valgte klokkeslett på måldagen. Passerte klokkeslett hoppes over.
    by_time = {(p.time.date(), p.time.hour): p for p in points}
    periods = []
    for hour in show_hours:
        p = by_time.get((day, hour))
        if p is None or p.time < now - timedelta(minutes=30):
            continue
        text, emoji = describe_symbol(p.symbol)
        periods.append({"label": f"kl. {hour:02d}", "temp": fmt_temp(p.temp),
                        "emoji": emoji, "text": text})

    # Tidsrommet barna er ute: kaldeste «føles som», sum nedbør, sterkeste vind.
    # Morgen og skoletid: skoletiden. Etter skoletid (f.eks. kl. 15–18) gjelder resten av dagen,
    # fra nå til kvelden – barna kan gå ut, og klesrådet skal gjelde nå (06 #46).
    out_from, out_to = school_from, school_to
    if day == now.date() and now.hour >= school_to:
        out_from = now.hour
        # minst to timer, så det alltid er varsel å regne på (f.eks. kl. 17:55 gir kl. 17–19)
        out_to = max(evening_from if evening_from is not None else school_to, now.hour + 2)
    school = [p for p in points if p.time.date() == day and out_from <= p.time.hour < out_to]
    outdoor = None
    if school:
        coldest = min(feels_like(p.temp, p.wind) for p in school)
        precip = sum(p.precip or 0.0 for p in school)
        winds = [p.wind for p in school if p.wind is not None]
        outdoor = {
            "label": f"{day_label} kl. {out_from:02d}–{out_to:02d}",
            "feels_min": fmt_temp(coldest),
            "precip": fmt_num(precip),
            "wind_max": fmt_num(max(winds), 0) if winds else "–",
            # Rådata som klesreglene i fase 3 kan bruke direkte:
            "raw": {"feels_min": coldest, "precip": precip,
                    "wind_max": max(winds) if winds else None,
                    "symbols": [p.symbol for p in school]},
        }

    return {
        "now": {
            "temp": fmt_temp(current.temp),
            "feels": fmt_temp(feels_like(current.temp, current.wind)),
            "show_feels": fmt_temp(feels_like(current.temp, current.wind)) != fmt_temp(current.temp),
            "emoji": cur_emoji,
            "text": cur_text,
        },
        "day_label": day_label,
        "periods": periods,
        "outdoor": outdoor,
    }
