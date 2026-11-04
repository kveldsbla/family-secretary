"""Tester for hent_fonter.py – uten nett (falsk nedlasting)."""
import hent_fonter as hf


def _fake_files(monkeypatch):
    content = {f"https://x/{n}": f"innhold {n}".encode() for n in ("a.ttf", "b.txt")}
    files = [(u.rsplit("/", 1)[1], u, hf.sha256(d)) for u, d in content.items()]
    monkeypatch.setattr(hf, "FILES", files)
    return content


def test_download_saves_verified_files(tmp_path, monkeypatch):
    content = _fake_files(monkeypatch)
    assert hf.download(tmp_path, fetcher=content.__getitem__) == 0
    assert (tmp_path / "a.ttf").read_bytes() == content["https://x/a.ttf"]
    assert hf.check(tmp_path) == {"a.ttf": "ok", "b.txt": "ok"}


def test_wrong_checksum_is_not_saved(tmp_path, monkeypatch):
    _fake_files(monkeypatch)
    assert hf.download(tmp_path, fetcher=lambda url: b"noe annet") == 2
    assert not (tmp_path / "a.ttf").exists()
    assert hf.check(tmp_path) == {"a.ttf": "mangler", "b.txt": "mangler"}


def test_existing_good_files_are_not_downloaded_again(tmp_path, monkeypatch):
    content = _fake_files(monkeypatch)
    hf.download(tmp_path, fetcher=content.__getitem__)
    calls = []
    assert hf.download(tmp_path, fetcher=lambda url: calls.append(url)) == 0
    assert calls == []


def test_changed_file_is_reported_and_replaced(tmp_path, monkeypatch):
    content = _fake_files(monkeypatch)
    hf.download(tmp_path, fetcher=content.__getitem__)
    (tmp_path / "a.ttf").write_bytes(b"tuklet med")
    assert hf.check(tmp_path)["a.ttf"] == "endret"
    assert hf.download(tmp_path, fetcher=content.__getitem__) == 0
    assert hf.check(tmp_path)["a.ttf"] == "ok"


def test_network_error_counts_as_error(tmp_path, monkeypatch):
    _fake_files(monkeypatch)

    def boom(url):
        raise OSError("ingen nett")
    assert hf.download(tmp_path, fetcher=boom) == 2


def test_real_list_matches_local_fonts_if_present():
    """Har du fontene lokalt, skal de stemme med sjekksummene i lista."""
    status = hf.check()
    assert "endret" not in status.values()
