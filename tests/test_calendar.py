"""Tester for kalenderen: tolking, gjentakelser, reservekopi og at lenken aldri lekker.

Bruker oppdiktede kalendere – ingen nett og ingen ekte data.
"""
import logging
from datetime import date
from zoneinfo import ZoneInfo

import pytest
import requests

from sources.calendar import CalendarError, events_between, fetch_ics, normalise_url
from sources.envfile import read_env

OSLO = ZoneInfo("Europe/Oslo")
SECRET = "https://p99-caldav.icloud.com/published/2/HEMMELIG-TEST-LENKE"

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//familiehub test//NO
BEGIN:VEVENT
UID:fotball-1
DTSTAMP:20261101T000000Z
DTSTART;TZID=Europe/Oslo:20261103T173000
DTEND;TZID=Europe/Oslo:20261103T183000
RRULE:FREQ=WEEKLY;BYDAY=TU
EXDATE;TZID=Europe/Oslo:20261110T173000
SUMMARY:[M] Fotball
LOCATION:Kunstgresset
END:VEVENT
BEGIN:VEVENT
UID:turdag-1
DTSTAMP:20261101T000000Z
DTSTART;VALUE=DATE:20261104
DTEND;VALUE=DATE:20261105
SUMMARY:[L] Turdag - matpakke og ekstra votter
END:VEVENT
BEGIN:VEVENT
UID:utc-1
DTSTAMP:20261101T000000Z
DTSTART:20261104T070000Z
DURATION:PT1H
SUMMARY:Tannlege
END:VEVENT
BEGIN:VEVENT
UID:avlyst-1
DTSTAMP:20261101T000000Z
DTSTART;TZID=Europe/Oslo:20261104T120000
DTEND;TZID=Europe/Oslo:20261104T130000
STATUS:CANCELLED
SUMMARY:Avlyst møte
END:VEVENT
BEGIN:VEVENT
UID:ferie-1
DTSTAMP:20261101T000000Z
DTSTART;VALUE=DATE:20261102
DTEND;VALUE=DATE:20261107
SUMMARY:Høstferie bestemor
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").encode("utf-8")


def titles(events):
    return [e.title for e in events]


# ---------------------------------------------------------------- tolking

def test_one_day():
    day = date(2026, 11, 4)
    ev = events_between(ICS, day, day, OSLO)
    # heldag først, så etter klokkeslett; avlyst hendelse er borte
    assert titles(ev) == ["Høstferie bestemor", "[L] Turdag - matpakke og ekstra votter", "Tannlege"]


def test_utc_is_converted_to_norwegian_time():
    day = date(2026, 11, 4)
    tannlege = [e for e in events_between(ICS, day, day, OSLO) if e.title == "Tannlege"][0]
    assert tannlege.start.hour == 8                    # 07:00 UTC = 08:00 norsk vintertid
    assert tannlege.time_text() == "08:00–09:00"       # DURATION i stedet for DTEND


def test_weekly_repeat_with_exception():
    ev = events_between(ICS, date(2026, 11, 2), date(2026, 11, 30), OSLO)
    fotball = [e.start.date() for e in ev if e.title == "[M] Fotball"]
    assert fotball == [date(2026, 11, 3), date(2026, 11, 17), date(2026, 11, 24)]   # 10. nov er strøket
    first = [e for e in ev if e.title == "[M] Fotball"][0]
    assert first.time_text() == "17:30–18:30" and first.location == "Kunstgresset"


def test_all_day_and_multi_day():
    ev = events_between(ICS, date(2026, 11, 6), date(2026, 11, 6), OSLO)
    ferie = [e for e in ev if e.title == "Høstferie bestemor"][0]
    assert ferie.all_day and ferie.time_text() == "Hele dagen"
    assert ferie.on_day(date(2026, 11, 6)) and not ferie.on_day(date(2026, 11, 7))


def test_day_without_events():
    # Mandag: fotballen er på tirsdager og gjentar seg uten sluttdato, så den skal ikke være med
    assert date(2027, 5, 31).weekday() == 0
    assert events_between(ICS, date(2027, 5, 31), date(2027, 5, 31), OSLO) == []
    # …men tirsdagen etter er den der fortsatt
    assert titles(events_between(ICS, date(2027, 6, 1), date(2027, 6, 1), OSLO)) == ["[M] Fotball"]


def test_broken_file():
    with pytest.raises(CalendarError):
        events_between(b"dette er ikke en kalender", date(2026, 11, 4), date(2026, 11, 4), OSLO)


# ---------------------------------------------------------------- henting og reservekopi

class FakeResponse:
    def __init__(self, status, content):
        self.status_code, self.content = status, content


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.urls = response, error, []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.response


def test_webcal_becomes_https():
    assert normalise_url(" webcal://p99-caldav.icloud.com/x ") == "https://p99-caldav.icloud.com/x"
    assert normalise_url("https://a/b") == "https://a/b"


def test_fetch_saves_backup(tmp_path):
    cache = tmp_path / "calendar_cache.ics"
    session = FakeSession(FakeResponse(200, ICS))
    assert fetch_ics(SECRET.replace("https", "webcal", 1), cache, session=session) == ICS
    assert cache.read_bytes() == ICS
    assert session.urls == [SECRET]


@pytest.mark.parametrize("session", [
    FakeSession(error=requests.ConnectionError(f"klarte ikke å nå {SECRET}")),
    FakeSession(FakeResponse(404, b"Not found")),
    FakeSession(FakeResponse(200, b"<html>innlogging</html>")),
])
def test_failure_uses_backup_and_never_leaks_link(tmp_path, caplog, session):
    cache = tmp_path / "calendar_cache.ics"
    cache.write_bytes(ICS)
    with caplog.at_level(logging.DEBUG):
        assert fetch_ics(SECRET, cache, session=session) == ICS
    assert "reservekopi" in caplog.text
    assert "HEMMELIG" not in caplog.text and "icloud" not in caplog.text


def test_failure_without_backup(tmp_path):
    session = FakeSession(error=requests.Timeout(f"tidsavbrudd for {SECRET}"))
    with pytest.raises(CalendarError) as info:
        fetch_ics(SECRET, tmp_path / "calendar_cache.ics", session=session)
    assert "HEMMELIG" not in str(info.value) and "icloud" not in str(info.value)


def test_missing_link(tmp_path):
    with pytest.raises(CalendarError):
        fetch_ics("", tmp_path / "calendar_cache.ics")


# ---------------------------------------------------------------- .env

def test_read_env(tmp_path):
    f = tmp_path / ".env"
    f.write_text('﻿# kommentar\n\nFAMILIEKALENDER_ICS="https://a/b?c=1"\nexport ANNET = verdi \nugyldig linje\n',
                 encoding="utf-8")
    assert read_env(f) == {"FAMILIEKALENDER_ICS": "https://a/b?c=1", "ANNET": "verdi"}
    assert read_env(tmp_path / "mangler.env") == {}
