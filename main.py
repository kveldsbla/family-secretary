"""familiehub – lager dagens bilde og sender det til Frame-TV-en.

Bruk (fra prosjektmappen):
    python main.py               # ekte vær fra Yr → bilde → TV-en
    python main.py --dry-run     # som over, men bildet lagres bare lokalt
    python main.py --demo        # oppdiktet vær og kalender (kan kombineres med --dry-run)
    python main.py --html-only   # bare HTML (rask designsjekk i nettleseren)
    python main.py --demo vinter --tid kveld   # late som klokka er 19:30 (også morgen, dag, ettermiddag eller 07:15)
    python main.py --demo --tid dra             # «Nå må du dra!» slik det ser ut kl. 08:00 på en skoledag
    python main.py --dra --dry-run              # «Nå må du dra!» med ekte data nå, uansett klokke og dag
    python main.py --undo        # fjern alle familiehub-bilder fra TV-en og vis det gamle bildet

Returkoder: 0 = OK, 1 = feil, 2 = TV-en svarer ikke (av eller utenfor nettet).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from logic.clothing import clothing_advice, summary_line
from logic.dates import norsk_dato
from logic.outdoor import outdoor_icons
from logic.day_plan import build_day, demo_events, load_persons
from logic.day_plan import summary_line as plan_summary
from logic.day_weather import summarize, target_day
from logic.leave import SchoolCalendar, kids_events, leave_check, load_school_calendar
from logic.leave import settings as leave_settings
from render.render import RenderError, build_html, find_chrome, render_png
from sources.calendar import ENV_KEY, CalendarError, events_between, fetch_ics
from sources.envfile import read_env
from sources.photos import photo_of_the_day
from sources.weather import WeatherError, demo_forecast, fetch_forecast, parse_points

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
DATA = ROOT / "data"
LOGS = ROOT / "logs"
KEEP_DAYS = 7
EVENING_FROM = 18          # standard: fra kl. 18 viser bildet i kveld + i morgen (dagen: kveld_fra)
TIME_NAMES = {"morgen": "07:00", "dra": "08:00", "dag": "12:00", "ettermiddag": "16:00", "kveld": "19:30"}

log = logging.getLogger("familiehub")


def setup_logging() -> None:
    LOGS.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(LOGS / "familiehub.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)


def load_config(path: Path, demo: bool) -> dict:
    if not path.exists():
        if demo:
            path = ROOT / "config.example.yaml"   # demo virker uten egen config
        else:
            sys.exit(f"Fant ikke {path.name}. Kjør først: python oppsett.py")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_weather(cfg: dict, tz: ZoneInfo, now_local: datetime, demo: str | None) -> dict | None:
    """Henter og oppsummerer været. Feiler det, returneres None og bildet lages likevel."""
    day = cfg.get("dagen", {})
    try:
        if demo:
            data = demo_forecast(now_local.astimezone(timezone.utc), demo)
        else:
            place = cfg["sted"]
            data = fetch_forecast(place["lat"], place["lon"], cfg["yr"]["user_agent"],
                                  DATA / "weather_cache.json", altitude=place.get("hoyde_moh"))
        return summarize(parse_points(data, tz), now_local,
                         school_from=int(day.get("skoletid_fra", 8)),
                         school_to=int(day.get("skoletid_til", 15)),
                         show_hours=day.get("vis_timer"),
                         evening_from=int(day.get("kveld_fra", EVENING_FROM)))
    except (WeatherError, KeyError, TypeError, ValueError) as exc:
        log.error("Vær feilet: %s", exc)
        return None


def get_clothing(cfg: dict, vaer: dict | None) -> dict | None:
    """Klesråd ut fra været i skoletiden. Feiler det, lages bildet uten klesråd."""
    if not vaer or not vaer.get("outdoor"):
        return None
    try:
        advice = clothing_advice(vaer["outdoor"]["raw"], cfg.get("klesrad"))
    except (KeyError, TypeError, ValueError) as exc:
        log.error("Klesråd feilet (sjekk «klesrad:» i config.yaml): %s", exc)
        return None
    log.info("Klesråd: %s", summary_line(advice))
    return advice


def get_outdoor(cfg: dict, vaer: dict | None) -> dict | None:
    """Ikoner for «Ute i dag». Feiler det, vises bare tallene."""
    if not vaer or not vaer.get("outdoor"):
        return None
    try:
        return outdoor_icons(vaer["outdoor"]["raw"], cfg.get("ute"), cfg.get("klesrad"))
    except (KeyError, TypeError, ValueError) as exc:
        log.error("Ute-ikoner feilet (sjekk «ute:» i config.yaml): %s", exc)
        return None

def get_plan(cfg: dict, tz: ZoneInfo, now_local: datetime, demo: str | None,
             kids_only: bool = False, max_items: int | None = None) -> dict | None:
    """Hendelsene i familiekalenderen for samme dag som været.

    `kids_only` (for «Nå må du dra!»): bare hendelser merket med et barn, og felles heldagshendelser.

    Om dagen: «I dag», der det som er ferdig, er borte. Fra kveld (dagen: kveld_fra, standard
    kl. 18): «I morgen», og det som gjenstår i kveld, ligger i plan["kveld"] (tittel «I kveld»).
    None = ingen kalenderlenke i .env, og feltet skjules. Feiler henting eller tolking,
    vises «–» i feltet og resten av bildet lages likevel. Lenken skrives aldri til loggen.
    """
    day, label = target_day(now_local, int(cfg.get("dagen", {}).get("kveld_fra", EVENING_FROM)))
    today = now_local.date()
    evening = day != today
    cal = cfg.get("kalender") or {}
    failed = {"tittel": label, "feil": True, "hendelser": [], "flere": 0}
    try:
        persons = load_persons(cfg.get("personer"))
        if demo:
            events = demo_events(today, persons, tz) + (demo_events(day, persons, tz) if evening else [])
        else:
            url = read_env(ROOT / ".env").get(ENV_KEY) or os.environ.get(ENV_KEY, "")
            if not url:
                log.info("Kalender: %s mangler i .env – feltet vises ikke", ENV_KEY)
                return None
            events = events_between(fetch_ics(url, DATA / "calendar_cache.ics"), today, day, tz)
        if kids_only:
            events = kids_events(events, persons)
        plan = build_day(events, day, persons, max_items=max_items or int(cal.get("maks_hendelser", 6)),
                         now=now_local)     # det som allerede er ferdig, vises ikke
        if evening:                         # det som gjenstår i kveld (uten heldag), over morgendagen
            kveld = build_day([e for e in events if not e.all_day], today, persons, max_items=int(cal.get("maks_i_kveld", 4)),
                              now=now_local)
            kveld["tittel"] = "I kveld"
            plan["kveld"] = kveld
    except (CalendarError, ValueError, TypeError) as exc:
        log.error("Kalender feilet: %s", exc)
        return failed
    except Exception as exc:                 # uventet feil i et bibliotek: bare typen logges (kan inneholde lenken)
        log.error("Kalender feilet uventet (%s)", type(exc).__name__)
        return failed
    plan["tittel"] = label
    if evening:
        log.info("Kalender i kveld: %s", plan_summary(plan["kveld"]))
    log.info("Kalender %s: %s", label.lower(), plan_summary(plan))
    return plan


def parse_time(value: str, now: datetime) -> datetime:
    """«kveld» eller «19:30» → i dag kl. 19:30 (for demo og test av dag- og kveldsbildet)."""
    text = TIME_NAMES.get(value.strip().lower(), value.strip())
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"--tid må være morgen, dra, dag, ettermiddag, kveld eller TT:MM, ikke «{value}»")
    return datetime.combine(now.date(), dtime(int(m.group(1)), int(m.group(2))), now.tzinfo)


def get_leave(cfg: dict, now: datetime, forced: bool, demo: bool) -> dict | None:
    """Innstillingene for «Nå må du dra!» hvis det bildet skal lages nå, ellers None.

    Vises kl. 08:00–08:10 (dra: fra/til) på skoledager etter skolerute.yaml. --dra tvinger det fram.
    Med --demo regnes alle hverdager som skoledager, så --demo --tid dra alltid virker på hverdager.
    Feil i oppsettet logges, og da lages vanlig dagbilde.
    """
    try:
        s = leave_settings(cfg.get("dra"))
        if forced:
            log.info("Nå må du dra!: tvunget med --dra")
            return s
        cal = SchoolCalendar() if demo else load_school_calendar(ROOT / str(s["skolerute"]))
        show, why = leave_check(now, s, cal)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        log.error("Nå må du dra! feilet (sjekk «dra:» i config.yaml og skolerute.yaml): %s", exc)
        return None
    if show:
        log.info("Nå må du dra!: %s", why)
        return s
    if why != "utenfor tidsrommet":
        log.info("Nå må du dra!: vises ikke – %s", why)
    return None


def get_photo(cfg: dict, day) -> dict | None:
    """Dagens familiefoto fra mappen «bilder» (eller foto: mappe: i config.yaml).

    None = ingen bilder, og kalenderen får hele høyre kolonne. Feil stopper aldri bildet.
    """
    foto = cfg.get("foto") or {}
    if foto.get("vis") is False:
        return None
    folder = ROOT / str(foto.get("mappe") or "bilder")    # en full sti (C:/...) virker også
    try:
        photo = photo_of_the_day(folder, day)
    except OSError as exc:
        log.error("Foto feilet (%s)", type(exc).__name__)
        return None
    if photo:
        log.info("Foto: %s", photo["fil"])
    else:
        log.info("Foto: ingen bilder i %s – feltet vises ikke", folder.name)
    return photo


def clean_old_images() -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for p in OUTPUT.glob("familiehub-*.png"):
        if p.stat().st_mtime < cutoff:
            p.unlink()


def run_undo(cfg: dict) -> int:
    from tv.upload import FrameAsleep, FrameError, undo
    print("Dette fjerner alle bilder familiehub har lagt på TV-en. Egne bilder røres ikke.")
    if input('Skriv "ja" for å fortsette: ').strip().lower() != "ja":
        print("Ingenting endret.")
        return 1
    try:
        r = undo(cfg.get("tv", {}), DATA)
    except FrameAsleep as exc:
        log.error("%s", exc)
        return 2
    except FrameError as exc:
        log.error("Undo feilet: %s", exc)
        return 1
    log.info("Undo: fjernet %s%s", ", ".join(r["deleted"]) or "ingenting",
             f", ba TV-en vise {r['put_back']} igjen" if r["put_back"] else "")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lager dagens familiehub-bilde og sender det til TV-en.")
    parser.add_argument("--dry-run", action="store_true", help="lag bildet lokalt uten å sende til TV-en")
    parser.add_argument("--demo", nargs="?", const="vinter", choices=["vinter", "regn", "sol"],
                        help="bruk oppdiktet vær og kalender (standard: vinter)")
    parser.add_argument("--html-only", action="store_true", help="lag bare output/siste.html")
    parser.add_argument("--tid", metavar="TID",
                        help="late som klokka er TID: morgen (07:00), dra (08:00), dag (12:00), "
                             "ettermiddag (16:00), kveld (19:30) eller TT:MM – for å se dag- og kveldsbildet")
    parser.add_argument("--dra", action="store_true",
                        help="lag «Nå må du dra!»-bildet uansett klokke og dag (for test)")
    parser.add_argument("--undo", action="store_true", help="fjern familiehub-bildene fra TV-en")
    parser.add_argument("--config", default="config.yaml", help="sti til config-fil")
    args = parser.parse_args(argv)

    setup_logging()
    cfg = load_config(ROOT / args.config, bool(args.demo))
    if args.undo:
        return run_undo(cfg)

    tz = ZoneInfo(cfg.get("tidssone", "Europe/Oslo"))
    now = datetime.now(tz)
    if args.tid:
        real_now = now
        try:
            now = parse_time(args.tid, now)
        except ValueError as exc:
            parser.error(str(exc))
        log.info("Tid satt til %s (--tid)", now.strftime("%H:%M"))
        if not args.demo and (real_now - now).total_seconds() > 3600:
            log.warning("--tid %s er tidligere enn nå: Yr har ikke varsel for passerte timer, så vær, "
                        "«Ute» og klesråd kan mangle. Bruk --demo sammen med --tid for å prøve tidligere tider.",
                        now.strftime("%H:%M"))
    dra = get_leave(cfg, now, args.dra, bool(args.demo))
    vaer = get_weather(cfg, tz, now, args.demo)
    # Kveldsfarger fra kl. 18 (fase 5.2): samme byttetid som «I kveld» + «I morgen» (06 #42).
    # «Nå må du dra!» har egne farger og er ikke med (ventes med til dra-bildet er sett på TV-en).
    evening_from = int((cfg.get("dagen") or {}).get("kveld_fra", EVENING_FROM))
    kveld = not dra and target_day(now, evening_from)[0] != now.date()
    if kveld:
        log.info("Kveldsfarger (fra kl. %d)", evening_from)
    context = {
        "dato": norsk_dato(now.date()),
        "vaer": vaer,
        "klar": get_clothing(cfg, vaer),
        "plan": get_plan(cfg, tz, now, args.demo, kids_only=bool(dra),
                         max_items=dra["maks_hendelser"] if dra else None),
        "ute": get_outdoor(cfg, vaer),
        "foto": None if dra else get_photo(cfg, now.date()),
        "dra": dra,
        "kveld": kveld,
        "oppdatert": now.strftime("%H:%M"),
        "demo": bool(args.demo),
        "tid_satt": bool(args.tid),
    }

    OUTPUT.mkdir(exist_ok=True)
    html_file = OUTPUT / "siste.html"
    html_file.write_text(build_html("dra.html" if dra else "morning.html", context), encoding="utf-8")
    log.info("HTML skrevet: %s", html_file)
    if args.html_only:
        return 0

    render_cfg = cfg.get("render", {})
    width, height = int(render_cfg.get("bredde", 3840)), int(render_cfg.get("hoyde", 2160))
    png = OUTPUT / f"familiehub-{now:%Y%m%d-%H%M}.png"
    try:
        chrome = find_chrome(render_cfg.get("chrome"))
        render_png(html_file, png, width, height, chrome)
    except RenderError as exc:
        log.error("Rendering feilet: %s", exc)
        return 1
    shutil.copyfile(png, OUTPUT / "siste.png")
    clean_old_images()
    log.info("Bilde laget: %s (%d x %d)", png, width, height)

    if args.dry_run:
        return 0

    # ---- Send til TV-en
    from tv.upload import FrameAsleep, FrameError, png_to_jpeg, send
    jpeg = png_to_jpeg(png, OUTPUT / "siste.jpg")
    try:
        result = send(jpeg, cfg.get("tv", {}), DATA)
    except FrameAsleep as exc:
        log.warning("%s", exc)
        return 2
    except FrameError as exc:
        log.error("Opplasting feilet: %s", exc)
        return 1
    log.info("TV: viser %s%s, fjernet %s", result["id"],
             "" if result["shown"] else " (TV-en holdt på et annet bilde – prøv igjen i Art Mode)",
             ", ".join(result["deleted"]) or "ingenting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
