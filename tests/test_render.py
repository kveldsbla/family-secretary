"""Tester at HTML lages riktig, og at Chrome gir et bilde på nøyaktig 3840 x 2160."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from logic.clothing import clothing_advice
from logic.outdoor import outdoor_icons
from logic.dates import norsk_dato
from logic.day_weather import summarize
from render.render import FONTS, RenderError, _font_face, build_html, find_chrome, png_size, render_png
from sources.weather import demo_forecast, parse_points

OSLO = ZoneInfo("Europe/Oslo")


def _context(vaer=True):
    now = datetime(2026, 11, 2, 6, 0, tzinfo=OSLO)
    points = parse_points(demo_forecast(now.astimezone(timezone.utc)), OSLO)
    summary = summarize(points, now) if vaer else None
    return {"dato": norsk_dato(now.date()),
            "vaer": summary,
            "klar": clothing_advice(summary["outdoor"]["raw"]) if summary else None,
            "ute": outdoor_icons(summary["outdoor"]["raw"]) if summary else None,
            "oppdatert": "06:00", "demo": True}


def test_html_contains_norwegian_text():
    html = build_html("morning.html", _context())
    assert "Mandag 2. november" in html and "Uke 45" in html
    assert "Værdata: MET Norway" in html


def test_html_without_weather_still_renders():
    html = build_html("morning.html", _context(vaer=False))
    assert "Været er ikke tilgjengelig" in html


def test_html_escapes_text():
    ctx = _context()
    ctx["vaer"]["now"]["text"] = "<script>alert(1)</script>"
    html = build_html("morning.html", ctx)
    assert "<script>alert" not in html


def test_render_png_size(tmp_path):
    try:
        chrome = find_chrome()
    except RenderError:
        pytest.skip("Chrome/Chromium er ikke installert")
    html = tmp_path / "test.html"
    html.write_text(build_html("morning.html", _context()), encoding="utf-8")
    png = render_png(html, tmp_path / "test.png", 3840, 2160, chrome)
    assert png_size(png) == (3840, 2160)


def test_emoji_font_is_linked_not_embedded():
    """Emojifonten skal lenkes som lokal fil, ikke bakes inn (den er ca. 25 MB)."""
    font = FONTS / "NotoColorEmoji-Regular.ttf"
    if not font.exists():
        pytest.skip("Noto Color Emoji er ikke lastet ned")
    rule = _font_face(font)
    assert "font-family: 'Noto Color Emoji'" in rule and "file:///" in rule
    assert "base64" not in rule
    html = build_html("morning.html", _context())
    assert len(html) < 3_000_000          # de små fontene bakes inn, emojifonten ikke


def test_html_shows_clothing():
    html = build_html("morning.html", _context())
    assert "Klesråd" in html and "Vinterdress" in html and "Kaldt" in html


def test_html_shows_outdoor_icons():
    html = build_html("morning.html", _context())
    assert "Ute i dag" in html and "føles som" in html and "Veldig kaldt" in html   # demo «vinter»: ca. −10°


def test_html_shows_photo_with_caption():
    ctx = _context()
    ctx["foto"] = {"src": "file:///C:/bilder/hytta.jpg", "tekst": "Hytta <i>i</i> høstferien", "fil": "hytta.jpg"}
    html = build_html("morning.html", ctx)
    assert 'class="foto"' in html and 'src="file:///C:/bilder/hytta.jpg"' in html
    assert "Hytta &lt;i&gt;i&lt;/i&gt; høstferien" in html          # bildeteksten escapes


def test_html_without_photo_has_no_photo_field():
    assert 'class="foto"' not in build_html("morning.html", _context())


# ---------------------------------------------------------------- kveldsfarger (fase 5.2)

def _plan_liv():
    return {"tittel": "I morgen", "flere": 0, "hendelser": [{
        "tid": "17:30", "tittel": "Korps", "navn": "Liv", "felles": False, "heldag": False,
        "ettermiddag": True,
        "personer": [{"navn": "Liv", "farge": "#c96f22", "farge_kveld": "#e28030"}]}]}


def test_day_uses_day_palette():
    html = build_html("morning.html", {**_context(), "plan": _plan_liv(), "kveld": False})
    assert '<html lang="nb">' in html
    assert "background: #c96f22" in html and "background: #e28030" not in html


def test_evening_uses_evening_palette():
    html = build_html("morning.html", {**_context(), "plan": _plan_liv(), "kveld": True})
    assert '<html lang="nb" class="kveld">' in html
    assert ":root.kveld" in html and "--papir:        #2c303b" in html
    assert "background: #e28030" in html and "background: #c96f22" not in html


def test_evening_without_evening_colour_falls_back():
    plan = _plan_liv()
    del plan["hendelser"][0]["personer"][0]["farge_kveld"]
    html = build_html("morning.html", {**_context(), "plan": plan, "kveld": True})
    assert "background: #c96f22" in html
