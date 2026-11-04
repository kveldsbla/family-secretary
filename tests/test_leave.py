"""Tester for «Nå må du dra!» (fase 5.1): skoledag, tidsrom, skolerute og barnas avtaler."""
from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import main
from logic.day_plan import load_persons
from logic.leave import (SchoolCalendar, free_reason, kids_events, leave_check,
                         load_school_calendar, parse_clock, settings)
from render.render import build_html
from sources.calendar import Event

TZ = ZoneInfo("Europe/Oslo")
ROOT = Path(__file__).resolve().parent.parent
PERSONS = load_persons([
    {"navn": "Eva", "merke": "E", "farge": "#6d5a4a"},
    {"navn": "Jens", "merke": "J", "farge": "#1e8a6e", "barn": True},
    {"navn": "Liv", "merke": "L", "farge": "#d0782a", "barn": True},
])


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), TZ)


TUESDAY = date(2026, 11, 3)
S = settings(None)


# ---------------------------------------------------------------- innstillinger

def test_standardverdier():
    assert S["fra_tid"] == time(8, 0) and S["til_tid"] == time(8, 10)
    assert S["ha_med"] == ["Sekk", "Matpakke", "Drikkeflaske"]
    assert S["tittel"] == "Nå må du dra!"


def test_config_overstyrer_bare_det_som_står():
    s = settings({"til": "08:15", "ha_med": ["Sekk", " ", "Gymtøy"]})
    assert s["til_tid"] == time(8, 15) and s["fra_tid"] == time(8, 0)
    assert s["ha_med"] == ["Sekk", "Gymtøy"]           # tomme linjer fjernes


def test_klokkeslett_uten_fnutter_fra_yaml():
    assert parse_clock(490) == time(8, 10)              # YAML leser 8:10 som 490 minutter
    with pytest.raises(ValueError):
        parse_clock("8 o'clock")


def test_til_maa_vaere_etter_fra():
    with pytest.raises(ValueError):
        settings({"fra": "08:10", "til": "08:00"})


# ---------------------------------------------------------------- skoledag og tidsrom

def test_vises_kl_0800_til_0809_paa_skoledag():
    assert leave_check(at(TUESDAY, 8, 0), S, SchoolCalendar())[0]
    assert leave_check(at(TUESDAY, 8, 9), S, SchoolCalendar())[0]


def test_vises_ikke_foer_og_etter():
    assert not leave_check(at(TUESDAY, 7, 59), S, SchoolCalendar())[0]
    show, why = leave_check(at(TUESDAY, 8, 10), S, SchoolCalendar())
    assert not show and why == "utenfor tidsrommet"     # kl. 08:10: tilbake til dagbildet


def test_ikke_i_helgen():
    show, why = leave_check(at(date(2026, 11, 7), 8, 0), S, SchoolCalendar())
    assert not show and "Helg" in why


def test_ikke_i_ferien():
    cal = SchoolCalendar(fridager=[(date(2027, 2, 22), date(2027, 2, 26), "Vinterferie")])
    show, why = leave_check(at(date(2027, 2, 24), 8, 0), S, cal)
    assert not show and "Vinterferie" in why
    assert leave_check(at(date(2027, 3, 1), 8, 0), S, cal)[0]


def test_kan_skrus_av():
    assert not leave_check(at(TUESDAY, 8, 0), settings({"vis": False}), SchoolCalendar())[0]


def test_skolerute_utdatert_gir_advarsel(caplog):
    cal = SchoolCalendar(gjelder_til=date(2026, 8, 1))
    assert leave_check(at(TUESDAY, 8, 0), S, cal)[0]   # regnes som skoledag …
    assert "skolerute.yaml" in caplog.text               # … men loggen sier fra


# ---------------------------------------------------------------- skolerute.yaml

def test_skolerute_i_prosjektet_kan_leses():
    cal = load_school_calendar(ROOT / "skolerute.yaml")
    assert cal and cal.gjelder_til == date(2028, 8, 20)
    assert free_reason(date(2026, 9, 30), cal) == "Høstferie"
    assert free_reason(date(2026, 12, 21), cal) == "Juleferie"
    assert free_reason(date(2027, 1, 4), cal) == "Juleferie"     # planleggingsdag
    assert free_reason(date(2027, 1, 5), cal) is None            # første skoledag
    assert free_reason(date(2027, 5, 17), cal) == "17. mai"
    assert free_reason(date(2027, 7, 1), cal) == "Sommerferie"
    assert free_reason(date(2027, 8, 16), cal) is None
    assert free_reason(TUESDAY, cal) is None


def test_skolerute_mangler(tmp_path):
    assert load_school_calendar(tmp_path / "finnes-ikke.yaml") is None


def test_skolerute_med_feil(tmp_path):
    f = tmp_path / "skolerute.yaml"
    f.write_text("fridager:\n  - { navn: Feil, fra: 2027-02-26, til: 2027-02-22 }\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_school_calendar(f)


# ---------------------------------------------------------------- barnas avtaler

def test_barn_leses_fra_config():
    assert [p.barn for p in PERSONS] == [False, True, True]


def test_bare_barnas_hendelser_og_felles_heldag():
    d = TUESDAY
    events = [
        Event(at(d, 8, 30), at(d, 9), False, "J Prøve i matte"),
        Event(at(d, 9), at(d, 10), False, "E Tannlege"),
        Event(at(d, 17), at(d, 18), False, "E & L Foreldremøte"),
        Event(d, date(2026, 11, 4), True, "Fotografering"),
        Event(at(d, 19), at(d, 20), False, "Taco-kveld"),
    ]
    titles = [e.title for e in kids_events(events, PERSONS)]
    assert titles == ["J Prøve i matte", "E & L Foreldremøte", "Fotografering"]


def test_uten_barn_i_config_vises_alt():
    persons = load_persons([{"navn": "A", "merke": "A", "farge": "#000000"}])
    events = [Event(at(TUESDAY, 9), at(TUESDAY, 10), False, "A Tannlege")]
    assert kids_events(events, persons) == events


# ---------------------------------------------------------------- hele flyten

def test_demo_kl_0800_lager_dra_bildet(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "OUTPUT", tmp_path)
    assert main.main(["--demo", "vinter", "--tid", "dra", "--html-only", "--config", "config.example.yaml"]) == 0
    html = (tmp_path / "siste.html").read_text(encoding="utf-8")
    assert "Nå må du dra!" in html and "I dag for barna" in html and "Ha med" in html
    assert "Foreldremøte" not in html          # voksenavtale (demo: merke 0 og 1)
    assert 'class="foto"' not in html


def test_demo_kl_0810_lager_vanlig_dagbilde(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "OUTPUT", tmp_path)
    assert main.main(["--demo", "vinter", "--tid", "08:10", "--html-only", "--config", "config.example.yaml"]) == 0
    html = (tmp_path / "siste.html").read_text(encoding="utf-8")
    assert "Nå må du dra!" not in html


def test_mal_uten_vaer_og_kalender():
    ctx = {"dato": {"ukedag": "Tirsdag", "dato": "3. november", "uke": 45}, "dra": S,
           "vaer": None, "ute": None, "klar": None, "plan": None, "oppdatert": "08:00",
           "demo": False, "tid_satt": False}
    html = build_html("dra.html", ctx)
    assert "Været er ikke tilgjengelig" in html and "Drikkeflaske" in html
