"""«Nå må du dra!» – det tredje bildet, kl. 08:00–08:10 på skoledager (fase 5.1, 06 #47–#49).

Her avgjøres tre ting, uten nett:
  1. Er det skoledag? Helg og fridagene i skolerute.yaml er ikke skoledager.
  2. Er klokka innenfor tidsrommet (dra: fra/til i config.yaml, standard 08:00–08:10)?
  3. Hvilke kalenderhendelser gjelder barna (personer med «barn: true» i config.yaml)?
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

import yaml

from logic.day_plan import Person, split_tag
from sources.calendar import Event

log = logging.getLogger(__name__)

DEFAULTS = {
    "vis": True,                        # false = aldri vis bildet automatisk (--dra virker fortsatt)
    "fra": "08:00",
    "til": "08:10",                     # fra og med «fra», til (ikke med) «til»
    "tittel": "Nå må du dra!",
    "undertekst": "Sko, jakke og sekk – av gårde!",
    "ha_med": ["Sekk", "Matpakke", "Drikkeflaske"],
    "maks_hendelser": 4,               # mer får ikke plass over bunnlinjen
    "skolerute": "skolerute.yaml",
}


def settings(cfg: dict | None) -> dict:
    """Standardverdiene, overstyrt av det som står under «dra:» i config.yaml."""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (cfg or {}).items() if v is not None})
    s["fra_tid"] = parse_clock(s["fra"])
    s["til_tid"] = parse_clock(s["til"])
    if s["til_tid"] <= s["fra_tid"]:
        raise ValueError(f"dra: til ({s['til']}) må være senere enn fra ({s['fra']})")
    if not isinstance(s["ha_med"], list):
        raise ValueError("dra: ha_med må være en liste, f.eks. [\"Sekk\", \"Matpakke\"]")
    s["ha_med"] = [str(x).strip() for x in s["ha_med"] if str(x).strip()]
    return s


def parse_clock(value) -> time:
    """«08:10» → 08:10. YAML kan gjøre 08:10 uten fnutter om til minutter (490), så det tas også."""
    if isinstance(value, int):                       # 08:10 uten fnutter leses av YAML som 490 (minutter)
        return time(value // 60, value % 60)
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", str(value).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"klokkeslett må skrives TT:MM, ikke «{value}»")
    return time(int(m.group(1)), int(m.group(2)))


# ---------------------------------------------------------------- skolerute

@dataclass
class SchoolCalendar:
    fridager: list[tuple[date, date, str]] = field(default_factory=list)
    gjelder_til: date | None = None


def load_school_calendar(path: Path) -> SchoolCalendar | None:
    """Leser skolerute.yaml. None = filen mangler (alle hverdager regnes da som skoledager)."""
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    cal = SchoolCalendar(gjelder_til=_as_date(data.get("gjelder_til"), "gjelder_til") if data.get("gjelder_til") else None)
    for i, p in enumerate(data.get("fridager") or [], start=1):
        if not isinstance(p, dict) or "fra" not in p:
            raise ValueError(f"fridager nr. {i} i {path.name} mangler «fra»")
        start = _as_date(p["fra"], f"fridager nr. {i}")
        end = _as_date(p.get("til") or p["fra"], f"fridager nr. {i}")
        if end < start:
            raise ValueError(f"fridager nr. {i} i {path.name}: «til» er før «fra»")
        cal.fridager.append((start, end, str(p.get("navn") or "Fridag")))
    return cal


def _as_date(value, where: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"{where}: dato må skrives ÅÅÅÅ-MM-DD, ikke «{value}»") from None


def free_reason(day: date, cal: SchoolCalendar | None) -> str | None:
    """Hvorfor er det ikke skole denne dagen? None = vanlig skoledag."""
    if day.weekday() >= 5:
        return "Helg"
    if cal:
        for start, end, name in cal.fridager:
            if start <= day <= end:
                return name
    return None


def leave_check(now: datetime, s: dict, cal: SchoolCalendar | None) -> tuple[bool, str]:
    """(skal «Nå må du dra!» vises?, forklaring til loggen)."""
    if not s["vis"]:
        return False, "skrudd av (dra: vis: false)"
    if not (s["fra_tid"] <= now.time().replace(second=0, microsecond=0) < s["til_tid"]):
        return False, "utenfor tidsrommet"
    reason = free_reason(now.date(), cal)
    if reason:
        return False, f"ikke skoledag ({reason})"
    if cal is None:
        log.warning("Fant ikke skoleruta – regner alle hverdager som skoledager")
    elif cal.gjelder_til and now.date() > cal.gjelder_til:
        log.warning("Skoleruta gjelder bare til %s – legg inn neste skoleår i skolerute.yaml",
                    cal.gjelder_til.isoformat())
    return True, f"skoledag kl. {s['fra']}–{s['til']}"


# ---------------------------------------------------------------- barnas avtaler

def kids_events(events: list[Event], persons: list[Person]) -> list[Event]:
    """Hendelsene som gjelder barna: merket med minst ett barn, eller felles heldagshendelser.

    Uten «barn: true» i config.yaml vet vi ikke hvem barna er, og da vises alt.
    """
    if not any(p.barn for p in persons):
        log.warning("Ingen personer har «barn: true» i config.yaml – «Nå må du dra!» viser hele kalenderen")
        return list(events)
    out = []
    for e in events:
        who, _ = split_tag(e.title, persons)
        if any(p.barn for p in who) or (not who and e.all_day):
            out.append(e)
    return out
