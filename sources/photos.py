"""Dagens familiefoto fra en mappe på maskinen (fase 5).

Legg bildene i mappen «bilder» i prosjektet (eller mappen som står under
«foto: mappe:» i config.yaml). Ett bilde per dag, på rundgang i alfabetisk
rekkefølge, så samme bilde vises hele dagen.

Filnavnet blir bildeteksten: «Hjemme, oktober 2026.jpg» → «Hjemme, oktober 2026».
Navn fra kamera og telefon (IMG_1234, DSC0042, P6241182, PXL_2026…, 20261031_…) gir ingen tekst.

Personvern: fotoet lenkes som lokal fil i HTML-en og blir en del av skjermbildet.
TV-en får bare det nye skjermbildet, ikke fotofilen, så EXIF (GPS, kamera) følger ikke med.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
CAMERA_NAME = re.compile(r"^(_?img|_?dsc|dji|gopr|pxl|mvimg|photo|screenshot|p\d{5,}|\d)", re.IGNORECASE)


def list_photos(folder: Path) -> list[Path]:
    """Alle bildefiler i mappen (ikke undermapper), sortert etter navn."""
    if not folder.is_dir():
        return []
    photos = [p for p in folder.iterdir()
              if p.is_file() and p.suffix.lower() in SUFFIXES and not p.name.startswith(".")]
    return sorted(photos, key=lambda p: p.name.lower())


def caption(path: Path) -> str:
    """Bildetekst fra filnavnet, eller tom tekst for kameranavn."""
    stem = path.stem.replace("_", " ").strip()
    return "" if CAMERA_NAME.match(stem) else stem


def photo_of_the_day(folder: Path, day: date) -> dict | None:
    """Velger dagens foto. None når mappen mangler eller er tom."""
    photos = list_photos(folder)
    if not photos:
        return None
    p = photos[day.toordinal() % len(photos)]
    return {"src": p.resolve().as_uri(), "tekst": caption(p), "fil": p.name}


if __name__ == "__main__":   # prøv: python -m sources.photos
    import sys
    root = Path(__file__).resolve().parent.parent
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "bilder"
    found = list_photos(folder)
    print(f"{len(found)} bilder i {folder}")
    today = photo_of_the_day(folder, date.today())
    if today:
        print(f"I dag: {today['fil']}  (tekst: «{today['tekst']}»)")
