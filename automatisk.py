"""Automatisk oppdatering av TV-en – startes av Oppgaveplanlegging i Windows (fase 6).

Hver kjøring:
  1. Vekker TV-en og setter Art Mode (tv_vekk.py) – bare på skoledager, og bare hvis
     kjøringen ikke er mer enn 30 min forsinket (f.eks. fordi PC-en var av).
     Kl. 08:00–08:10 (dra-tiden) avbrytes også en TV som står på i TV-modus, med et kort
     trykk til Art Mode. Resten av dagen får den som ser på TV, se ferdig.
  2. Lager bildet og laster det opp (main.py). main.py velger selv riktig bilde ut fra klokka:
     morgen/dag, «Nå må du dra!» kl. 08:00–08:10 på skoledager, kveld fra kl. 18.
  3. Svarer ikke TV-en (kode 2): prøver igjen.
       Skoledager: 3 forsøk med 5 min mellomrom, med vekking hver gang.
       Helg, skoleferie og fridager (skolerute.yaml, samme regel som «Nå må du dra!»):
                  opptil 12 forsøk med 10 min mellomrom, uten vekking
                 (bildet kommer når noen har skrudd på TV-en).
  4. Logger til logs/automatisk.log (ruller ved 1 MB) og holder logs/familiehub.log under 2 MB.

Bruk:
  .venv\\Scripts\\pythonw.exe automatisk.py --planlagt 07:00    (slik Oppgaveplanlegging kjører det – uten vindu)
  .venv\\Scripts\\python automatisk.py --planlagt 07:00         (for å teste – med vindu)
  .venv\\Scripts\\python automatisk.py --helg                   (test helgeoppførsel på en hverdag)

Returkode: 0 = TV-en er oppdatert, 2 = TV-en svarte ikke etter alle forsøk, 1 = annen feil.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
LÅS = ROOT / "data" / "automatisk.lock"
MAKS_FORSINKELSE = timedelta(minutes=30)   # senere enn dette: ikke vekk TV-en, bare ett forsøk
LÅS_GYLDIG = timedelta(hours=3)

log = logging.getLogger("automatisk")


def sett_opp_logg() -> None:
    LOGS.mkdir(exist_ok=True)
    h = RotatingFileHandler(LOGS / "automatisk.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    if sys.stdout is not None:                     # python.exe: vis også i vinduet
        log.addHandler(logging.StreamHandler(sys.stdout))
    # familiehub.log (fra main.py) rulles her, så den ikke vokser for alltid
    fh = LOGS / "familiehub.log"
    if fh.exists() and fh.stat().st_size > 2_000_000:
        gammel = LOGS / "familiehub.log.1"
        if gammel.exists():
            gammel.unlink()
        fh.rename(gammel)


def kjør(skript: str, *args: str) -> int:
    """Kjører et av prosjektets skript med samme Python, uten vindu, og legger utskriften i loggen."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    flagg = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run([sys.executable, skript, *args], cwd=ROOT, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=600, creationflags=flagg)
    except subprocess.TimeoutExpired:
        log.error("%s brukte mer enn 10 min og ble stoppet", skript)
        return 1
    for linje in (r.stdout + r.stderr).splitlines():
        if linje.strip():
            log.info("  %s | %s", skript, linje.rstrip())
    return r.returncode


def forsinkelse(planlagt: str | None, nå: datetime) -> timedelta:
    if not planlagt:
        return timedelta(0)
    t, m = (int(x) for x in planlagt.split(":"))
    skulle = nå.replace(hour=t, minute=m, second=0, microsecond=0)
    if skulle > nå + timedelta(minutes=5):   # tiden er ikke kommet i dag: den tapte kjøringen var i går
        skulle -= timedelta(days=1)
    return max(nå - skulle, timedelta(0))


def fri_i_dag(dag) -> str | None:
    """Helg eller fridag i skoleruta? Gir grunnen (f.eks. «Høstferie»), eller None på skoledager."""
    try:
        import yaml
        from logic.leave import free_reason, load_school_calendar, settings
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        cal = load_school_calendar(ROOT / str(settings(cfg.get("dra"))["skolerute"]))
        return free_reason(dag, cal)
    except Exception as exc:   # skoleruta skal aldri stoppe oppdateringen
        log.warning("Kunne ikke lese skoleruta (%s) – bruker bare ukedagen", exc)
        return "Helg" if dag.weekday() >= 5 else None


def dra_tidsrom() -> tuple:
    """Tidsrommet for «Nå må du dra!» fra config (dra: fra/til/vis), standard 08:00–08:10."""
    from datetime import time as klokke
    try:
        import yaml
        from logic.leave import settings
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        s = settings(cfg.get("dra"))
        return s["fra_tid"], s["til_tid"], bool(s["vis"])
    except Exception as exc:
        log.warning("Kunne ikke lese dra-tidsrommet (%s) – bruker 08:00–08:10", exc)
        return klokke(8, 0), klokke(8, 10), True


def ta_lås() -> bool:
    """Hindrer at to kjøringer går samtidig (f.eks. helgeforsøk som varer til neste planlagte tid)."""
    LÅS.parent.mkdir(exist_ok=True)
    if LÅS.exists() and datetime.now() - datetime.fromtimestamp(LÅS.stat().st_mtime) < LÅS_GYLDIG:
        return False
    LÅS.write_text(f"{os.getpid()} {datetime.now():%Y-%m-%d %H:%M}", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Automatisk oppdatering av Frame-TV-en.")
    p.add_argument("--planlagt", metavar="TT:MM", help="tiden oppgaven skulle gått (for å se om den er forsinket)")
    p.add_argument("--helg", action="store_true", help="oppfør deg som på en fridag (ingen vekking, mange forsøk)")
    p.add_argument("--ikke-vekk", action="store_true", help="aldri vekk TV-en denne kjøringen")
    args = p.parse_args(argv)

    sett_opp_logg()
    nå = datetime.now()
    fri = "Helg (--helg)" if args.helg else fri_i_dag(nå.date())
    helg = fri is not None
    sen = forsinkelse(args.planlagt, nå)
    vekk = not (helg or args.ikke_vekk or sen > MAKS_FORSINKELSE)
    if sen > MAKS_FORSINKELSE:
        forsøk, pause = 1, 0
    elif helg:
        forsøk, pause = 12, 10
    else:
        forsøk, pause = 3, 5

    log.info("=== Start%s: %s, vekking %s, inntil %d forsøk%s",
             f" (planlagt {args.planlagt}, {int(sen.total_seconds() // 60)} min forsinket)" if args.planlagt else "",
             f"fri ({fri})" if helg else "skoledag", "på" if vekk else "av", forsøk,
             f" med {pause} min mellomrom" if forsøk > 1 else "")
    if not ta_lås():
        log.info("En annen kjøring pågår allerede – avslutter.")
        return 0
    try:
        fra, til, dra_på = dra_tidsrom()
        for nr in range(1, forsøk + 1):
            if vekk:
                # Kl. 08:00–08:10 på skoledager avbrytes barne-TV-en med kort trykk til Art Mode (06 #71)
                avbryt = dra_på and fra <= datetime.now().time() < til
                rc = kjør("tv_vekk.py", *(["--avbryt"] if avbryt else []))
                log.info("Vekking: %s", "TV-en er i Art Mode" if rc == 0 else "TV-en ble ikke klar")
            rc = kjør("main.py")
            if rc == 0:
                log.info("=== Ferdig: TV-en er oppdatert (forsøk %d)", nr)
                return 0
            if rc != 2:
                log.error("=== Feil i main.py (kode %d) – se logs/familiehub.log", rc)
                return rc
            if nr < forsøk:
                log.info("TV-en svarte ikke (forsøk %d av %d) – prøver igjen om %d min", nr, forsøk, pause)
                time.sleep(pause * 60)
        log.warning("=== TV-en svarte ikke etter %d forsøk – bildet står som før", forsøk)
        return 2
    finally:
        LÅS.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
