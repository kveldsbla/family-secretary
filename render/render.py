"""HTML-mal → PNG i 3840 x 2160 med headless Chrome/Chromium.

«Headless» betyr at nettleseren kjører uten vindu: den åpner HTML-filen,
tar et skjermbilde i riktig størrelse og lukker seg.
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
FONTS = HERE / "static" / "fonts"


class RenderError(Exception):
    pass


# ---------------------------------------------------------------- Chrome

def find_chrome(configured: str | None = None) -> str:
    """Finner Chrome (Windows/Mac) eller Chromium (Raspberry Pi)."""
    if configured:
        if Path(configured).exists():
            return configured
        raise RenderError(f"Fant ikke Chrome på stien i config.yaml: {configured}")

    candidates = []
    if sys.platform == "win32":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    for c in candidates:
        if c.exists():
            return str(c)
    raise RenderError("Fant ikke Chrome/Chromium. Sett render.chrome i config.yaml til full sti.")


# ---------------------------------------------------------------- fonter

def _font_face(path: Path) -> str | None:
    """Lager en @font-face-regel med fonten bakt inn, så rendering ikke trenger nett.

    Unntak: emojifonten (ca. 25 MB) bakes ikke inn, men lenkes som lokal fil
    (file:///…). Det holder HTML-en liten og virker fortsatt uten nett.
    """
    name = path.stem.lower()
    if name.startswith("notocoloremoji"):
        return (f"@font-face {{ font-family: 'Noto Color Emoji'; font-style: normal; font-weight: 400; "
                f"src: url('{path.resolve().as_uri()}') format('truetype'); }}")
    if name.startswith("cormorant"):
        family = "Cormorant Garamond"
    elif name.startswith("jost"):
        family = "Jost"
    else:
        return None
    style = "italic" if "italic" in name else "normal"
    if "variable" in name:
        weight = "300 700"
    else:
        weight = "400"
        for word, w in (("light", "300"), ("medium", "500"), ("semibold", "600"), ("bold", "700")):
            if word in name:
                weight = w  # «semibold» overstyrer «bold» fordi den kommer først i lista
                break
    fmt = {".ttf": "truetype", ".otf": "opentype", ".woff2": "woff2", ".woff": "woff"}[path.suffix.lower()]
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return (f"@font-face {{ font-family: '{family}'; font-style: {style}; font-weight: {weight}; "
            f"src: url(data:font/{path.suffix[1:].lower()};base64,{data}) format('{fmt}'); }}")


def font_css(folder: Path = FONTS) -> str:
    rules = []
    if folder.exists():
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() in (".ttf", ".otf", ".woff2", ".woff"):
                rule = _font_face(p)
                if rule:
                    rules.append(rule)
    if not rules:
        log.info("Ingen fonter i render/static/fonts – bruker systemfonter som reserve")
    return "\n".join(rules)


# ---------------------------------------------------------------- HTML og PNG

def build_html(template_name: str, context: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))  # tekst fra data escapes automatisk
    return env.get_template(template_name).render(font_css=font_css(), **context)


def render_png(html_file: Path, out_png: Path, width: int, height: int,
               chrome: str, timeout: int = 90) -> Path:
    """Tar skjermbilde av html_file med headless Chrome og sjekker størrelsen."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    if out_png.exists():
        out_png.unlink()
    with tempfile.TemporaryDirectory(prefix="familiehub-chrome-") as profile:
        args = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--mute-audio",
            "--force-device-scale-factor=1",
            f"--window-size={width},{height}",
            f"--user-data-dir={profile}",   # egen profil: forstyrrer ikke Chrome du har åpen
            "--virtual-time-budget=3000",    # gi fonter tid til å laste
            f"--screenshot={out_png}",
            html_file.resolve().as_uri(),
        ]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            log.warning("Kjører som root – Chrome krever da --no-sandbox. Bruk vanlig bruker på Pi-en.")
            args.insert(1, "--no-sandbox")
        try:
            # Argumentliste uten shell: ingen tegn i stier kan tolkes som kommandoer.
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RenderError(f"Chrome brukte mer enn {timeout} s")
    if not out_png.exists():
        raise RenderError(f"Chrome laget ikke bildet. Feilmelding:\n{proc.stderr[-1500:]}")
    w, h = png_size(out_png)
    if (w, h) != (width, height):
        raise RenderError(f"Bildet ble {w} x {h}, forventet {width} x {height}")
    return out_png


def png_size(path: Path) -> tuple[int, int]:
    """Leser bredde og høyde rett fra PNG-filens hode (ingen ekstra bibliotek)."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise RenderError(f"{path.name} er ikke en PNG-fil")
    return struct.unpack(">II", head[16:24])
