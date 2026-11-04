"""Tester for dagens plan: merker i tittelen, personer, tidsrom og «+N til».

Bruker oppdiktede personer og hendelser – ingen ekte navn eller kalenderdata.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from logic.day_plan import DEFAULT_COLOR, build_day, demo_events, load_persons, split_tag, summary_line
from sources.calendar import Event

OSLO = ZoneInfo("Europe/Oslo")
DAY = date(2026, 11, 4)
PERSONER = load_persons([
    {"navn": "Voksen 1", "merke": "A", "farge": "#9b6a4a"},
    {"navn": "Voksen 2", "merke": "B", "farge": "#4a6a9b"},
    {"navn": "Barn 8", "merke": "D", "farge": "#b0805a"},
    {"navn": "Barn 4", "merke": "F", "farge": "#8a5a9b"},
])


def at(h, mi=0, day=DAY):
    return datetime.combine(day, time(h, mi), OSLO)


def ev(title, start, end=None, all_day=False):
    if all_day:
        return Event(start, end or start + timedelta(days=1), True, title)
    return Event(start, end or start + timedelta(hours=1), False, title)


# ---------------------------------------------------------------- merker (initial først, uten klammer)

def test_one_person():
    who, title = split_tag("F Turdag – matpakke", PERSONER)
    assert [p.navn for p in who] == ["Barn 4"] and title == "Turdag – matpakke"


def test_several_people_in_config_order_and_separators():
    for lead in ("D A", "D & A", "D&A", "D og A", "D, A", "D/A", "D + A"):
        who, title = split_tag(f"{lead} Foreldremøte", PERSONER)
        assert [p.merke for p in who] == ["A", "D"], lead          # rekkefølgen fra config
        assert title == "Foreldremøte", lead


def test_colon_after_initial():
    who, title = split_tag("F: Turdag", PERSONER)
    assert [p.merke for p in who] == ["F"] and title == "Turdag"


def test_no_mark_is_shared():
    assert split_tag("Middag hos besteforeldre", PERSONER) == ([], "Middag hos besteforeldre")


def test_initial_must_stand_alone():
    """Ord som bare begynner med samme bokstav som et merke, er ikke merker."""
    for title in ("Fotball", "Felles middag", "F-lag kamp", "Dans", "A4-ark"):
        assert split_tag(title, PERSONER) == ([], title), title


def test_lowercase_and_unknown_letters_are_not_marks():
    assert split_tag("f turdag", PERSONER) == ([], "f turdag")
    assert split_tag("X Fotball", PERSONER) == ([], "X Fotball")
    assert split_tag("I morgen: bake", PERSONER) == ([], "I morgen: bake")


def test_mark_only_in_start_of_title():
    assert split_tag("Fotball A", PERSONER) == ([], "Fotball A")


def test_og_after_single_mark_belongs_to_title():
    who, title = split_tag("A og venner på kino", PERSONER)
    assert [p.merke for p in who] == ["A"] and title == "og venner på kino"


def test_mark_without_title():
    who, title = split_tag("A", PERSONER)
    assert [p.merke for p in who] == ["A"] and title == "(uten tittel)"


def test_no_persons_in_config():
    assert split_tag("A Fotball", []) == ([], "A Fotball")


# ---------------------------------------------------------------- personer i config

def test_persons_validation():
    with pytest.raises(ValueError, match="to personer"):
        load_persons([{"navn": "X", "merke": "a", "farge": "#fff"}, {"navn": "Y", "merke": "A", "farge": "#000"}])
    with pytest.raises(ValueError, match="mangler"):
        load_persons([{"navn": "X", "farge": "#fff"}])
    for bad in ("A B", "A&", "A:"):
        with pytest.raises(ValueError, match="mellomrom"):
            load_persons([{"navn": "X", "merke": bad, "farge": "#fff"}])
    assert load_persons(None) == []


def test_bad_colour_becomes_grey():
    """Fargen havner i HTML-en, så bare ekte hex-farger slippes gjennom."""
    p = load_persons([{"navn": "X", "merke": "X", "farge": "red; background:url(x)"}])
    assert p[0].farge == DEFAULT_COLOR


# ---------------------------------------------------------------- dagens plan

def test_order_all_day_first_then_time():
    plan = build_day([
        ev("D Korps", at(17, 30)),
        ev("Tannlege", at(8)),
        ev("F Turdag", DAY, all_day=True),
    ], DAY, PERSONER)
    assert [h["tittel"] for h in plan["hendelser"]] == ["Turdag", "Tannlege", "Korps"]
    assert [h["tid"] for h in plan["hendelser"]] == ["Hele dagen", "08:00", "17:30"]
    assert plan["flere"] == 0


def test_people_colours_and_names():
    plan = build_day([ev("A D Foreldremøte", at(19)), ev("Felles middag", at(17))], DAY, PERSONER)
    felles, mote = plan["hendelser"]
    assert felles["felles"] and felles["personer"] == [] and felles["navn"] == ""
    assert not mote["felles"] and mote["navn"] == "Voksen 1 og Barn 8"
    assert [p["farge"] for p in mote["personer"]] == ["#9b6a4a", "#b0805a"]


def test_afternoon_flag():
    plan = build_day([ev("Morgen", at(13, 59)), ev("Ettermiddag", at(14)),
                      ev("Heldag", DAY, all_day=True)], DAY, PERSONER)
    flags = {h["tittel"]: h["ettermiddag"] for h in plan["hendelser"]}
    assert flags == {"Heldag": False, "Morgen": False, "Ettermiddag": True}


def test_other_days_are_left_out():
    plan = build_day([ev("I går", at(10, day=DAY - timedelta(days=1))), ev("I dag", at(10))], DAY, PERSONER)
    assert [h["tittel"] for h in plan["hendelser"]] == ["I dag"]


def test_event_from_yesterday_and_multi_day():
    plan = build_day([
        ev("Nattevakt", at(22, day=DAY - timedelta(days=1)), at(7)),               # slutter i dag
        ev("Seminar", at(9, day=DAY - timedelta(days=1)), at(16, day=DAY + timedelta(days=1))),
        ev("Høstferie", DAY - timedelta(days=2), DAY + timedelta(days=3), all_day=True),
    ], DAY, PERSONER)
    tider = {h["tittel"]: h["tid"] for h in plan["hendelser"]}
    assert tider == {"Høstferie": "Hele dagen", "Seminar": "Hele dagen", "Nattevakt": "til 07:00"}


def test_too_many_events():
    events = [ev(f"Hendelse {i}", at(8 + i)) for i in range(9)]
    plan = build_day(events, DAY, PERSONER, max_items=6)
    assert len(plan["hendelser"]) == 5 and plan["flere"] == 4              # 5 + «+4 til» = 6 linjer
    assert build_day(events[:6], DAY, PERSONER, max_items=6)["flere"] == 0  # akkurat 6 får plass


def test_empty_day():
    assert build_day([], DAY, PERSONER) == {"hendelser": [], "flere": 0, "passert": 0}


# ---------------------------------------------------------------- passerte hendelser

def test_passed_events_are_removed():
    events = [ev("Tannlege", at(8), at(9)), ev("Lunsj", at(11, 30), at(12, 30)),
              ev("Korps", at(17, 30), at(18, 30)), ev("F Turdag", DAY, all_day=True)]
    plan = build_day(events, DAY, PERSONER, now=at(12))
    assert [h["tittel"] for h in plan["hendelser"]] == ["Turdag", "Lunsj", "Korps"]   # pågår + heldag blir
    assert plan["passert"] == 1


def test_event_ending_exactly_now_is_gone():
    plan = build_day([ev("Møte", at(9), at(10))], DAY, PERSONER, now=at(10))
    assert plan["hendelser"] == [] and plan["passert"] == 1


def test_event_without_duration():
    events = [ev("Påminnelse", at(9), at(9)), ev("Senere", at(15), at(15))]
    plan = build_day(events, DAY, PERSONER, now=at(12))
    assert [h["tittel"] for h in plan["hendelser"]] == ["Senere"]


def test_night_event_from_yesterday_passed():
    plan = build_day([ev("Nattevakt", at(22, day=DAY - timedelta(days=1)), at(7))], DAY, PERSONER, now=at(8))
    assert plan["hendelser"] == [] and plan["passert"] == 1


def test_tomorrow_is_not_filtered():
    tomorrow = DAY + timedelta(days=1)
    plan = build_day([ev("Tidlig", at(7, day=tomorrow))], tomorrow, PERSONER, now=at(16))
    assert len(plan["hendelser"]) == 1 and plan["passert"] == 0


def test_passed_events_do_not_count_in_more():
    events = [ev(f"Ferdig {i}", at(6 + i, 0), at(6 + i, 30)) for i in range(4)] + \
             [ev(f"Senere {i}", at(13 + i)) for i in range(6)]
    plan = build_day(events, DAY, PERSONER, max_items=6, now=at(12))
    assert plan["passert"] == 4 and plan["flere"] == 0 and len(plan["hendelser"]) == 6
    assert summary_line(plan) == "6 hendelser (6 felles), 4 passert"


def test_summary_line_has_no_titles():
    plan = build_day([ev("A Hemmelig avtale", at(9)), ev("Felles", at(10))], DAY, PERSONER)
    line = summary_line(plan)
    assert line == "2 hendelser (1 felles)" and "Hemmelig" not in line


def test_demo_events_use_marks_from_config():
    plan = build_day(demo_events(DAY, PERSONER, OSLO), DAY, PERSONER)
    assert len(plan["hendelser"]) == 6 and plan["flere"] == 0
    assert any(h["felles"] for h in plan["hendelser"])
    assert sum(1 for h in plan["hendelser"] if not h["felles"]) == 5          # merkene er tolket og fjernet


# ---------------------------------------------------------------- på bildet

def _html(plan):
    from render.render import build_html
    return build_html("morning.html", {
        "dato": {"ukedag": "Onsdag", "dato": "4. november", "uke": 45, "aar": 2026},
        "vaer": None, "klar": None, "plan": plan, "oppdatert": "06:00", "demo": True})


def test_html_shows_today_with_people():
    plan = build_day([ev("A D Foreldremøte", at(19)), ev("F Turdag", DAY, all_day=True),
                      ev("Felles middag", at(17))], DAY, PERSONER)
    plan["tittel"] = "I dag"
    html = _html(plan)
    assert 'class="idag"' in html and "flate med-kalender" in html
    assert "Foreldremøte" in html and "Voksen 1 og Barn 8" in html and "Hele dagen" in html
    assert "background: #9b6a4a" in html


def test_html_escapes_event_titles():
    plan = build_day([ev("A <script>alert(1)</script>", at(9))], DAY, PERSONER)
    plan["tittel"] = "I dag"
    html = _html(plan)
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_html_more_empty_error_and_none():
    plan = build_day([ev(f"Hendelse {i}", at(8 + i)) for i in range(8)], DAY, PERSONER)
    plan["tittel"] = "I dag"
    assert "+3 til i kalenderen" in _html(plan)
    assert "Ingenting i kalenderen" in _html({"tittel": "I dag", "hendelser": [], "flere": 0})
    assert "Ingenting mer i kalenderen" in _html({"tittel": "I dag", "hendelser": [], "flere": 0, "passert": 2})
    error = _html({"tittel": "I dag", "feil": True, "hendelser": [], "flere": 0})
    assert "Kalenderen er ikke tilgjengelig" in error and "flate med-kalender" not in error
    assert 'class="idag"' not in _html(None)                       # ingen kalender satt opp: feltet skjules


# ---------------------------------------------------------------- main.get_plan (uten nett)

CFG = {"personer": [{"navn": "Barn 4", "merke": "F", "farge": "#8a5a9b"}]}


def test_get_plan_demo_follows_weather_day():
    import main
    morgen = main.get_plan(CFG, OSLO, at(6), demo="vinter")
    ettermiddag = main.get_plan(CFG, OSLO, at(16), demo="vinter")  # før kl. 18: fortsatt i dag (06 #41)
    kveld = main.get_plan(CFG, OSLO, at(19), demo="vinter")        # fra kl. 18: i morgen, som været
    assert morgen["tittel"] == "I dag" and ettermiddag["tittel"] == "I dag" and kveld["tittel"] == "I morgen"
    assert morgen["hendelser"] and not morgen.get("feil") and "kveld" not in morgen
    kveld_i_dag = main.get_plan({**CFG, "dagen": {"kveld_fra": 23}}, OSLO, at(22), demo="vinter")
    assert kveld_i_dag["tittel"] == "I dag" and kveld_i_dag["passert"] > 0   # det som er ferdig, er borte


def test_get_plan_without_link_hides_field(monkeypatch):
    import main
    monkeypatch.setattr(main, "read_env", lambda path: {})
    monkeypatch.delenv("FAMILIEKALENDER_ICS", raising=False)
    assert main.get_plan(CFG, OSLO, at(6), demo=None) is None


def test_get_plan_error_shows_dash_and_hides_link(monkeypatch, caplog):
    import main
    from sources.calendar import CalendarError

    def fail(url, cache_file, **kwargs):
        raise CalendarError("Kunne ikke hente kalenderen (nettverksfeil)")

    monkeypatch.setattr(main, "read_env", lambda path: {"FAMILIEKALENDER_ICS": "https://hemmelig.example/lenke"})
    monkeypatch.setattr(main, "fetch_ics", fail)
    plan = main.get_plan(CFG, OSLO, at(6), demo=None)
    assert plan["feil"] and plan["tittel"] == "I dag"
    assert "hemmelig" not in caplog.text


def test_get_plan_bad_persons_config():
    import main
    plan = main.get_plan({"personer": [{"navn": "X"}]}, OSLO, at(6), demo="vinter")
    assert plan["feil"]


def test_get_plan_evening_has_tonight_and_tomorrow():
    import main
    plan = main.get_plan(CFG, OSLO, at(19, 30), demo="vinter")
    assert plan["tittel"] == "I morgen" and plan["hendelser"]
    kveld = plan["kveld"]
    assert kveld["tittel"] == "I kveld" and kveld["passert"] > 0
    assert [h["tid"] for h in kveld["hendelser"]] == ["19:00", "20:30"]   # pågår + resten; heldag ikke om kvelden
    tidlig = main.get_plan({**CFG, "dagen": {"kveld_fra": 17}}, OSLO, at(17, 5), demo="vinter")
    assert tidlig["tittel"] == "I morgen"                                             # kveld_fra fra config


def test_parse_time_names_and_clock():
    import main
    now = at(6)
    assert main.parse_time("kveld", now).strftime("%H:%M") == "19:30"
    assert main.parse_time("07:15", now) == at(7, 15) and main.parse_time("7.15", now) == at(7, 15)
    import pytest
    for bad in ("25:00", "nå", "7"):
        with pytest.raises(ValueError):
            main.parse_time(bad, now)


def test_html_evening_shows_tonight_above_tomorrow_and_hides_photo():
    morgen = build_day([ev("A Fotball", at(17))], DAY, PERSONER)
    morgen["tittel"] = "I morgen"
    kveld = build_day([ev("D Korps", at(19))], DAY, PERSONER)
    kveld["tittel"] = "I kveld"
    morgen["kveld"] = kveld
    from render.render import build_html
    ctx = {"dato": {"ukedag": "Onsdag", "dato": "4. november", "uke": 45, "aar": 2026}, "vaer": None,
           "klar": None, "plan": morgen, "oppdatert": "19:30", "demo": True,
           "foto": {"src": "file:///x.jpg", "tekst": "", "fil": "x.jpg"}}
    kveld_h2, morgen_h2 = '<h2 class="etikett">I kveld</h2>', '<h2 class="etikett">I morgen</h2>'
    html = build_html("morning.html", ctx)
    assert html.index(kveld_h2) < html.index(morgen_h2) and "Korps" in html
    assert 'class="foto"' not in html                                  # kvelden trenger plassen
    morgen["kveld"] = {**kveld, "hendelser": []}                       # ingenting igjen i kveld: foto igjen
    html = build_html("morning.html", ctx)
    assert 'class="foto"' in html and kveld_h2 not in html


# ---------------------------------------------------------------- kveldsfarger (fase 5.2)

def test_farge_kveld_is_read():
    p = load_persons([{"navn": "Liv", "merke": "L", "farge": "#c96f22", "farge_kveld": "#e28030"}])[0]
    assert p.farge == "#c96f22" and p.farge_kveld == "#e28030"


def test_farge_kveld_missing_uses_day_colour():
    p = load_persons([{"navn": "X", "merke": "X", "farge": "#2f6aa8"}])[0]
    assert p.farge_kveld == "#2f6aa8"


def test_farge_kveld_invalid_is_grey():
    from logic.day_plan import DEFAULT_COLOR_KVELD
    p = load_persons([{"navn": "X", "merke": "X", "farge": "#2f6aa8", "farge_kveld": "lyseblå"}])[0]
    assert p.farge_kveld == DEFAULT_COLOR_KVELD
    q = load_persons([{"navn": "Y", "merke": "Y", "farge": "rød"}])[0]     # begge feil → kveldsgrå
    assert q.farge == DEFAULT_COLOR and q.farge_kveld == DEFAULT_COLOR_KVELD


def test_build_day_gives_evening_colour():
    persons = load_persons([{"navn": "Liv", "merke": "L", "farge": "#c96f22", "farge_kveld": "#e28030"}])
    tz = ZoneInfo("Europe/Oslo")
    day = date(2026, 11, 4)
    e = Event(datetime(2026, 11, 4, 17, 30, tzinfo=tz), datetime(2026, 11, 4, 18, 30, tzinfo=tz), False, "L Korps")
    plan = build_day([e], day, persons)
    assert plan["hendelser"][0]["personer"] == [{"navn": "Liv", "farge": "#c96f22", "farge_kveld": "#e28030"}]
