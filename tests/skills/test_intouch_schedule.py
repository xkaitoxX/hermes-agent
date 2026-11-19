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


def _el(text, y, clickable=False):
    return {"text": text, "desc": "", "clickable": clickable, "center": [600, y], "cls": "TextView", "pkg": ""}


def test_two_shifts_same_day_each_gets_its_own_button(intouch):
    elems = [_el("08:00 - 12:00", 600), _el("BOOK ON", 800, True),
             _el("16:00 - 20:00", 1300), _el("BOOK ON", 1500, True)]
    first = intouch._shift_anchor(elems, dt.datetime(2026, 11, 20, 8, 0))
    second = intouch._shift_anchor(elems, dt.datetime(2026, 11, 20, 16, 0))
    buttons = intouch._all_hits(elems, intouch.DEFAULTS["book_on_labels"])
    assert intouch._nearest(buttons, first)["center"][1] == 800
    assert intouch._nearest(buttons, second)["center"][1] == 1500


def test_time_anchor_does_not_match_inside_other_times(intouch):
    elems = [_el("18:00 - 22:00", 600)]
    assert intouch._shift_anchor(elems, dt.datetime(2026, 11, 20, 8, 0)) is None  # 8:00 inside 18:00


def test_twelve_hour_times_are_recognised(intouch):
    elems = [_el("Shift 4:30 pm", 600)]
    assert intouch._shift_anchor(elems, dt.datetime(2026, 11, 20, 16, 30)) is not None


class _Clock:
    def __init__(self, start):
        self.now = start


@pytest.fixture
def service(intouch, tmp_path, monkeypatch):
    monkeypatch.setattr(intouch, "STATE_DIR", tmp_path)
    monkeypatch.setattr(intouch, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(intouch, "SCHEDULE_FILE", tmp_path / "schedule.json")
    monkeypatch.setattr(intouch, "LOG_FILE", tmp_path / "log")
    monkeypatch.setenv("INTOUCH_VERBOSE", "0")
    sent = []
    monkeypatch.setattr(intouch, "notify", lambda title, text, nid="": sent.append(title))
    svc = intouch._Service()
    monkeypatch.setattr(svc, "link", lambda cfg, force=False: True)
    return svc, sent


def test_retries_every_two_minutes_until_booked(intouch, service, monkeypatch):
    svc, sent = service
    shift = {"start": "2026-11-20T08:00", "end": "2026-11-20T12:00"}
    results = iter([("not_available", "not on site"), ("not_available", "not on site"), ("booked", "ok")])
    calls = []
    monkeypatch.setattr(intouch, "book_on_once", lambda cfg, shift=None: (calls.append(shift["start"]), next(results))[1])
    t = dt.datetime(2026, 11, 20, 7, 44)
    for _ in range(20):  # 07:44 .. 07:53:30 in 30 s ticks
        svc.handle_shift(shift, intouch.DEFAULTS, t)
        t += dt.timedelta(seconds=30)
    assert len(calls) == 3                       # 07:45, 07:47, 07:49 -- then booked, stops
    assert svc.state["shifts"][shift["start"]]["status"] == "booked"
    assert sent == ["InTouch book-on window open", "Booked on ✔"]


def test_window_closing_without_book_on_notifies(intouch, service, monkeypatch):
    svc, sent = service
    shift = {"start": "2026-11-20T08:00", "end": None}
    monkeypatch.setattr(intouch, "book_on_once", lambda cfg, shift=None: ("not_available", "not on site"))
    t = dt.datetime(2026, 11, 20, 7, 45)
    while t <= dt.datetime(2026, 11, 20, 8, 16):
        svc.handle_shift(shift, intouch.DEFAULTS, t)
        t += dt.timedelta(seconds=30)
    st = svc.state["shifts"][shift["start"]]
    assert st["status"] == "missed" and st["attempts"] == 16   # every 2 min across the 30-min window
    assert sent[-1] == "NOT booked on ✖"


def test_two_shifts_in_one_day_are_booked_independently(intouch, service, monkeypatch):
    svc, sent = service
    a = {"start": "2026-11-20T08:00", "end": "2026-11-20T12:00"}
    b = {"start": "2026-11-20T16:00", "end": "2026-11-20T20:00"}
    booked_for = []
    monkeypatch.setattr(intouch, "book_on_once",
                        lambda cfg, shift=None: (booked_for.append(shift["start"]), ("booked", "ok"))[1])
    for t in (dt.datetime(2026, 11, 20, 7, 50), dt.datetime(2026, 11, 20, 15, 50)):
        for s in (a, b):
            svc.handle_shift(s, intouch.DEFAULTS, t)
    assert booked_for == [a["start"], b["start"]]
    assert all(svc.state["shifts"][s["start"]]["status"] == "booked" for s in (a, b))


def test_a_crashing_tick_does_not_stop_the_service(intouch, service, monkeypatch):
    svc, _ = service
    monkeypatch.setattr(svc, "tick", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    ticks = []
    monkeypatch.setattr(intouch.time, "sleep", lambda s: (ticks.append(s), len(ticks) > 2 and (_ for _ in ()).throw(SystemExit))[1])
    monkeypatch.setattr(intouch, "_Service", lambda: svc)
    monkeypatch.setattr(intouch, "PID_FILE", intouch.STATE_DIR / "pid")
    with pytest.raises(SystemExit):
        intouch.daemon(intouch.DEFAULTS)
    assert len(ticks) == 3  # kept looping after each error


def test_fingerprint_prompt_picks_the_real_cancel_button(intouch):
    # Exact shape of InTouch's prompt as dumped from the phone.
    elems = [
        {"text": "", "desc": "Cancel", "clickable": True, "bounds": [0, 0, 1216, 2688], "center": [608, 1344]},
        {"text": "", "desc": "", "clickable": True, "bounds": [0, 907, 1216, 2688], "center": [608, 1797]},
        {"text": "Place your finger on the device fingerprint reader to login", "desc": "", "clickable": False,
         "bounds": [13, 1643, 1203, 1718], "center": [608, 1680]},
        {"text": "CANCEL", "desc": "", "clickable": True, "bounds": [364, 2409, 852, 2539], "center": [608, 2474]},
    ]
    assert intouch._labels_hit(elems, ["cancel"])["center"] == [608, 2474]


def test_phone_blocklist_refuses_logout():
    sys.path.insert(0, str(ROOT / "skills" / "android" / "phone-control" / "scripts"))
    import phone

    with pytest.raises(phone.PhoneError):
        phone.check_allowed("LOGOUT", force=False)
    phone.check_allowed("BOOK ON", force=False)
