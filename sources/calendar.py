"""Familiekalenderen fra iCloud (offentlig .ics-lenke, 06 #18).

- Lenken er hemmelig: den ligger i .env som FAMILIEKALENDER_ICS og skrives aldri
  til logg, skjerm eller feilmeldinger.
- Gjentakende hendelser (fotball hver tirsdag), unntak og flyttede ganger håndteres
  av biblioteket recurring-ical-events.
- Hvis nettet eller iCloud feiler, brukes siste kopi i data/calendar_cache.ics.

Prøv selv (fra prosjektmappen):
    .venv\\Scripts\\python -m sources.calendar        # i dag og 6 dager frem
    .venv\\Scripts\\python -m sources.calendar 14     # 14 dager
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests

log = logging.getLogger(__name__)
ENV_KEY = "FAMILIEKALENDER_ICS"


class CalendarError(Exception):
    """Kalenderen kunne ikke leses, og det finnes ingen brukbar reservekopi."""


@dataclass
class Event:
    """Én forekomst av en hendelse, i lokal tid."""
    start: datetime | date      # date for heldagshendelser
    end: datetime | date        # for heldag: dagen ETTER siste dag (slik iCal gjør)
    all_day: bool
    title: str
    location: str = ""

    def on_day(self, day: date) -> bool:
        """Varer hendelsen (helt eller delvis) på denne dagen?"""
        if self.all_day:
            return self.start <= day < self.end
        return self.start.date() <= day <= (self.end - timedelta(microseconds=1)).date() \
            if self.end > self.start else self.start.date() == day

    def time_text(self) -> str:
        """«Hele dagen» eller «17:30–18:45»."""
        if self.all_day:
            return "Hele dagen"
        if self.end > self.start and self.end.date() == self.start.date():
            return f"{self.start:%H:%M}–{self.end:%H:%M}"
        return f"{self.start:%H:%M}"


# ---------------------------------------------------------------- henting

def normalise_url(url: str) -> str:
    """iCloud deler ofte lenken som webcal://. Det er bare https:// med et annet navn."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        return "https://" + url[len("webcal://"):]
    return url


def _looks_like_ics(data: bytes) -> bool:
    return data.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"BEGIN:VCALENDAR")


def fetch_ics(url: str, cache_file: Path, timeout: int = 20, session=None) -> bytes:
    """Henter kalenderen. Feiler det, brukes reservekopien.

    Feilmeldinger nevner aldri lenken (requests tar med adressen i sine egne meldinger,
    så vi logger bare typen feil og eventuell statuskode).
    """
    if not url:
        raise CalendarError(f"{ENV_KEY} mangler i .env")
    url = normalise_url(url)
    http = session or requests
    reason = ""
    try:
        resp = http.get(url, timeout=timeout, headers={"User-Agent": "familiehub/0.1"})
        if resp.status_code != 200:
            reason = f"svarte med status {resp.status_code}"
        elif not _looks_like_ics(resp.content):
            reason = "svaret var ikke en kalender (.ics)"
        else:
            data = resp.content
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(cache_file)          # skriver ferdig fil først, så en avbrutt kjøring ikke ødelegger kopien
            return data
    except requests.RequestException as exc:
        reason = f"nettverksfeil ({type(exc).__name__})"

    if cache_file.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        log.warning("Kalender: henting feilet (%s) – bruker reservekopi som er %.0f timer gammel",
                    reason, age.total_seconds() / 3600)
        return cache_file.read_bytes()
    raise CalendarError(f"Kunne ikke hente kalenderen ({reason}), og det finnes ingen reservekopi")


# ---------------------------------------------------------------- tolking

def _to_local(value, tz: ZoneInfo):
    """iCal-tid → lokal tid. Heldag (date) beholdes som date."""
    if isinstance(value, datetime):
        if value.tzinfo is None:            # «flytende» tid uten sone: tolkes som lokal tid
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)
    return value


def events_between(ics: bytes, first: date, last: date, tz: ZoneInfo) -> list[Event]:
    """Alle forekomster fra og med `first` til og med `last`, sortert."""
    if not _looks_like_ics(ics):
        raise CalendarError("Kalenderfilen er ikke en .ics-fil")
    try:
        cal = icalendar.Calendar.from_ical(ics)
    except Exception as exc:        # ødelagt fil utenfra: alle feil gjøres om til én feiltype
        raise CalendarError(f"Kalenderfilen kunne ikke leses ({type(exc).__name__})") from None

    start = datetime.combine(first, time.min, tz)
    stop = datetime.combine(last + timedelta(days=1), time.min, tz)
    events = []
    for comp in recurring_ical_events.of(cal).between(start, stop):
        if str(comp.get("STATUS", "")).upper() == "CANCELLED":
            continue
        if "DTSTART" not in comp:
            continue
        begin = _to_local(comp["DTSTART"].dt, tz)
        all_day = not isinstance(begin, datetime)
        if "DTEND" in comp:
            end = _to_local(comp["DTEND"].dt, tz)
        elif "DURATION" in comp:
            end = begin + comp["DURATION"].dt
        else:
            end = begin + timedelta(days=1) if all_day else begin
        title = str(comp.get("SUMMARY", "")).strip() or "(uten tittel)"
        location = str(comp.get("LOCATION", "")).strip()
        events.append(Event(begin, end, all_day, title, location))

    def sort_key(e: Event):
        day = e.start if e.all_day else e.start.date()
        moment = time.min if e.all_day else e.start.time()
        return (day, not e.all_day, moment, e.title.lower())   # heldag først hver dag

    return sorted(events, key=sort_key)


# ---------------------------------------------------------------- prøvekjøring

def _main(argv: list[str]) -> int:
    from logic.dates import norsk_dato
    from sources.envfile import read_env
    root = Path(__file__).resolve().parent.parent
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    days = int(argv[0]) if argv else 7
    tz = ZoneInfo("Europe/Oslo")
    url = read_env(root / ".env").get(ENV_KEY) or os.environ.get(ENV_KEY, "")
    try:
        ics = fetch_ics(url, root / "data" / "calendar_cache.ics")
        today = datetime.now(tz).date()
        events = events_between(ics, today, today + timedelta(days=days - 1), tz)
    except CalendarError as exc:
        print(f"FEIL: {exc}")
        return 1
    print(f"{len(events)} hendelser fra {today:%d.%m} og {days} dager frem:\n")
    current = None
    for e in events:
        day = e.start if e.all_day else e.start.date()
        if day != current:
            current = day
            print(f"{norsk_dato(day)['ukedag']} {day:%d.%m}")
        place = f"  ({e.location})" if e.location else ""
        print(f"   {e.time_text():<12} {e.title}{place}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
