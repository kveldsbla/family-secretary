"""Nedtelling til neste ferie eller en egen dag (I-13), f.eks. «45 dager til juleferie».

Feriene kommer fra skolerute.yaml: perioder med «ferie» i navnet (Høstferie, Juleferie …).
Enkeltstående fridager (planleggingsdager, 17. mai) teller ikke. Egne nedtellinger
(bursdag, hyttetur) legges under «nedtelling:» i config.yaml. Bare den nærmeste vises.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from logic.leave import SchoolCalendar, _as_date

MAKS_DAGER = 60          # lenger unna enn dette: ingen linje
FERIE_EMOJI = {"høstferie": "🍂", "juleferie": "🎄", "vinterferie": "⛷️",
               "påskeferie": "🐣", "sommerferie": "☀️"}
FERIE_STANDARD = "🎒"
EGEN_STANDARD = "🎉"


@dataclass
class Target:
    dag: date
    tekst: str           # «juleferie», «julaften», «Lunas bursdag»
    emoji: str


def settings(cfg) -> tuple[list[Target], int]:
    """«nedtelling:» i config.yaml → (egne nedtellinger, maks dager).

    Kan skrives som en liste med datoer, eller med «maks_dager» og «datoer» under.
    """
    if cfg is None:
        return [], MAKS_DAGER
    if isinstance(cfg, list):
        items, maks = cfg, MAKS_DAGER
    elif isinstance(cfg, dict):
        items, maks = cfg.get("datoer") or [], int(cfg.get("maks_dager", MAKS_DAGER))
    else:
        raise ValueError("nedtelling: må være en liste med datoer (se config.example.yaml)")
    targets = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict) or "dato" not in item or not str(item.get("tekst") or "").strip():
            raise ValueError(f"nedtelling nr. {i} må ha både «dato» og «tekst»")
        targets.append(Target(_as_date(item["dato"], f"nedtelling nr. {i}"), str(item["tekst"]).strip(),
                              str(item.get("emoji") or EGEN_STANDARD)))
    return targets, maks


def holidays(cal: SchoolCalendar | None, today: date) -> list[Target]:
    """Første fridag i hver ferie i skoleruta. Mangler eller er utløpt skoleruta: ingen."""
    if cal is None or (cal.gjelder_til and today > cal.gjelder_til):
        return []
    out = []
    for start, _end, name in cal.fridager:
        if "ferie" in name.lower():
            out.append(Target(start, name.lower(), FERIE_EMOJI.get(name.lower(), FERIE_STANDARD)))
    return out


def countdown(today: date, targets: list[Target], maks_dager: int = MAKS_DAGER) -> dict | None:
    """Den nærmeste nedtellingen fra i dag (0–maks_dager dager), eller None."""
    ahead = [t for t in targets if 0 <= (t.dag - today).days <= maks_dager]
    if not ahead:
        return None
    t = min(ahead, key=lambda x: x.dag)      # ved likt: den første i lista (ferie før egne)
    days = (t.dag - today).days
    if days == 0:
        text = f"I dag: {t.tekst}!"
    elif days == 1:
        text = f"I morgen: {t.tekst}!"
    else:
        text = f"{days} dager til {t.tekst}"
    return {"tekst": text, "emoji": t.emoji, "dager": days}
