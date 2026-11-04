"""Tester for klesreglene (logic/clothing.py). Ingen nett nødvendig."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from logic.clothing import clothing_advice, load_rules, precip_types, summary_line, temperature_step
from logic.day_weather import summarize
from sources.weather import demo_forecast, parse_points

OSLO = ZoneInfo("Europe/Oslo")
LIMITS = load_rules(None)["grenser"]


def raw(feels, precip=0.0, wind=2.0, symbols=("cloudy",)):
    return {"feels_min": feels, "precip": precip, "wind_max": wind, "symbols": list(symbols)}


# ---------------------------------------------------------------- temperaturtrinn

@pytest.mark.parametrize("feels, step", [
    (-25.0, "iskaldt"),
    (-20.6, "iskaldt"),        # avrundes til −21
    (-20.0, "veldig_kaldt"),   # «−20 til −11» starter på −20
    (-15.0, "veldig_kaldt"),
    (-10.6, "veldig_kaldt"),   # avrundes til −11
    (-10.0, "kaldt"),          # «−10 til 0» starter på −10
    (-0.6, "kaldt"),           # −1
    (-0.4, "kjolig"),          # avrundes til 0 – skjermen viser «0°»
    (7.4, "kjolig"),
    (8.0, "mildt"),
    (15.0, "mildt"),
    (15.6, "varmt"),           # 16
    (25.0, "varmt"),
])
def test_temperature_step(feels, step):
    assert temperature_step(feels, LIMITS) == step


def test_very_cold_uses_cold_figure_but_thicker_list():
    a = clothing_advice(raw(-14))
    assert a["kategori"] == "kaldt" and a["trinn"] == "veldig_kaldt"
    assert "Tykke votter" in a["huskeliste"] and "Ullfleece" in a["huskeliste"]
    assert a["figur"] == ["🥶", "⛄"]


# ---------------------------------------------------------------- nedbør, vind og sol

def test_precip_types():
    assert precip_types(["lightrain", "heavysnowshowers_day", "sleet", None, "cloudy"]) == {"regn", "sno", "sludd"}
    assert precip_types([]) == set()


def test_rain_over_threshold_gives_rain_gear():
    a = clothing_advice(raw(5, precip=3.2, symbols=["rain"] * 7))
    assert a["regn"] and "Regntøy" in a["huskeliste"] and "Støvler" in a["huskeliste"]
    assert a["figur"] == ["🧥", "🧤", "☔", "👢"]


def test_little_rain_is_ignored():
    a = clothing_advice(raw(5, precip=0.8, symbols=["lightrain"]))
    assert not a["regn"] and "Regntøy" not in a["huskeliste"]


def test_rain_when_cold_gives_winter_variant():
    a = clothing_advice(raw(-3, precip=2.0, symbols=["rain"]))
    assert "Vanntett ytterst" in a["huskeliste"] and "Regntøy" not in a["huskeliste"]


def test_sleet_gives_waterproof_and_extra_mittens_once():
    a = clothing_advice(raw(-2, precip=4.0, symbols=["rain", "sleet"]))
    assert a["huskeliste"].count("Vanntett ytterst") == 1     # ingen dubletter
    assert "Ekstra votter i sekken" in a["huskeliste"]
    assert a["regn"] and not a["sno"]


def test_snow():
    a = clothing_advice(raw(-6, precip=2.0, symbols=["lightsnow"] * 7))
    assert a["sno"] and not a["regn"]
    assert a["figur"] == ["🥶", "⛄", "❄️"]
    assert "Ekstra votter i sekken" in a["huskeliste"]


def test_wind():
    a = clothing_advice(raw(10, wind=9.5))
    assert a["vind"] and "Vindtett ytterst" in a["huskeliste"]
    assert not clothing_advice(raw(10, wind=None))["vind"]   # mangler vind: ingen feil


def test_sun_hat_only_when_warm_and_sunny():
    assert "Solhatt" in clothing_advice(raw(20, symbols=["clearsky_day"]))["huskeliste"]
    assert "Solhatt" not in clothing_advice(raw(20, symbols=["cloudy"]))["huskeliste"]
    assert "Solhatt" not in clothing_advice(raw(5, symbols=["clearsky_day"]))["huskeliste"]


# ---------------------------------------------------------------- config og feiltilfeller

def test_config_overrides_only_what_is_given():
    a = clothing_advice(raw(-5), {"figur": {"kaldt": ["🧊"]}, "regn_mm": 0.5})
    assert a["figur"] == ["🧊"]
    rules = load_rules({"figur": {"kaldt": ["🧊"]}})
    assert rules["figur"]["varmt"] == ["😎", "👕"]          # resten er uendret


def test_no_data_gives_none():
    assert clothing_advice(None) is None
    assert clothing_advice({"feels_min": None}) is None
    assert summary_line(None) == "ingen værdata for skoletiden"


def test_summary_line_has_no_emoji():
    line = summary_line(clothing_advice(raw(-6, precip=2.0, symbols=["snow"])))
    assert line.startswith("kaldt + sno – Ull innerst")
    assert all(ord(c) < 0x2600 for c in line)   # tankestrek (U+2013) er lov, emojier ikke


# ---------------------------------------------------------------- hele kjeden med demovær

@pytest.mark.parametrize("scenario, category, rain, snow", [
    ("vinter", "kaldt", False, True),
    ("regn", "kjolig", True, False),
    ("sol", "varmt", False, False),
])
def test_demo_scenarios(scenario, category, rain, snow):
    now = datetime(2026, 11, 2, 6, 0, tzinfo=OSLO)
    points = parse_points(demo_forecast(now.astimezone(timezone.utc), scenario), OSLO)
    a = clothing_advice(summarize(points, now)["outdoor"]["raw"])
    assert (a["kategori"], a["regn"], a["sno"]) == (category, rain, snow)



def test_ice_cold_has_own_list_but_cold_figure():
    a = clothing_advice(raw(-24))
    assert a["trinn"] == "iskaldt" and a["kategori"] == "kaldt"
    assert "Balaklava" in a["huskeliste"] and "Kuldekrem" in a["huskeliste"]
