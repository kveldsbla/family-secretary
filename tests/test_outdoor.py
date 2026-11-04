"""Tester for ikonene i «Ute i dag» (logic/outdoor.py)."""
import pytest

from logic.outdoor import outdoor_icons


def raw(feels=5.0, precip=0.0, wind=2.0, symbols=("cloudy",)):
    return {"feels_min": feels, "precip": precip, "wind_max": wind, "symbols": list(symbols)}


@pytest.mark.parametrize("feels, emoji, text", [
    (-25, "🧊", "Iskaldt"),
    (-14, "🥶", "Veldig kaldt"),
    (-3, "⛄", "Kaldt"),
    (1, "🧣", "Kjølig"),
    (-0.4, "🧣", "Kjølig"),       # avrundes til 0 – samme trinn som klesrådet
    (10, "🙂", "Mildt"),
    (20, "😎", "Varmt"),
])
def test_feels_like(feels, emoji, text):
    assert outdoor_icons(raw(feels))["foles"] == {"emoji": emoji, "tekst": text}


@pytest.mark.parametrize("precip, symbols, text", [
    (0.0, ["rain"], "Tørt"),            # symbol uten mengde: tørt
    (0.05, ["lightrain"], "Tørt"),
    (0.6, ["lightrain"], "Litt"),       # under regngrensen: ikke regntøy, men litt
    (3.0, ["rain"], "Regn"),
    (2.0, ["sleet"], "Sludd"),
    (0.5, ["lightsnow"], "Snø"),        # snø vises selv i små mengder
    (3.0, ["cloudy"], "Regn"),          # mye nedbør uten symbol: regn
])
def test_precip(precip, symbols, text):
    assert outdoor_icons(raw(precip=precip, symbols=symbols))["nedbor"]["tekst"] == text


@pytest.mark.parametrize("wind, text", [(1, "Rolig"), (4, "Litt vind"), (8, "Litt vind"), (8.5, "Mye vind")])
def test_wind(wind, text):
    assert outdoor_icons(raw(wind=wind))["vind"]["tekst"] == text


def test_missing_wind():
    assert outdoor_icons(raw(wind=None))["vind"] == {"emoji": "", "tekst": ""}


def test_follows_clothing_limits():
    # Endres regngrensen eller vindgrensen i klesrådet, følger ikonene med
    assert outdoor_icons(raw(precip=0.6, symbols=["rain"]), klesrad={"regn_mm": 0.5})["nedbor"]["tekst"] == "Regn"
    assert outdoor_icons(raw(wind=7), klesrad={"vind_ms": 6})["vind"]["tekst"] == "Mye vind"


def test_config_override():
    icons = outdoor_icons(raw(-3), ute={"foles": {"kaldt": ["⛄", "Kaldt ute"]}})
    assert icons["foles"] == {"emoji": "⛄", "tekst": "Kaldt ute"}
    assert outdoor_icons(raw(20), ute={"foles": {"kaldt": ["⛄", "x"]}})["foles"]["emoji"] == "😎"


def test_no_data():
    assert outdoor_icons(None) is None
    assert outdoor_icons({"feels_min": None}) is None
