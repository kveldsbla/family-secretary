"""Soloppgang og solnedgang fra MET Norway: Sunrise 3.0, /sun (I-12).

Vilkår fra MET som koden følger (samme som været):
- Identifiserende User-Agent med kontaktinfo (yr.user_agent i config.yaml).
- Maks 4 desimaler i koordinatene.
- Ikke spør oftere enn nødvendig. Soltidene for en dato endrer seg aldri, så hver dato hentes
  bare én gang og legges i data/sun_cache.json. (Det er sjeldnere enn «Expires» krever.)
- Data er lisensiert CC BY 4.0: krediteringen «Vær- og soldata: MET Norway» står på bildet.

Kveldskjøringen henter morgendagen, så morgenbildet har soltidene selv om nettet er nede.
Midnattssol og mørketid: MET sender «time: null» for opp og ned, og solarnoon.visible sier hvilken.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

API_URL = "https://api.met.no/weatherapi/sunrise/3.0/sun"
KEEP_DAYS = 10            # så mange datoer beholdes i hurtigbufferen
log = logging.getLogger(__name__)


class SunError(Exception):
    """Soltidene kunne ikke hentes, og datoen finnes ikke i hurtigbufferen."""


# ---------------------------------------------------------------- henting

def _offset(day: date, tz: ZoneInfo) -> str:
    """Tidssoneforskyvningen for datoen, f.eks. «+01:00» om vinteren og «+02:00» om sommeren."""
    minutes = int(datetime(day.year, day.month, day.day, 12, tzinfo=tz).utcoffset().total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def fetch_sun(lat: float, lon: float, day: date, tz: ZoneInfo, user_agent: str,
              cache_file: Path, session=None) -> dict:
    """Henter «properties» fra MET for én dato. Datoer som er hentet før, tas fra hurtigbufferen."""
    if not user_agent or "eksempel" in user_agent:
        raise SunError("Sett yr.user_agent i config.yaml til din egen e-postadresse.")

    place = {"lat": round(float(lat), 4), "lon": round(float(lon), 4)}
    key = day.isoformat()
    cache = _read_cache(cache_file)
    if not cache or cache.get("sted") != place:
        cache = {"sted": place, "dager": {}}
    if key in cache["dager"]:
        return cache["dager"][key]

    params = {**place, "date": key, "offset": _offset(day, tz)}
    http = session or requests
    try:
        resp = http.get(API_URL, params=params, headers={"User-Agent": user_agent}, timeout=15)
    except requests.RequestException as exc:
        raise SunError(f"nettverksfeil ({type(exc).__name__})") from None
    if resp.status_code == 203:
        log.warning("MET svarte 203: Sunrise 3.0 er på vei ut. Sjekk api.met.no.")
    elif resp.status_code != 200:
        reasons = {403: "403 – MET avviste forespørselen (sjekk User-Agent i config.yaml)",
                   429: "429 – for mange forespørsler; vent litt"}
        raise SunError(reasons.get(resp.status_code, f"HTTP {resp.status_code}"))
    try:
        props = resp.json()["properties"]
        props["sunrise"], props["sunset"]       # finnes de ikke, er svaret ubrukelig
    except (ValueError, KeyError, TypeError):
        raise SunError("MET sendte et svar uten soltider") from None

    cache["dager"][key] = props
    keep = sorted(cache["dager"])[-KEEP_DAYS:]    # ISO-datoer sorteres riktig som tekst
    cache["dager"] = {k: cache["dager"][k] for k in keep}
    _write_cache(cache_file, cache)
    return props


def _read_cache(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("dager"), dict) else None
    except (OSError, ValueError):
        return None


def _write_cache(path: Path, content: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(content), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("Klarte ikke å lagre solbufferen: %s", exc)


# ---------------------------------------------------------------- tolking

def parse_sun(props: dict, tz: ZoneInfo) -> dict:
    """MET-svaret → {"opp", "ned" (datetime eller None), "polar" (None/«midnattssol»/«mørketid»),
    "minutter" (dagslengde)}. Kaster ValueError hvis svaret ikke kan brukes."""
    def when(name):
        t = (props.get(name) or {}).get("time")
        return datetime.fromisoformat(t).astimezone(tz) if t else None

    up, down = when("sunrise"), when("sunset")
    if up and down:
        return {"opp": up, "ned": down, "polar": None,
                "minutter": round((down - up).total_seconds() / 60)}
    if not up and not down:
        visible = (props.get("solarnoon") or {}).get("visible")
        if visible is True:
            return {"opp": None, "ned": None, "polar": "midnattssol", "minutter": 24 * 60}
        if visible is False:
            return {"opp": None, "ned": None, "polar": "mørketid", "minutter": 0}
    # Bare én av dem (skjer bare nær polarsirkelen): for usikkert til å vise noe.
    raise ValueError("ufullstendige soltider")


def _length(minutes: int) -> str:
    return f"{minutes // 60} t {minutes % 60} min"


def sun_line(today: dict, before: dict | None, show_change: str = "alltid") -> dict:
    """Det malen trenger: {"opp": "07:47", "ned": "16:15", "lengde": "8 t 28 min", "endring": "−5 min"}.

    `before` er dagen før (for endringen), eller None. show_change: «alltid», «lengre» (bare når
    dagene blir lengre) eller «aldri». Ved midnattssol/mørketid: {"polar": "Midnattssol"} o.l.
    """
    if today["polar"]:
        return {"polar": today["polar"].capitalize()}
    line = {"opp": f"{today['opp']:%H:%M}", "ned": f"{today['ned']:%H:%M}",
            "lengde": _length(today["minutter"]), "endring": None}
    if before is not None and show_change != "aldri":
        diff = today["minutter"] - before["minutter"]
        if diff > 0:
            line["endring"] = f"+{diff} min"
        elif diff < 0 and show_change == "alltid":
            line["endring"] = f"−{-diff} min"          # ekte minustegn, som i temperaturene
        elif diff == 0 and show_change == "alltid":
            line["endring"] = "±0 min"
    return line


# ---------------------------------------------------------------- demodata

def demo_sun(day: date, tz: ZoneInfo, day_before: bool = False) -> dict:
    """Oppdiktede soltider i samme format som MET: en vinterdag i januar, da dagene blir lengre.

    Dagen er 08:58–15:42 (6 t 44 min). Med day_before=True: 08:59–15:40, så endringen blir «+3 min».
    """
    def t(h, m):
        return datetime(day.year, day.month, day.day, h, m, tzinfo=tz).isoformat()
    up, down = ((8, 59), (15, 40)) if day_before else ((8, 58), (15, 42))
    return {"sunrise": {"time": t(*up)}, "sunset": {"time": t(*down)}, "solarnoon": {"visible": True}}
