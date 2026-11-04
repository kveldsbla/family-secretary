"""Tester TV-logikken med en falsk TV, så ingen ekte TV er nødvendig."""
import asyncio
import json

import pytest
from PIL import Image

import tv.upload as up


def test_png_to_jpeg(tmp_path):
    png = tmp_path / "a.png"
    Image.new("RGBA", (3840, 2160), (240, 235, 225, 255)).save(png)
    jpg = up.png_to_jpeg(png, tmp_path / "a.jpg")
    with Image.open(jpg) as im:
        assert im.format == "JPEG" and im.size == (3840, 2160)
        assert not im.info.get("exif")


class FakeFrame:
    """Oppfører seg som tv.frame.Frame, men holder bildene i en liste."""
    photos = []
    showing = "SAM-S10004506"
    hang = False

    def __init__(self, cfg, token_file=None):
        self.cfg = cfg

    async def open(self):
        if FakeFrame.hang:
            await asyncio.sleep(3600)

    async def close(self):
        pass

    async def current(self):
        return {"content_id": FakeFrame.showing, "category_id": "MY-C0002"}

    async def upload(self, path):
        cid = f"MY_F{len(FakeFrame.photos) + 1:04d}"
        FakeFrame.photos.append(cid)
        return cid, "2026:11:02 17:00:00"

    async def make_current(self, cid):
        FakeFrame.showing = cid
        return True

    async def select(self, cid, category=None):
        FakeFrame.showing = cid

    async def delete_ours(self, records):
        ids = [r["id"] for r in records]
        FakeFrame.photos = [p for p in FakeFrame.photos if p not in ids]
        return ids, [], []


@pytest.fixture
def fake(tmp_path, monkeypatch):
    FakeFrame.photos, FakeFrame.showing, FakeFrame.hang = [], "SAM-S10004506", False
    monkeypatch.setattr(up, "Frame", FakeFrame)
    monkeypatch.setattr(up, "reachable", lambda ip, port: True)
    (tmp_path / "token.txt").write_text("hemmelig")
    return tmp_path


TV = {"ip": "192.168.1.50"}


def test_send_keeps_only_newest_and_undo_restores(fake, tmp_path):
    jpg = tmp_path / "x.jpg"
    jpg.write_bytes(b"jpeg")
    first = up.send(jpg, TV, fake)
    second = up.send(jpg, TV, fake)
    assert second["deleted"] == [first["id"]]          # forrige familiehub-bilde ryddet bort
    assert FakeFrame.photos == [second["id"]]
    state = json.loads((fake / "state.json").read_text())
    assert state["before"]["id"] == "SAM-S10004506"    # husker eierens bilde
    r = up.undo(TV, fake)
    assert r["put_back"] == "SAM-S10004506" and FakeFrame.showing == "SAM-S10004506"
    assert FakeFrame.photos == []


def test_missing_token(fake, tmp_path):
    (fake / "token.txt").unlink()
    with pytest.raises(up.FrameRefused, match="token"):
        up.send(tmp_path / "x.jpg", TV, fake)


def test_connect_timeout(fake, tmp_path, monkeypatch):
    FakeFrame.hang = True
    monkeypatch.setattr(up, "CONNECT_TIMEOUT", 0.2)
    with pytest.raises(up.FrameAsleep, match="Art Mode"):
        up.send(tmp_path / "x.jpg", TV, fake)


def test_tv_off(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(up, "reachable", lambda ip, port: False)
    with pytest.raises(up.FrameAsleep, match="svarer ikke"):
        up.send(tmp_path / "x.jpg", TV, fake)
