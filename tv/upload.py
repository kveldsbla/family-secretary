"""Sender dagens bilde til Frame-TV-en i Art Mode.

Bygger på frame.py og state.py fra smart-frame-tv (MIT, commit b124b8e). Det vi legger til:
- PNG → JPEG, fordi TV-koden sender JPEG.
- Tidsgrense rundt tilkoblingen til Art Mode-kanalen. Biblioteket kan ellers vente for alltid
  (det skjedde under paring mens TV-en sto i TV-modus).
- Vår egen data/state.json: vi sletter bare bilder familiehub selv har lastet opp.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from PIL import Image

from tv.frame import Frame, FrameAsleep, FrameError, FrameRefused, reachable  # noqa: F401
from tv.state import State

log = logging.getLogger("familiehub.tv")
CONNECT_TIMEOUT = 20     # sekunder for å åpne Art Mode-kanalen
TOTAL_TIMEOUT = 180      # sikkerhetsnett for hele opplastingen


def png_to_jpeg(png: Path, jpg: Path, quality: int = 92) -> Path:
    """Lagrer en JPEG-kopi. Pillow skriver ingen metadata (EXIF/GPS) når vi ikke ber om det."""
    with Image.open(png) as im:
        im.convert("RGB").save(jpg, "JPEG", quality=quality, optimize=True)
    return jpg


def _frame(tv_cfg: dict, data_dir: Path) -> Frame:
    token = data_dir / "token.txt"
    if not token.exists():
        raise FrameRefused("Mangler data/token.txt. Koble til TV-en med: python oppsett.py --par")
    cfg = {"frame": {"ip": tv_cfg.get("ip"), "port": int(tv_cfg.get("port", 8002)),
                     "name": tv_cfg.get("navn") or "SmartFrame"}}
    return Frame(cfg, token_file=str(token))


async def _open(frame: Frame) -> None:
    try:
        await asyncio.wait_for(frame.open(), CONNECT_TIMEOUT)
    except asyncio.TimeoutError:
        await frame.close()
        raise FrameAsleep(f"TV-en åpnet ikke Art Mode-kanalen innen {CONNECT_TIMEOUT} s. "
                          "Står den i TV-modus? Prøv igjen med TV-en i Art Mode.")


async def _send(jpeg: Path, tv_cfg: dict, data_dir: Path) -> dict:
    state = State(str(data_dir / "state.json"))
    frame = _frame(tv_cfg, data_dir)
    await _open(frame)
    try:
        ours = {u["id"] for u in state.uploaded}
        if not state.data.get("before"):
            # Husk bildet TV-en viste før familiehub, så --undo kan sette det tilbake.
            cur = await frame.current() or {}
            if cur.get("content_id") and cur["content_id"] not in ours:
                state.data["before"] = {"id": cur["content_id"], "category": cur.get("category_id") or ""}
        cid, stamp = await frame.upload(str(jpeg))
        state.add_upload(cid, stamp)
        state.save()   # lagres før alt annet, så bildet alltid kan ryddes bort senere
        shown = await frame.make_current(cid)
        state.data["shown"] = shown
        older = [u for u in state.uploaded if u["id"] != cid]
        deleted, gone, skipped = await frame.delete_ours(older) if older else ([], [], [])
        for x in deleted + gone + skipped:
            state.forget(x)
        if skipped:
            log.warning("Lot være %s: TV-en beskriver dem annerledes nå, så de er kanskje ikke våre",
                        ", ".join(skipped))
        state.save()
        return {"id": cid, "shown": shown, "deleted": deleted}
    finally:
        await frame.close()


async def _undo(tv_cfg: dict, data_dir: Path) -> dict:
    state = State(str(data_dir / "state.json"))
    frame = _frame(tv_cfg, data_dir)
    await _open(frame)
    try:
        # Sett tilbake det gamle bildet FØRST (en Frame som mister bildet den viser, kan henge seg opp).
        before, put_back = state.data.get("before") or {}, None
        if before.get("id") and before["id"] not in {u["id"] for u in state.uploaded}:
            try:
                await frame.select(before["id"], category=before.get("category") or None)
                put_back = before["id"]
            except Exception as exc:
                log.warning("Klarte ikke å sette tilbake %s: %s", before["id"], exc)
        deleted, gone, skipped = await frame.delete_ours(list(state.uploaded))
        for x in deleted + gone + skipped:
            state.forget(x)
        state.data["before"] = None
        state.save()
        return {"deleted": deleted, "gone": gone, "skipped": skipped, "put_back": put_back}
    finally:
        await frame.close()


def send(jpeg: Path, tv_cfg: dict, data_dir: Path) -> dict:
    """Laster opp, viser og rydder. Kaster FrameError (eller underklasse) ved feil."""
    if not reachable(tv_cfg.get("ip"), int(tv_cfg.get("port", 8002))):
        raise FrameAsleep(f"TV-en på {tv_cfg.get('ip')} svarer ikke. Er den på (TV eller Art Mode) og på Wi-Fi?")
    try:
        return asyncio.run(asyncio.wait_for(_send(jpeg, tv_cfg, data_dir), TOTAL_TIMEOUT))
    except asyncio.TimeoutError:
        raise FrameError(f"Opplastingen tok mer enn {TOTAL_TIMEOUT} s og ble avbrutt")


def undo(tv_cfg: dict, data_dir: Path) -> dict:
    if not reachable(tv_cfg.get("ip"), int(tv_cfg.get("port", 8002))):
        raise FrameAsleep(f"TV-en på {tv_cfg.get('ip')} svarer ikke.")
    return asyncio.run(asyncio.wait_for(_undo(tv_cfg, data_dir), TOTAL_TIMEOUT))
