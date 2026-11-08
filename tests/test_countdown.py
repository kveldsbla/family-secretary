"""Tester for nedtellingen (I-13). Bare oppdiktede datoer, ingen nett."""
from datetime import date

import pytest

from logic.countdown import countdown, holidays, settings
from logic.leave import SchoolCalendar

CAL = SchoolCalendar(
    fridager=[(date(2026, 9, 28), date(2026, 10, 2), "Høstferie"),
              (date(2026, 11, 20), date(2026, 11, 20), "Planleggingsdag"),
              (date(2026, 12, 19), date(2027, 1, 4), "Juleferie")],
    gjelder_til=date(2027, 8, 15))


def test_next_holiday_from_school_calendar():
    c = countdown(date(2026, 11, 4), holidays(CAL, date(2026, 11, 4)))
    assert c["tekst"] == "45 dager til juleferie" and c["emoji"] == "🎄"


def test_single_free_day_is_not_a_holiday():
    names = [t.tekst for t in holidays(CAL, date(2026, 11, 4))]
    assert "planleggingsdag" not in names


def test_own_countdown_closer_than_holiday_wins():
    own, maks = settings([{"dato": date(2026, 11, 10), "tekst": "hyttetur"}])
    c = countdown(date(2026, 11, 4), holidays(CAL, date(2026, 11, 4)) + own, maks)
    assert c["tekst"] == "6 dager til hyttetur" and c["emoji"] == "🎉"


def test_today_and_tomorrow():
    own, _ = settings([{"dato": "2026-12-24", "tekst": "julaften", "emoji": "🎅"}])
    assert countdown(date(2026, 12, 24), own)["tekst"] == "I dag: julaften!"
    assert countdown(date(2026, 12, 23), own)["tekst"] == "I morgen: julaften!"
    assert countdown(date(2026, 12, 25), own) is None          # passert


def test_ongoing_holiday_counts_to_the_next_one():
    assert countdown(date(2026, 12, 27), holidays(CAL, date(2026, 12, 27))) is None


def test_nothing_within_limit():
    assert countdown(date(2026, 10, 5), holidays(CAL, date(2026, 10, 5))) is None    # 75 dager
    own, maks = settings({"maks_dager": 90, "datoer": []})
    assert countdown(date(2026, 10, 5), holidays(CAL, date(2026, 10, 5)) + own, maks)["dager"] == 75


def test_expired_or_missing_school_calendar_gives_no_holidays():
    assert holidays(None, date(2026, 11, 4)) == []
    assert holidays(CAL, date(2027, 8, 16)) == []
    own, _ = settings([{"dato": "2027-08-20", "tekst": "hyttetur"}])   # egne virker likevel
    assert countdown(date(2027, 8, 16), holidays(CAL, date(2027, 8, 16)) + own)["dager"] == 4


def test_no_settings_and_bad_settings():
    assert settings(None) == ([], 60)
    with pytest.raises(ValueError):
        settings([{"dato": "2026-12-24"}])                      # mangler tekst
    with pytest.raises(ValueError):
        settings([{"dato": "24.12.2026", "tekst": "jul"}])       # feil datoformat
