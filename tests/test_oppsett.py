"""Tester for oppsett.py – uten TV og uten nett."""
from pathlib import Path

import pytest
import yaml

import oppsett as o
from logic.day_plan import load_persons


def scripted(*answers):
    it = iter(answers)
    return lambda prompt="": next(it)


class NoFonts:
    """Later som fontene allerede finnes, så ingen nedlasting spørres om."""
    @staticmethod
    def check():
        return {"x.ttf": "ok"}


def test_parse_coord_accepts_comma_and_rounds():
    assert o.parse_coord("59,91234", -90, 90) == 59.9123
    with pytest.raises(ValueError):
        o.parse_coord("91", -90, 90)
    with pytest.raises(ValueError):
        o.parse_coord("nord", -90, 90)


@pytest.mark.parametrize("bad", ["", "uten-krøllalfa", "din.epost@eksempel.no", "a b@c.no"])
def test_parse_email_rejects(bad):
    with pytest.raises(ValueError):
        o.parse_email(bad)


def test_parse_ip():
    assert o.parse_ip("192.168.1.50") == "192.168.1.50"
    with pytest.raises(ValueError):
        o.parse_ip("192.168.1")


def test_default_mark_skips_used_letters():
    assert o.default_mark("Liv", set()) == "L"
    assert o.default_mark("Lars", {"L"}) == "A"


def test_parse_mark_rejects_duplicates_and_separators():
    assert o.parse_mark("l", set()) == "L"
    with pytest.raises(ValueError):
        o.parse_mark("L", {"L"})
    with pytest.raises(ValueError):
        o.parse_mark("E&L", set())


def test_ask_repeats_until_valid(capsys):
    assert o.ask("Tall", None, o.parse_count, scripted("x", "0", "3")) == 3
    assert capsys.readouterr().out.count("!") == 2


def test_config_text_is_valid_and_readable_by_the_program():
    persons = [{"navn": "Eva", "merke": "E"}, {"navn": "Øyvind «Øy»", "merke": "Ø", "barn": True}]
    cfg = yaml.safe_load(o.config_text(59.9133, 10.7389, "a@b.no", "192.168.1.50", persons))
    assert cfg["sted"] == {"lat": 59.9133, "lon": 10.7389}
    assert cfg["yr"]["user_agent"] == "family-secretary/0.1 a@b.no"
    assert cfg["tv"]["ip"] == "192.168.1.50"
    loaded = load_persons(cfg["personer"])
    assert [p.navn for p in loaded] == ["Eva", "Øyvind «Øy»"]
    assert loaded[0].farge == "#6d5a4a" and loaded[1].farge_kveld == "#6aa5e0"
    assert [p.barn for p in loaded] == [False, True]


def test_colours_repeat_after_five_people():
    persons = [{"navn": f"P{i}", "merke": chr(65 + i)} for i in range(6)]
    cfg = yaml.safe_load(o.config_text(1, 1, "a@b.no", "10.0.0.2", persons))
    assert cfg["personer"][5]["farge"] == cfg["personer"][0]["farge"]


def test_write_env_keeps_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANNET=1\nFAMILIEKALENDER_ICS=gammel\n", encoding="utf-8")
    o.write_env(env, "FAMILIEKALENDER_ICS", "https://ny")
    assert env.read_text(encoding="utf-8").splitlines() == ["ANNET=1", "FAMILIEKALENDER_ICS=https://ny"]


def test_full_run_writes_files(tmp_path):
    (tmp_path / "skolerute.example.yaml").write_text("gjelder_til: 2028-08-20\nfridager: []\n", encoding="utf-8")
    answers = scripted("59,9", "10,7", "a@b.no", "192.168.1.50",
                       "2", "Eva", "", "n", "Liv", "", "j",
                       "https://p01.icloud.com/x.ics", "j")
    assert o.run(tmp_path, inp=answers, reach=lambda ip: False, fonts=NoFonts) == 0
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert [(p["merke"], p.get("barn", False)) for p in cfg["personer"]] == [("E", False), ("L", True)]
    assert (tmp_path / ".env").read_text(encoding="utf-8").strip() == "FAMILIEKALENDER_ICS=https://p01.icloud.com/x.ics"
    assert (tmp_path / "skolerute.yaml").exists()
    assert (tmp_path / "bilder").is_dir()


def test_existing_config_is_kept_unless_confirmed(tmp_path):
    (tmp_path / "config.yaml").write_text("min: config\n", encoding="utf-8")
    assert o.run(tmp_path, inp=scripted("n"), reach=lambda ip: False, fonts=NoFonts) == 0
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == "min: config\n"


def test_new_config_backs_up_the_old_one(tmp_path):
    (tmp_path / "config.yaml").write_text("min: config\n", encoding="utf-8")
    answers = scripted("j", "60", "10", "a@b.no", "10.0.0.2", "1", "Eva", "", "n", "")
    o.run(tmp_path, inp=answers, reach=lambda ip: False, fonts=NoFonts)
    assert (tmp_path / "config.yaml.bak").read_text(encoding="utf-8") == "min: config\n"
    assert "Eva" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_pairing_is_offered_when_tv_answers(tmp_path):
    calls = []
    answers = scripted("60", "10", "a@b.no", "10.0.0.2", "1", "Eva", "", "n", "", "j", "")
    o.run(tmp_path, inp=answers, reach=lambda ip: True, fonts=NoFonts,
          pair=lambda ip, data: calls.append((ip, data)) or "Koblet til.")
    assert calls == [("10.0.0.2", tmp_path / "data")]


def test_py_cmd_points_to_the_venv(tmp_path):
    exe = tmp_path / ".venv" / "Scripts" / "python.exe"
    assert o.py_cmd(tmp_path, str(exe)) == str(Path(".venv") / "Scripts" / "python")
    assert o.py_cmd(tmp_path, "/usr/bin/python3") == "python"
