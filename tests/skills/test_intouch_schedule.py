"""Schedule parsing and book-on window logic of the custom InTouch skill (no phone needed)."""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "android" / "intouch" / "scripts"


@pytest.fixture(scope="module")
def intouch():
    sys.path.insert(0, str(ROOT / "skills" / "android" / "phone-control" / "scripts"))
    spec = importlib.util.spec_from_file_location("intouch_skill", SCRIPTS / "intouch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TODAY = dt.date(2026, 11, 19)


def test_time_range_with_long_date(intouch):
    shifts = intouch.parse_shifts(["Thursday 20 November 2026", "Site A", "08:00 - 16:00"], today=TODAY)
    assert shifts == [{"start": "2026-11-20T08:00", "end": "2026-11-20T16:00",
                       "raw": "08:00 - 16:00", "source": "parsed"}]


def test_overnight_shift_ends_next_day(intouch):
    (s,) = intouch.parse_shifts(["21/11/2026 22:00 - 06:00"], today=TODAY)
    assert s["start"] == "2026-11-21T22:00" and s["end"] == "2026-11-22T06:00"


def test_am_pm_and_undated_time_is_today(intouch):
    (s,) = intouch.parse_shifts(["7:30 am to 3:30 pm"], today=TODAY)
    assert s["start"] == "2026-11-19T07:30" and s["end"] == "2026-11-19T15:30"


def test_no_shift_text_yields_nothing(intouch):
    assert intouch.parse_shifts(["You don't have any shifts right now.", "REFRESH"], today=TODAY) == []


def test_calendar_day_labels_alone_are_not_shifts(intouch):
    assert intouch.parse_shifts(["Monday 23 November 2026", "Tuesday 24 November 2026"], today=TODAY) == []


def test_window_is_15_before_to_15_after(intouch):
    opens, closes = intouch.window({"start": "2026-11-20T08:00"}, intouch.DEFAULTS)
    assert opens == dt.datetime(2026, 11, 20, 7, 45)
    assert closes == dt.datetime(2026, 11, 20, 8, 15)


def test_merge_keeps_manual_and_replaces_parsed(intouch, tmp_path, monkeypatch):
    monkeypatch.setattr(intouch, "SCHEDULE_FILE", tmp_path / "schedule.json")
    future = (dt.datetime.now() + dt.timedelta(days=2)).replace(second=0, microsecond=0)
    manual = {"start": future.isoformat(timespec="minutes"), "end": None, "raw": "", "source": "manual"}
    stale = {"start": (future + dt.timedelta(hours=3)).isoformat(timespec="minutes"), "end": None,
             "raw": "", "source": "parsed"}
    intouch.save_json(intouch.SCHEDULE_FILE, [manual, stale])
    fresh = {"start": (future + dt.timedelta(days=1)).isoformat(timespec="minutes"), "end": None,
             "raw": "", "source": "parsed"}
    merged = intouch.merge_schedule([fresh], replace_source=True)
    assert [s["start"] for s in merged] == [manual["start"], fresh["start"]]


def test_labels_hit_matches_whole_words_only(intouch):
    elems = [{"text": "Book on", "desc": "", "clickable": True},
             {"text": "Facebook online", "desc": "", "clickable": True}]
    assert intouch._labels_hit(elems, ["book on"])["text"] == "Book on"
    assert intouch._labels_hit(elems[1:], ["book on"]) is None


def test_redact_hides_the_password(intouch):
    assert intouch._redact("Login failed for hunter2!", "hunter2") == "Login failed for [redacted]!"
    assert intouch._redact("Login failed", None) == "Login failed"


def test_login_refuses_after_a_failed_attempt(intouch, tmp_path, monkeypatch):
    monkeypatch.setattr(intouch, "LOGIN_BLOCK_FILE", tmp_path / "login_blocked")
    (tmp_path / "login_blocked").write_text("x")
    with pytest.raises(intouch.PhoneError, match="paused"):
        intouch.login(intouch.DEFAULTS, [])


def test_login_without_saved_password_asks_user(intouch, tmp_path, monkeypatch):
    monkeypatch.setattr(intouch, "LOGIN_BLOCK_FILE", tmp_path / "login_blocked")
    monkeypatch.setattr(intouch, "SECRET_FILE", tmp_path / "password")
    with pytest.raises(intouch.PhoneError, match="set-password"):
        intouch.login(intouch.DEFAULTS, [])


def test_empty_app_has_no_shift_content(intouch):
    real_empty_read = ["You don't have any shifts right now.", "REFRESH", "Go back to the previous month",
                       "Go forward to the next month", "November 2026", "Today", "Monday 26 October 2026",
                       "Thursday 19 November 2026", "Monday", "Tuesday", "19", "REQUEST HOLIDAY"]
    assert intouch.has_shift_content(real_empty_read) is False


def test_calendar_with_a_shift_marker_has_content(intouch):
    assert intouch.has_shift_content(["November 2026", "Friday 20 November 2026", "Day shift - Site A"]) is True


def test_type_command_types_each_character_exactly(intouch):
    cmd = intouch._type_command("a b%s'!")
    assert cmd == ("input text a; input keyevent 62; input text b; input text %; input text s; "
                   "input text ''\"'\"''; input text '!'")


def test_phone_blocklist_refuses_logout():
    sys.path.insert(0, str(ROOT / "skills" / "android" / "phone-control" / "scripts"))
    import phone

    with pytest.raises(phone.PhoneError):
        phone.check_allowed("LOGOUT", force=False)
    phone.check_allowed("BOOK ON", force=False)
