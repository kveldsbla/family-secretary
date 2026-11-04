"""Værvarsel fra MET Norway (Yr): Locationforecast 2.0, «compact».

Vilkår fra MET som koden følger:
- Identifiserende User-Agent med kontaktinfo (settes i config.yaml).
- Maks 4 desimaler i koordinatene.
- Ikke spør igjen før tidspunktet i «Expires» er passert, og send «If-Modified-Since».
- Data er lisensiert CC BY 4.0: vis «Værdata: MET Norway» på bildet.

Hvis nettet eller MET feiler, brukes forrige svar fra hurtigbufferen (data/weather_cache.json).
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

API_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
log = logging.getLogger(__name__)


class WeatherError(Exception):
    """Vær kunne ikke hentes, og det finnes ingen brukbar hurtigbuffer."""


@dataclass
class Point:
    """Ett tidspunkt i varselet, i lokal tid."""
    time: datetime
    temp: float
    wind: float | None          # m/s
    symbol: str | None          # MET-symbolkode, f.eks. «lightrain_day»
    precip: float | None        # mm neste time


# ---------------------------------------------------------------- henting

def fetch_forecast(lat: float, lon: float, user_agent: str, cache_file: Path,
                   altitude: int | None = None, now: datetime | None = None,
                   session=None) -> dict:
    """Henter varsel fra MET og returnerer JSON-svaret som en dict."""
    if not user_agent or "eksempel" in user_agent:
        raise WeatherError("Sett yr.user_agent i config.yaml til din egen e-postadresse.")

    now = now or datetime.now(timezone.utc)
    params = {"lat": round(float(lat), 4), "lon": round(float(lon), 4)}
    if altitude is not None:
        params["altitude"] = int(altitude)

    cache = _read_cache(cache_file)
    same_place = bool(cache) and cache.get("params") == params

    # 1) Hurtigbufferen er fortsatt gyldig: ikke spør MET i det hele tatt.
    if same_place:
        expires = _parse_http_date(cache.get("expires"))
        if expires and now < expires:
            log.info("Vær: bruker hurtigbuffer (gyldig til %s)", expires.isoformat())
            return cache["data"]

    headers = {"User-Agent": user_agent}
    if same_place and cache.get("last_modified"):
        headers["If-Modified-Since"] = cache["last_modified"]

    http = session or requests
    try:
        resp = http.get(API_URL, params=params, headers=headers, timeout=15)
    except requests.RequestException as exc:
        return _fallback(cache, same_place, f"nettverksfeil: {exc}")

    # 2) Ikke endret siden sist: bruk hurtigbufferen, men oppdater utløpstiden.
    if resp.status_code == 304 and same_place:
        cache["expires"] = resp.headers.get("Expires", cache.get("expires"))
        _write_cache(cache_file, cache)
        log.info("Vær: uendret hos MET (304), bruker hurtigbuffer")
        return cache["data"]

    # 3) Nytt svar.
    if resp.status_code in (200, 203):
        if resp.status_code == 203:
            log.warning("MET svarte 203: denne API-versjonen er på vei ut. Sjekk api.met.no.")
        try:
            data = resp.json()
        except ValueError:
            return _fallback(cache, same_place, "MET sendte ugyldig JSON")
        _write_cache(cache_file, {
            "params": params,
            "expires": resp.headers.get("Expires"),
            "last_modified": resp.headers.get("Last-Modified"),
            "data": data,
        })
        log.info("Vær: nytt varsel hentet fra MET")
        return data

    reasons = {
        403: "403 – MET avviste forespørselen (sjekk User-Agent i config.yaml)",
        429: "429 – for mange forespørsler; vent litt",
    }
    return _fallback(cache, same_place, reasons.get(resp.status_code, f"HTTP {resp.status_code}"))


def _fallback(cache: dict | None, same_place: bool, reason: str) -> dict:
    if same_place and cache and cache.get("data"):
        log.warning("Vær: %s. Bruker forrige varsel fra hurtigbufferen.", reason)
        return cache["data"]
    raise WeatherError(f"Kunne ikke hente vær: {reason}")


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _read_cache(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(path: Path, content: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(content), encoding="utf-8")
        tmp.replace(path)  # skriv ferdig fil først, så en halvskrevet fil aldri blir liggende
    except OSError as exc:
        log.warning("Klarte ikke å lagre værbufferen: %s", exc)


# ---------------------------------------------------------------- tolking

def parse_points(data: dict, tz: ZoneInfo) -> list[Point]:
    """Gjør MET-svaret om til en liste med tidspunkter i lokal tid."""
    points = []
    for entry in data.get("properties", {}).get("timeseries", []):
        try:
            t = datetime.fromisoformat(entry["time"].replace("Z", "+00:00")).astimezone(tz)
            d = entry["data"]
            inst = d["instant"]["details"]
            nxt = d.get("next_1_hours") or d.get("next_6_hours") or {}
            points.append(Point(
                time=t,
                temp=float(inst["air_temperature"]),
                wind=inst.get("wind_speed"),
                symbol=nxt.get("summary", {}).get("symbol_code"),
                precip=(d.get("next_1_hours") or {}).get("details", {}).get("precipitation_amount"),
            ))
        except (KeyError, TypeError, ValueError):
            continue  # hopp over et ødelagt punkt i stedet for å feile helt
    return points


# ---------------------------------------------------------------- demodata

DEMO_SCENARIOS = {
    # navn: (middeltemp, døgnvariasjon, vind m/s, symbol om dagen, nedbør mm/t)
    "vinter": (-4.0, 3.0, 5.0, "lightsnow", 0.4),
    "regn": (6.0, 2.0, 7.0, "rain", 1.2),
    "sol": (17.0, 5.0, 2.0, "clearsky", 0.0),
}


def demo_forecast(now_utc: datetime, scenario: str = "vinter") -> dict:
    """Lager oppdiktede data i samme format som MET, for test uten nett."""
    mean, amp, wind, symbol, precip = DEMO_SCENARIOS[scenario]
    start = now_utc.replace(minute=0, second=0, microsecond=0)
    series = []
    for h in range(48):
        t = start + timedelta(hours=h)
        local_hour = (t.hour + 1) % 24  # omtrent norsk tid, godt nok for demo
        temp = mean + amp * math.sin((local_hour - 9) / 24 * 2 * math.pi)
        day = 8 <= local_hour < 17
        sym = (symbol if day else "cloudy") + ("_day" if symbol in ("clearsky", "fair") and day else "")
        series.append({
            "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": {
                "instant": {"details": {"air_temperature": round(temp, 1), "wind_speed": wind}},
                "next_1_hours": {
                    "summary": {"symbol_code": sym},
                    "details": {"precipitation_amount": precip if day else 0.0},
                },
            },
        })
    return {"type": "Feature", "properties": {"timeseries": series}}
