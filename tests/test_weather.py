"""Tester for vær: tolking, beregninger, hurtigbuffer og datotekst. Ingen nett nødvendig."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import requests

from logic.dates import norsk_dato
from logic.day_weather import describe_symbol, feels_like, fmt_num, fmt_temp, summarize
from sources.weather import WeatherError, demo_forecast, fetch_forecast, parse_points

OSLO = ZoneInfo("Europe/Oslo")
UA = "familiehub-test/0.1 test@test.no"


# ---------------------------------------------------------------- dato

def test_norsk_dato():
    d = norsk_dato(date(2026, 11, 2))
    assert d == {"ukedag": "Mandag", "dato": "2. november", "uke": 45, "aar": 2026}
    assert norsk_dato(date(2027, 1, 1))["uke"] == 53   # 1. jan 2027 er en fredag i uke 53
    assert norsk_dato(date(2026, 8, 15))["ukedag"] == "Lørdag"


# ---------------------------------------------------------------- symboler og tall

@pytest.mark.parametrize("code, text", [
    ("lightrainshowers_day", "Lette regnbyger"),
    ("cloudy", "Skyet"),
    ("heavysnowandthunder", "Kraftig snø og torden"),
    ("clearsky_night", "Klarvær"),
    ("ukjentsymbol", "ukjentsymbol"),
])
def test_describe_symbol(code, text):
    assert describe_symbol(code)[0] == text


def test_feels_like():
    assert feels_like(12, 8) == 12            # for varmt for vindavkjøling
    assert feels_like(-5, 1.0) == -5          # nesten vindstille
    assert round(feels_like(-2, 5)) == -7     # typisk novembermorgen
    assert feels_like(3, None) == 3


def test_formatting():
    assert fmt_temp(-3.4) == "−3°"
    assert fmt_temp(-0.4) == "0°"             # aldri «−0°»
    assert fmt_temp(None) == "–"
    assert fmt_num(2.5) == "2,5"
    assert fmt_num(7.0, 0) == "7"


# ---------------------------------------------------------------- oppsummering

def _points(now_local):
    return parse_points(demo_forecast(now_local.astimezone(timezone.utc), "vinter"), OSLO)


def test_summary_morning_shows_today():
    now = datetime(2026, 11, 2, 6, 0, tzinfo=OSLO)
    s = summarize(_points(now), now)
    assert s["day_label"] == "I dag"
    assert [p["label"] for p in s["periods"]] == ["kl. 08", "kl. 12", "kl. 16"]
    assert s["outdoor"]["label"] == "I dag kl. 08–15"
    assert s["outdoor"]["raw"]["precip"] > 0


def test_summary_after_school_shows_tomorrow():
    now = datetime(2026, 11, 2, 16, 5, tzinfo=OSLO)
    s = summarize(_points(now), now)
    assert s["day_label"] == "I morgen"
    assert len(s["periods"]) == 3


def test_summary_skips_passed_hours():
    now = datetime(2026, 11, 2, 10, 0, tzinfo=OSLO)
    s = summarize(_points(now), now)
    assert [p["label"] for p in s["periods"]] == ["kl. 12", "kl. 16"]


def test_summary_empty():
    assert summarize([], datetime(2026, 11, 2, 6, tzinfo=OSLO)) is None


# ---------------------------------------------------------------- henting og hurtigbuffer

class FakeResponse:
    def __init__(self, status, data=None, headers=None):
        self.status_code, self._data, self.headers = status, data, headers or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"params": params, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


NOW = datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)
SAMPLE = demo_forecast(NOW)
EXPIRES_SOON = "Mon, 02 Nov 2026 05:30:00 GMT"


def test_fetch_uses_cache_until_expires(tmp_path):
    cache = tmp_path / "cache.json"
    s = FakeSession([FakeResponse(200, SAMPLE, {"Expires": EXPIRES_SOON, "Last-Modified": "x"})])
    assert fetch_forecast(59.91234567, 10.75, UA, cache, now=NOW, session=s) == SAMPLE
    assert s.calls[0]["params"] == {"lat": 59.9123, "lon": 10.75}       # maks 4 desimaler
    assert s.calls[0]["headers"]["User-Agent"] == UA
    # Andre kall før Expires: ingen ny forespørsel
    assert fetch_forecast(59.91234567, 10.75, UA, cache, now=NOW + timedelta(minutes=10), session=s) == SAMPLE
    assert len(s.calls) == 1


def test_fetch_sends_if_modified_since_and_handles_304(tmp_path):
    cache = tmp_path / "cache.json"
    later = NOW + timedelta(hours=1)
    s = FakeSession([FakeResponse(200, SAMPLE, {"Expires": EXPIRES_SOON, "Last-Modified": "LM"}),
                     FakeResponse(304, None, {"Expires": "Mon, 02 Nov 2026 07:00:00 GMT"})])
    fetch_forecast(59.9, 10.7, UA, cache, now=NOW, session=s)
    assert fetch_forecast(59.9, 10.7, UA, cache, now=later, session=s) == SAMPLE
    assert s.calls[1]["headers"]["If-Modified-Since"] == "LM"


def test_fetch_falls_back_to_cache_on_network_error(tmp_path):
    cache = tmp_path / "cache.json"
    s = FakeSession([FakeResponse(200, SAMPLE, {"Expires": EXPIRES_SOON}),
                     requests.ConnectionError("ingen nett")])
    fetch_forecast(59.9, 10.7, UA, cache, now=NOW, session=s)
    assert fetch_forecast(59.9, 10.7, UA, cache, now=NOW + timedelta(hours=2), session=s) == SAMPLE


def test_fetch_without_cache_raises(tmp_path):
    s = FakeSession([FakeResponse(403)])
    with pytest.raises(WeatherError, match="403"):
        fetch_forecast(59.9, 10.7, UA, tmp_path / "cache.json", now=NOW, session=s)


def test_fetch_refuses_example_user_agent(tmp_path):
    with pytest.raises(WeatherError, match="user_agent"):
        fetch_forecast(59.9, 10.7, "familiehub/0.1 din.epost@eksempel.no", tmp_path / "c.json")


def test_summary_evening_from_keeps_today_until_evening():
    points = parse_points(demo_forecast(datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)), OSLO)
    ettermiddag = summarize(points, datetime(2026, 11, 2, 16, 5, tzinfo=OSLO), evening_from=18)
    kveld = summarize(points, datetime(2026, 11, 2, 18, 0, tzinfo=OSLO), evening_from=18)
    assert ettermiddag["day_label"] == "I dag" and kveld["day_label"] == "I morgen"


def test_afternoon_outdoor_covers_rest_of_today():
    """Kl. 15–18: skoletiden er over, så «Ute» og klesrådet gjelder fra nå til kveld (06 #46)."""
    now = datetime(2026, 11, 2, 16, 10, tzinfo=OSLO)
    points = parse_points(demo_forecast(now.astimezone(timezone.utc)), OSLO)   # som Yr: bare fra nå og framover
    s = summarize(points, now, evening_from=18)
    assert s["day_label"] == "I dag"
    assert s["outdoor"] is not None and s["outdoor"]["label"] == "I dag kl. 16–18"
    sent = summarize(points, datetime(2026, 11, 2, 17, 50, tzinfo=OSLO), evening_from=18)
    assert sent["outdoor"]["label"] == "I dag kl. 17–19"
    kl7 = datetime(2026, 11, 2, 7, 0, tzinfo=OSLO)
    morgen = summarize(parse_points(demo_forecast(kl7.astimezone(timezone.utc)), OSLO), kl7, evening_from=18)
    assert morgen["outdoor"]["label"] == "I dag kl. 08–15"
