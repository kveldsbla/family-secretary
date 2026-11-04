"""Dagens plan: hvem gjelder hendelsen, og når på dagen? (fase 4, 06 #31)

Kalenderen merker personer med initialen først i tittelen, etterfulgt av mellomrom:
    «L Turdag – matpakke»        → gjelder L
    «E L Foreldremøte»           → gjelder E og L (også «E & L», «E og L», «E, L» og «E/L»)
    «L: Turdag»                  → kolon etter initialen går også fint
    «Middag hos besteforeldre»   → uten initial: felles for hele familien
Bare initialene i config.yaml («personer:») regnes som merker, og de må stå alene
med samme store bokstav: «Lisa …», «L-lag …» og «l …» røres ikke.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sources.calendar import Event

log = logging.getLogger(__name__)

MARK_BAD = re.compile(r"[\s&+,/:]")                 # tegn som skiller merker, kan ikke være i et merke
JOIN = r"(?:\s*[&+,/]\s*|\s+og\s+|\s+)"               # mellom to initialer: & + , / «og» eller mellomrom
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
DEFAULT_COLOR = "#7a7268"                            # dempet grå hvis fargen mangler eller er feil
DEFAULT_COLOR_KVELD = "#a19a8f"                      # lys grå mot det mørke kveldspapiret (fase 5.2)


@dataclass(frozen=True)
class Person:
    navn: str
    merke: str
    farge: str
    barn: bool = False          # «barn: true» i config.yaml – brukes av «Nå må du dra!» (fase 5.1)
    farge_kveld: str = ""       # lysere farge mot kveldspapiret fra kl. 18 (fase 5.2); tom = dagfargen


# ---------------------------------------------------------------- personer fra config

def load_persons(entries) -> list[Person]:
    """Leser «personer:» fra config.yaml. Feil i oppsettet gir ValueError med forklaring."""
    persons: list[Person] = []
    seen: set[str] = set()
    for i, p in enumerate(entries or [], start=1):
        if not isinstance(p, dict):
            raise ValueError(f"personer nr. {i} må ha navn, merke og farge")
        navn = str(p.get("navn") or "").strip()
        merke = str(p.get("merke") or "").strip()
        if not navn or not merke:
            raise ValueError(f"personer nr. {i} mangler navn eller merke")
        if MARK_BAD.search(merke):
            raise ValueError(f"merket til personer nr. {i} kan ikke inneholde mellomrom eller tegnene & + , / :")
        if merke.casefold() in seen:
            raise ValueError(f"merket «{merke}» er brukt av to personer")
        seen.add(merke.casefold())
        farge = str(p.get("farge") or "").strip()
        if not HEX.match(farge):
            log.warning("personer nr. %d: farge «%s» er ikke en hex-farge (f.eks. #9b6a4a) – bruker grå", i, farge)
            farge = DEFAULT_COLOR
        farge_kveld = str(p.get("farge_kveld") or "").strip()
        if not farge_kveld:
            log.warning("personer nr. %d: farge_kveld mangler – bruker dagfargen om kvelden (lav kontrast "
                        "mot kveldspapiret)", i)
            farge_kveld = DEFAULT_COLOR_KVELD if farge == DEFAULT_COLOR else farge
        elif not HEX.match(farge_kveld):
            log.warning("personer nr. %d: farge_kveld «%s» er ikke en hex-farge – bruker grå", i, farge_kveld)
            farge_kveld = DEFAULT_COLOR_KVELD
        persons.append(Person(navn, merke, farge, barn=p.get("barn") is True, farge_kveld=farge_kveld))
    return persons


def split_tag(title: str, persons: list[Person]) -> tuple[list[Person], str]:
    """«E L Foreldremøte» → ([E, L], «Foreldremøte»). Uten initial først: ([], tittelen uendret)."""
    if not persons:
        return [], title.strip()
    marks = sorted({p.merke for p in persons}, key=len, reverse=True)       # lengste først
    mark = "(?:" + "|".join(re.escape(m) for m in marks) + r")(?=[\s&+,/:]|$)"   # initialen må stå alene
    m = re.match(rf"\s*((?:{mark})(?:{JOIN}(?:{mark}))*)\s*:?\s*", title)
    if not m:
        return [], title.strip()
    found = set(re.findall(mark, m.group(1)))
    who = [p for p in persons if p.merke in found]                         # alltid i rekkefølgen fra config
    rest = title[m.end():].strip() or "(uten tittel)"
    return who, rest


# ---------------------------------------------------------------- dagens plan

def _time_label(e: Event, day: date) -> tuple[str, time | None]:
    """Tekst i tidskolonnen og klokkeslettet hendelsen starter denne dagen (None = hele dagen)."""
    if e.all_day:
        return "Hele dagen", None
    starts_today = e.start.date() == day
    ends_today = e.end > e.start and (e.end - timedelta(microseconds=1)).date() == day
    if starts_today:
        return f"{e.start:%H:%M}", e.start.time()
    if ends_today:                                     # startet i går, slutter i dag
        return f"til {e.end:%H:%M}", time.min
    return "Hele dagen", None                         # varer gjennom hele dagen


def is_over(e: Event, now: datetime) -> bool:
    """Er hendelsen ferdig? Heldag varer hele dagen; ellers gjelder sluttiden (eller start uten varighet)."""
    if e.all_day:
        return False
    end = e.end if e.end > e.start else e.start
    return end <= now


def build_day(events: list[Event], day: date, persons: list[Person],
              afternoon_from: int = 14, max_items: int = 6, now: datetime | None = None) -> dict:
    """Gjør kalenderhendelsene for én dag om til det malen trenger.

    Med `now` hoppes hendelser som allerede er ferdige, over (de telles i «passert»).
    Returnerer {"hendelser": [...], "flere": antall som ikke fikk plass, "passert": antall ferdige}.
    Hver hendelse: tid, tittel, personer (navn + farge + farge_kveld), felles, heldag, ettermiddag.
    """
    items = []
    passed = 0
    for e in events:
        if not e.on_day(day):
            continue
        if now is not None and is_over(e, now):
            passed += 1
            continue
        who, title = split_tag(e.title, persons)
        label, starts = _time_label(e, day)
        items.append({
            "tid": label,
            "tittel": title,
            "personer": [{"navn": p.navn, "farge": p.farge, "farge_kveld": p.farge_kveld or p.farge} for p in who],
            "navn": _names(who),
            "felles": not who,
            "heldag": starts is None,
            "ettermiddag": starts is not None and starts.hour >= afternoon_from,
            "_sort": (0 if starts is None else 1, starts or time.min, title.casefold()),
        })
    items.sort(key=lambda x: x["_sort"])
    for it in items:
        del it["_sort"]

    max_items = max(int(max_items), 1)
    extra = 0
    if len(items) > max_items:                       # siste plass brukes til «+N til»
        extra = len(items) - (max_items - 1)
        items = items[:max_items - 1]
    return {"hendelser": items, "flere": extra, "passert": passed}


def _names(who: list[Person]) -> str:
    """«Barn 8» · «Voksen 1 og Barn 8» · «Voksen 1, Voksen 2 og Barn 8» · tom for felles."""
    names = [p.navn for p in who]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " og " + names[-1]


def summary_line(plan: dict) -> str:
    """Én linje til loggen – uten titler, bare antall."""
    n = len(plan["hendelser"]) + plan["flere"]
    felles = sum(1 for h in plan["hendelser"] if h["felles"])
    line = f"{n} hendelser ({felles} felles)" + (f", {plan['flere']} skjult" if plan["flere"] else "")
    return line + (f", {plan['passert']} passert" if plan.get("passert") else "")


# ---------------------------------------------------------------- demodata

def demo_events(day: date, persons: list[Person], tz: ZoneInfo) -> list[Event]:
    """Oppdiktet dag for «--demo», laget av merkene som står i config."""
    marks = [p.merke for p in persons]

    def m(*idx: int) -> str:                      # uten personer i config: ingen merker
        return " ".join(marks[i % len(marks)] for i in idx) + " " if marks else ""

    def at(h: int, mi: int = 0) -> datetime:
        return datetime.combine(day, time(h, mi), tz)

    nxt = day + timedelta(days=1)
    return [
        Event(day, nxt, True, m(4) + "Turdag – matpakke og ekstra votter"),
        Event(at(8, 30), at(9, 30), False, m(2) + "Prøve i matte"),
        Event(at(16), at(16, 15), False, m(1) + "Henting"),
        Event(at(17, 30), at(18, 30), False, m(3) + "Korps"),
        Event(at(19), at(20), False, m(0, 1) + "Foreldremøte"),
        Event(at(20, 30), at(21), False, "Taco-kveld er flyttet til fredag"),
    ]
