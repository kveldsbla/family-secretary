"""Tester for sol opp/ned (I-12): henting, hurtigbuffer, tolking og linjen på bildet. Ingen nett."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import requests

from render.render import build_html
from sources.sun import SunError, _offset, demo_sun, fetch_sun, parse_sun, sun_line

OSLO = ZoneInfo("Europe/Oslo")
UA = "familiehub-test/0.1 test@test.no"
DAY = date(2026, 11, 4)


def met(up, down, visible=True):
    """Et svar i samme form som MET Sunrise 3.0 (sett 4. nov 2026)."""
    return {"type": "Feature", "properties": {
        "body": "Sun",
        "sunrise": {"time": up, "azimuth": 120.0 if up else None},
        "sunset": {"time": down, "azimuth": 240.0 if down else None},
        "solarnoon": {"time": "2026-11-04T12:01+01:00", "disc_centre_elevation": 14.7, "visible": visible},
    }}


TODAY = met("2026-11-04T07:47+01:00", "2026-11-04T16:15+01:00")
BEFORE = met("2026-11-03T07:44+01:00", "2026-11-03T16:17+01:00")


class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.headers = status, data, {}

    def json(self):
        if self._data is None:
            raise ValueError("ingen JSON")
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# ---------------------------------------------------------------- henting og hurtigbuffer

def test_fetch_once_per_date(tmp_path):
    cache = tmp_path / "sun_cache.json"
    s = FakeSession([FakeResponse(200, TODAY)])
    props = fetch_sun(59.91391234, 10.7522, DAY, OSLO, UA, cache, session=s)
    assert props["sunrise"]["time"] == "2026-11-04T07:47+01:00"
    call = s.calls[0]
    assert call["url"].endswith("/sunrise/3.0/sun")
    assert call["params"] == {"lat": 59.9139, "lon": 10.7522, "date": "2026-11-04", "offset": "+01:00"}
    assert call["headers"]["User-Agent"] == UA
    # Samme dato igjen: fra hurtigbufferen, uten nettkall (og uten nett)
    s2 = FakeSession([requests.ConnectionError("nede")])
    assert fetch_sun(59.9139, 10.7522, DAY, OSLO, UA, cache, session=s2) == props
    assert s2.calls == []


def test_new_place_fetches_again(tmp_path):
    cache = tmp_path / "sun_cache.json"
    fetch_sun(59.91, 10.75, DAY, OSLO, UA, cache, session=FakeSession([FakeResponse(200, TODAY)]))
    s = FakeSession([FakeResponse(200, TODAY)])
    fetch_sun(60.0, 10.75, DAY, OSLO, UA, cache, session=s)
    assert len(s.calls) == 1


def test_cache_keeps_only_recent_days(tmp_path):
    cache = tmp_path / "sun_cache.json"
    for d in range(1, 16):
        fetch_sun(59.91, 10.75, date(2026, 11, d), OSLO, UA, cache, session=FakeSession([FakeResponse(200, TODAY)]))
    import json
    days = json.loads(cache.read_text(encoding="utf-8"))["dager"]
    assert len(days) == 10 and "2026-11-15" in days and "2026-11-01" not in days


def test_summer_offset():
    assert _offset(date(2026, 6, 21), OSLO) == "+02:00"
    assert _offset(date(2026, 12, 21), OSLO) == "+01:00"


@pytest.mark.parametrize("response, text", [
    (requests.ConnectionError("nede"), "nettverksfeil"),
    (FakeResponse(403), "User-Agent"),
    (FakeResponse(500), "HTTP 500"),
    (FakeResponse(200, None), "uten soltider"),
    (FakeResponse(200, {"properties": {}}), "uten soltider"),
])
def test_fetch_errors_without_cache(tmp_path, response, text):
    with pytest.raises(SunError, match=text):
        fetch_sun(59.91, 10.75, DAY, OSLO, UA, tmp_path / "c.json", session=FakeSession([response]))
    assert not (tmp_path / "c.json").exists()     # et feilsvar lagres aldri


def test_example_user_agent_refused(tmp_path):
    with pytest.raises(SunError, match="user_agent"):
        fetch_sun(59.91, 10.75, DAY, OSLO, "familiehub/0.1 din.epost@eksempel.no", tmp_path / "c.json",
                  session=FakeSession([]))


# ---------------------------------------------------------------- tolking

def test_parse_normal_day():
    s = parse_sun(TODAY["properties"], OSLO)
    assert (s["opp"].hour, s["opp"].minute, s["ned"].hour, s["ned"].minute) == (7, 47, 16, 15)
    assert s["minutter"] == 8 * 60 + 28 and s["polar"] is None


def test_parse_polar_day_and_night():
    assert parse_sun(met(None, None, True)["properties"], OSLO)["polar"] == "midnattssol"
    assert parse_sun(met(None, None, False)["properties"], OSLO)["polar"] == "mørketid"


def test_parse_only_sunrise_is_refused():
    with pytest.raises(ValueError):
        parse_sun(met("2026-11-04T07:47+01:00", None)["properties"], OSLO)


# ---------------------------------------------------------------- linjen

def _line(today, before, show="alltid"):
    return sun_line(parse_sun(today["properties"], OSLO),
                    parse_sun(before["properties"], OSLO) if before else None, show)


def test_line_shorter_days():
    assert _line(TODAY, BEFORE) == {"opp": "07:47", "ned": "16:15", "lengde": "8 t 28 min", "endring": "−5 min"}
    assert _line(TODAY, BEFORE, "lengre")["endring"] is None      # bare når dagene blir lengre
    assert _line(TODAY, BEFORE, "aldri")["endring"] is None


def test_line_longer_days_and_no_yesterday():
    assert _line(BEFORE, TODAY, "lengre")["endring"] == "+5 min"
    assert _line(TODAY, None)["endring"] is None
    assert _line(TODAY, TODAY)["endring"] == "±0 min"


def test_line_polar():
    assert _line(met(None, None, True), TODAY) == {"polar": "Midnattssol"}


def test_demo_sun_gives_plus_three():
    line = sun_line(parse_sun(demo_sun(DAY, OSLO), OSLO), parse_sun(demo_sun(DAY, OSLO, day_before=True), OSLO))
    assert line == {"opp": "08:58", "ned": "15:42", "lengde": "6 t 44 min", "endring": "+3 min"}


# ---------------------------------------------------------------- main og malen

def _main_cfg(**sol):
    return {"sted": {"lat": 59.91, "lon": 10.75}, "yr": {"user_agent": UA}, "sol": sol}


def test_get_sun_evening_uses_tomorrow(monkeypatch):
    import main
    asked = []
    monkeypatch.setattr(main, "fetch_sun", lambda lat, lon, d, *a, **k: asked.append(d) or
                        (TODAY if d == date(2026, 11, 5) else BEFORE)["properties"])
    line = main.get_sun(_main_cfg(), OSLO, datetime(2026, 11, 4, 19, 30, tzinfo=OSLO), None)
    assert asked == [date(2026, 11, 5), date(2026, 11, 4)]
    assert line["dag"] == "I morgen" and line["endring"] == "−5 min"


def test_get_sun_failure_gives_no_line(monkeypatch):
    import main
    def fail(*a, **k):
        raise SunError("nettverksfeil")
    monkeypatch.setattr(main, "fetch_sun", fail)
    assert main.get_sun(_main_cfg(), OSLO, datetime(2026, 11, 4, 12, 0, tzinfo=OSLO), None) is None


def test_get_sun_without_yesterday_still_shows(monkeypatch):
    import main
    def fetch(lat, lon, d, *a, **k):
        if d == DAY:
            return TODAY["properties"]
        raise SunError("nettverksfeil")
    monkeypatch.setattr(main, "fetch_sun", fetch)
    line = main.get_sun(_main_cfg(), OSLO, datetime(2026, 11, 4, 12, 0, tzinfo=OSLO), None)
    assert line["opp"] == "07:47" and line["endring"] is None


def test_get_sun_can_be_turned_off():
    import main
    assert main.get_sun(_main_cfg(vis=False), OSLO, datetime(2026, 11, 4, 12, 0, tzinfo=OSLO), "vinter") is None


def test_sun_line_in_html_and_credit():
    from tests.test_render import _context
    ctx = {**_context(), "sol": {"opp": "07:47", "ned": "16:15", "lengde": "8 t 28 min", "endring": "−5 min",
                                 "dag": "I dag"}}
    html = build_html("morning.html", ctx)
    header = html.split("<header>")[1].split("</header>")[0]
    assert 'class="sol"' in header                                   # i datolinjen
    assert "07:47–16:15" in header and "8 t 28 min" in header and "−5 min" in header
    assert "🌅" not in html                                         # uten emoji
    assert "Vær- og soldata: MET Norway" in html
    evening = build_html("morning.html", {**ctx, "sol": {**ctx["sol"], "dag": "I morgen"}})
    assert "Sol i morgen" in evening
    without = build_html("morning.html", _context())
    assert 'class="sol"' not in without and "Værdata: MET Norway" in without
