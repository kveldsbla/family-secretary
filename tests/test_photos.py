"""Tester for dagens familiefoto (sources/photos.py)."""
from datetime import date

from sources.photos import caption, list_photos, photo_of_the_day


def _touch(folder, *names):
    for n in names:
        (folder / n).write_bytes(b"x")


def test_missing_or_empty_folder_gives_none(tmp_path):
    assert photo_of_the_day(tmp_path / "finnes-ikke", date(2026, 11, 3)) is None
    assert photo_of_the_day(tmp_path, date(2026, 11, 3)) is None


def test_only_image_files_are_used(tmp_path):
    _touch(tmp_path, "b.JPG", "a.png", "c.webp", "LESMEG.md", ".skjult.jpg", "notat.txt")
    (tmp_path / "undermappe.jpg").mkdir()
    assert [p.name for p in list_photos(tmp_path)] == ["a.png", "b.JPG", "c.webp"]


def test_one_photo_per_day_in_rotation(tmp_path):
    _touch(tmp_path, "a.jpg", "b.jpg", "c.jpg")
    days = [date(2026, 11, d) for d in (3, 4, 5, 6)]
    picked = [photo_of_the_day(tmp_path, d)["fil"] for d in days]
    assert len(set(picked[:3])) == 3 and picked[3] == picked[0]          # alle tre før det gjentas
    assert photo_of_the_day(tmp_path, days[0]) == photo_of_the_day(tmp_path, days[0])   # samme hele dagen


def test_photo_is_linked_as_local_file(tmp_path):
    _touch(tmp_path, "Hjemme, oktober 2026.jpg")
    p = photo_of_the_day(tmp_path, date(2026, 11, 3))
    assert p["src"].startswith("file:///") and p["tekst"] == "Hjemme, oktober 2026"


def test_caption_from_file_name():
    from pathlib import Path
    assert caption(Path("Hytta_i_høstferien.jpg")) == "Hytta i høstferien"
    assert caption(Path("Påskefjellet 2025.jpg")) == "Påskefjellet 2025"     # P + bokstav er et vanlig navn
    for camera in ("IMG_1234.jpg", "DSC0042.JPG", "_DSC0042.jpg", "P6241182.JPG", "GOPR0012.jpg",
                   "PXL_20261031_101010.jpg", "20261031_101010.jpg"):
        assert caption(Path(camera)) == ""
