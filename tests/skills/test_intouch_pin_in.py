"""InTouch book-on as it really works (owner's screen recording, 24 Nov 2026):

    Shift List card -> Shift Details [CANCEL | PIN IN] -> "You are about to Pin In to confirm
    attendance. Is this correct?" [NO | YES] -> "Acquiring GPS" -> On Site screen, or
    "You can only book on when you are on site" [TRY AGAIN | CANCEL].

Plus what went wrong that day: BACK closing the app, the On Site screen not being recognised, the
password box's text reaching the audit log, and a link error escaping the service loop.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "android" / "intouch" / "scripts"
PKG = "com.mitie.InTouch"
SECRET = "Zx9!secretPW"
START = dt.datetime(2026, 11, 24, 14, 0)


@pytest.fixture(scope="module")
def intouch():
    sys.path.insert(0, str(ROOT / "skills" / "android" / "phone-control" / "scripts"))
    spec = importlib.util.spec_from_file_location("intouch_pin_in", SCRIPTS / "intouch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _n(text, bounds, clickable=False, cls="TextView", desc="", pkg=PKG, password=False):
    x1, y1, x2, y2 = bounds
    return {"text": text, "desc": desc, "cls": cls, "pkg": pkg, "clickable": clickable, "password": password,
            "bounds": list(bounds), "center": [(x1 + x2) // 2, (y1 + y2) // 2], "id": ""}


def LIST(status="Scheduled"):
    return [_n("Shift List", (481, 153, 788, 244)), _n("", (0, 289, 244, 445), desc="Selected "),
            _n("TODAY", (49, 612, 1216, 685)), _n("", (0, 685, 1216, 1630), clickable=True, cls="ViewGroup"),
            _n("Short Term Events", (128, 754, 1059, 946)), _n(status, (128, 1292, 1059, 1365)),
            _n("Tue 14:00 - 20:00", (200, 1398, 706, 1474)), _n("5 hr, 15 min", (866, 1398, 1100, 1474))]


def DETAILS(date="Tue 24 November 2026", window="14:00 - 20:00"):
    return [_n("Shift Details", (70, 150, 490, 240)), _n("CANCEL", (918, 150, 1165, 240), clickable=True),
            _n("Date:", (66, 360, 300, 420)), _n(date, (66, 450, 900, 540)),
            _n("Location:", (66, 620, 300, 680)), _n("1 Example Street", (66, 710, 700, 800)),
            _n("Shift window:", (66, 1010, 420, 1070)), _n(window, (66, 1080, 560, 1160)),
            _n("Duration:", (660, 1010, 900, 1070)), _n("5 hr, 15 min", (660, 1080, 1060, 1160)),
            _n("PIN IN", (65, 1838, 1151, 2000), clickable=True)]


CONFIRM = [_n("You are about to Pin In to confirm attendance. Is this correct?", (160, 1240, 1060, 1380)),
           _n("NO", (740, 1420, 830, 1520), clickable=True, cls="Button"),
           _n("YES", (935, 1420, 1050, 1520), clickable=True, cls="Button")]
GPS = [_n("Acquiring GPS", (400, 1300, 820, 1380))]
REFUSED = [_n("You can only book on when you are on site", (160, 1140, 1060, 1290)),
           _n("In order to proceed, you'll need to verify your location.", (160, 1320, 1060, 1470)),
           _n("TRY AGAIN", (480, 1520, 800, 1620), clickable=True, cls="Button"),
           _n("CANCEL", (840, 1520, 1075, 1620), clickable=True, cls="Button")]
ON_SITE = [_n("", (40, 130, 190, 260), clickable=True, cls="ImageView"),            # back arrow
           _n("On Site", (510, 150, 760, 240)),
           _n("", (1046, 126, 1192, 270), clickable=True, cls="ImageView"),          # SOS (no label!)
           _n("", (0, 289, 244, 445), desc="Selected "),
           _n("Short Term Events", (50, 500, 700, 580)), _n("TIME ON SITE", (170, 1050, 470, 1100)),
           _n("-4 min", (220, 1150, 420, 1220)), _n("DURATION", (780, 1050, 1020, 1100)),
           _n("CHECK CALL", (50, 1340, 1168, 1502), clickable=True),
           _n("Call Sam Manager", (50, 1578, 1168, 1750), clickable=True)]
LOGIN = [_n("Login", (480, 150, 740, 240)),
         _n("someone@example.com", (60, 400, 1150, 500), cls="EditText", clickable=True),
         _n(SECRET, (60, 560, 1150, 660), cls="EditText", clickable=True),          # plain text, not flagged
         _n("LOGIN", (60, 760, 1150, 900), clickable=True, cls="Button"),
         _n("Forgotten Password?", (380, 960, 840, 1020), clickable=True)]

PIN_IN_AT = (608, 1919)
YES_AT = (992, 1470)
TRY_AGAIN_AT = (640, 1570)
DIALOG_CANCEL_AT = (957, 1570)
HEADER_CANCEL_AT = (959, 195)           # the left end of the word, well away from SOS
SOS_AT = (1119, 198)
CARD_AT = (608, 1157)


@pytest.fixture
def env(intouch, tmp_path, monkeypatch):
    """A fake phone: `screens` are shown one after another (the last one stays), taps and shell
    commands are recorded."""
    monkeypatch.setattr(intouch, "STATE_DIR", tmp_path)
    monkeypatch.setattr(intouch, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(intouch, "SCHEDULE_FILE", tmp_path / "schedule.json")
    monkeypatch.setattr(intouch, "LOG_FILE", tmp_path / "log")
    monkeypatch.setattr(intouch, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(intouch, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(intouch, "SECRET_FILE", tmp_path / "password")
    monkeypatch.setattr(intouch, "LOGIN_BLOCK_FILE", tmp_path / "login_blocked")
    monkeypatch.setenv("INTOUCH_VERBOSE", "0")
    sim = {"screens": [], "taps": [], "shell": [], "sent": [], "opened": 0}
    monkeypatch.setattr(intouch, "notify", lambda title, text, nid="": sim["sent"].append(title))
    monkeypatch.setattr(intouch.time, "sleep", lambda s: None)
    monkeypatch.setattr(intouch.phone, "tap_xy", lambda x, y: sim["taps"].append((x, y)))
    monkeypatch.setattr(intouch.phone, "shell", lambda cmd, timeout=30: (sim["shell"].append(cmd), "")[1])
    monkeypatch.setattr(intouch.phone, "open_app", lambda pkg: sim.__setitem__("opened", sim["opened"] + 1))
    monkeypatch.setattr(intouch.phone, "screen_state", lambda: {"awake": True, "locked": False})
    monkeypatch.setattr(intouch.phone, "foreground", lambda: PKG + "/.MainActivity")
    monkeypatch.setattr(intouch.phone, "keyboard_shown", lambda: False)
    monkeypatch.setattr(intouch, "screen",
                        lambda: sim["screens"].pop(0) if len(sim["screens"]) > 1 else sim["screens"][0])
    return sim


def _back_presses(sim):
    return [c for c in sim["shell"] if c.strip() == "input keyevent 4"]


def _go(intouch, sim, screens, cfg=None):
    sim["screens"] = list(screens)
    lst = LIST()
    return intouch._start_by_card(cfg or intouch.DEFAULTS, lst, lst[6], START, False)


# ---------------------------------------------------------------- the pin-in flow
def test_pin_in_yes_gps_then_on_site_is_booked(intouch, env):
    out, detail = _go(intouch, env, [DETAILS(), CONFIRM, GPS, GPS, ON_SITE])
    assert out == "booked" and "On Site" in detail
    assert env["taps"] == [CARD_AT, PIN_IN_AT, YES_AT]      # the card, PIN IN, YES -- nothing else
    assert _back_presses(env) == []                         # BACK closes InTouch: never
    said = [r["detail"] for r in intouch.read_audit(1) if r["action"] == "book_on"]
    assert any("PIN IN" in d for d in said) and any("YES" in d for d in said)


def test_gps_refusal_is_retried_and_then_books_on(intouch, env):
    out, detail = _go(intouch, env, [DETAILS(), CONFIRM, GPS, REFUSED, CONFIRM, GPS, REFUSED, CONFIRM, GPS, ON_SITE])
    assert out == "booked" and "2 GPS refusals" in detail
    assert env["taps"].count(TRY_AGAIN_AT) == 2 and env["taps"].count(YES_AT) == 3
    assert env["taps"].count(PIN_IN_AT) == 1
    assert _back_presses(env) == []


def test_gps_refused_three_times_gives_up_politely(intouch, env):
    out, detail = _go(intouch, env, [DETAILS(), CONFIRM, REFUSED, CONFIRM, REFUSED, CONFIRM, REFUSED,
                                     REFUSED, DETAILS(), LIST()])
    assert out == "no_gps" and "on site" in detail
    assert env["taps"].count(TRY_AGAIN_AT) == 2             # gps_tries = 3 -> two TRY AGAINs
    assert env["taps"][-2:] == [DIALOG_CANCEL_AT, HEADER_CANCEL_AT]   # out through InTouch's own buttons
    assert _back_presses(env) == []


def test_details_of_another_shift_are_not_pinned_in(intouch, env):
    out, detail = _go(intouch, env, [DETAILS(date="Fri 27 November 2026", window="07:00 - 19:00"), LIST()])
    assert out == "failed" and "Fri 27 Nov" in detail
    assert PIN_IN_AT not in env["taps"] and YES_AT not in env["taps"]


def test_wrong_start_time_on_details_is_not_pinned_in(intouch, env):
    out, _ = _go(intouch, env, [DETAILS(window="19:00 - 07:00"), LIST()])
    assert out == "failed" and PIN_IN_AT not in env["taps"]


def test_login_form_in_the_middle_is_an_error_not_a_guess(intouch, env):
    out, detail = _go(intouch, env, [DETAILS(), LOGIN])
    assert out == "error" and "login" in detail.lower()
    assert SECRET not in detail


def test_yes_is_never_tapped_on_any_other_question(intouch, env):
    other = [_n("You are about to Pin Out. Is this correct?", (160, 1240, 1060, 1380)),
             _n("NO", (740, 1420, 830, 1520), clickable=True, cls="Button"),
             _n("YES", (935, 1420, 1050, 1520), clickable=True, cls="Button")]
    out, _ = _go(intouch, env, [other])
    assert YES_AT not in env["taps"] and out == "failed"


def test_nothing_is_tapped_on_the_on_site_screen(intouch, env, monkeypatch):
    monkeypatch.setattr(intouch, "ensure_awake_unlocked", lambda: "ok")
    monkeypatch.setattr(intouch, "relock_if_we_unlocked", lambda: None)
    env["screens"] = [ON_SITE]
    shift = {"start": (dt.datetime.now() + dt.timedelta(minutes=4)).isoformat(timespec="minutes")}
    out, detail = intouch.book_on_once(intouch.DEFAULTS, shift=shift)
    assert out == "already" and "On Site" in detail
    assert env["taps"] == [] and _back_presses(env) == []


def test_on_site_for_an_earlier_shift_is_not_this_shifts_book_on(intouch, env):
    intouch.save_json(intouch.SCHEDULE_FILE, [{"start": "2026-11-24T07:00", "end": "2026-11-24T19:00"},
                                              {"start": "2026-11-24T19:00", "end": "2026-11-25T07:00"}])
    night = {"start": "2026-11-24T19:00", "end": "2026-11-25T07:00"}
    # The screen's own clock decides: 11 h 50 min on site cannot be a shift that starts in 10 minutes.
    long_on_site = [dict(e, text="11 hr, 50 min") if e["text"] == "-4 min" else e for e in ON_SITE]
    out, detail = intouch._on_site_outcome(night, long_on_site, now=dt.datetime(2026, 11, 24, 18, 50))
    assert out == "other_shift" and "earlier shift" in detail
    out, _ = intouch._on_site_outcome(night, long_on_site, now=dt.datetime(2026, 11, 24, 19, 5))
    assert out == "other_shift"                              # still not this shift after 19:00
    # "-4 min" four to five minutes before the start: this shift.
    out, _ = intouch._on_site_outcome({"start": "2026-11-24T14:00"}, ON_SITE, now=dt.datetime(2026, 11, 24, 13, 55))
    assert out == "already"
    # Forgot to pin out yesterday: On Site still showing next morning is NOT today's book-on.
    stale = [dict(e, text="23 hr, 46 min") if e["text"] == "-4 min" else e for e in ON_SITE]
    out, _ = intouch._on_site_outcome({"start": "2026-11-28T07:00"}, stale, now=dt.datetime(2026, 11, 28, 6, 46))
    assert out == "other_shift"
    # Time unreadable: fall back to the schedule.
    blank = [e for e in ON_SITE if e["text"] != "-4 min"]
    out, detail = intouch._on_site_outcome(night, blank, now=dt.datetime(2026, 11, 24, 18, 50))
    assert out == "other_shift" and "07:00" in detail


def test_locked_phone_is_left_alone(intouch, env, monkeypatch):
    monkeypatch.setattr(intouch, "ensure_awake_unlocked", lambda: "locked")
    monkeypatch.setattr(intouch, "relock_if_we_unlocked", lambda: None)
    out, _ = intouch.book_on_once(intouch.DEFAULTS, shift={"start": "2026-11-24T14:00"})
    assert out == "locked" and env["shell"] == [] and env["taps"] == []     # not even HOME


# ---------------------------------------------------------------- opening InTouch
def test_on_site_screen_counts_as_open_and_is_not_touched(intouch, env):
    env["screens"] = [ON_SITE]
    assert intouch.open_intouch(intouch.DEFAULTS) is ON_SITE
    assert env["taps"] == [] and env["shell"] == [] and env["opened"] == 0
    assert intouch.goto_tab(0) is ON_SITE and env["taps"] == []


def test_shift_details_left_open_is_closed_with_its_own_cancel(intouch, env):
    env["screens"] = [DETAILS(), DETAILS(), LIST()]
    assert intouch._on_main_tabs(intouch.open_intouch(intouch.DEFAULTS))
    assert env["taps"] == [HEADER_CANCEL_AT] and _back_presses(env) == []


def test_refusal_left_open_is_closed_with_cancel_never_try_again(intouch, env):
    env["screens"] = [REFUSED, REFUSED, DETAILS(), LIST()]
    intouch.open_intouch(intouch.DEFAULTS)
    assert env["taps"] == [DIALOG_CANCEL_AT, HEADER_CANCEL_AT]


def test_pin_in_question_left_open_is_answered_no(intouch, env):
    env["screens"] = [CONFIRM, CONFIRM, DETAILS(), LIST()]
    intouch.open_intouch(intouch.DEFAULTS)
    assert YES_AT not in env["taps"] and env["taps"][0] == (785, 1470)       # NO


def test_while_intouch_looks_for_gps_nothing_is_pressed(intouch, env):
    env["screens"] = [GPS, GPS, GPS, GPS, ON_SITE]
    assert intouch.open_intouch(intouch.DEFAULTS) is ON_SITE
    assert env["taps"] == [] and _back_presses(env) == []


def test_blank_page_is_waited_out_without_back(intouch, env):
    env["screens"] = [[], [], [], [], LIST()]
    intouch.open_intouch(intouch.DEFAULTS)
    assert _back_presses(env) == [] and env["taps"] == []


def test_unknown_screen_is_never_backed_out_of(intouch, env, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(intouch.time, "time", lambda: clock["t"])
    monkeypatch.setattr(intouch.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    env["screens"] = [[_n("Something new", (100, 100, 900, 200))]]
    with pytest.raises(intouch.PhoneError, match="In front: " + PKG):
        intouch.open_intouch(intouch.DEFAULTS)
    assert _back_presses(env) == [] and env["opened"] == 3      # brought forward, then again, then gave up


def test_phone_locking_itself_mid_job_is_said_plainly(intouch, env, monkeypatch):
    monkeypatch.setattr(intouch.phone, "screen_state", lambda: {"awake": False, "locked": True})
    env["screens"] = [[]]
    with pytest.raises(intouch.PhoneError, match="locked itself"):
        intouch.open_intouch(intouch.DEFAULTS)


# ---------------------------------------------------------------- the password never leaves the box
def test_screen_text_never_includes_input_boxes(intouch, env):
    texts = intouch._texts(LOGIN)
    assert SECRET not in texts and "someone@example.com" not in texts
    assert "Forgotten Password?" in texts
    half = [dict(LOGIN[2], text=SECRET[:5])]                 # a half-typed password cannot be matched: still out
    assert intouch._texts(half) == [] and intouch._say(LOGIN + half) and SECRET[:5] not in intouch._say(LOGIN + half)


def test_log_audit_and_notification_are_scrubbed(intouch, env, monkeypatch):
    intouch.SECRET_FILE.write_text(SECRET + "\n")
    intouch.log("screen said: " + SECRET)
    intouch.audit("login", "failed", "box held " + SECRET.upper())
    assert SECRET not in intouch.LOG_FILE.read_text()
    raw = intouch.AUDIT_FILE.read_text()
    assert SECRET not in raw and SECRET.upper() not in raw and "[hidden]" in raw


def test_filled_password_box_is_still_the_login_form(intouch, env):
    assert intouch._password_field(LOGIN) is LOGIN[2]        # the lower box, although nothing marks it
    empty = [LOGIN[0], LOGIN[1], dict(LOGIN[2], text="Password"), LOGIN[3]]
    assert intouch._password_field(empty)["text"] == "Password"
    assert intouch._is_login_screen(LOGIN, intouch.DEFAULTS)


def test_unrecognised_login_form_logs_no_box_text(intouch, env):
    intouch.SECRET_FILE.write_text(SECRET)
    odd = [LOGIN[0], dict(LOGIN[2], text=SECRET[:6]), LOGIN[4]]      # one box, no LOGIN button
    with pytest.raises(intouch.PhoneError):
        intouch.login(intouch.DEFAULTS, odd)
    raw = intouch.AUDIT_FILE.read_text()
    assert SECRET[:6] not in raw and "not recognised" in raw


def test_adb_errors_never_echo_typed_text(intouch):
    phone = intouch.phone
    assert phone._shown(("shell", "input text 'a'; input text 'b'")) == "shell input <hidden>"
    assert "dumpsys" in phone._shown(("shell", "dumpsys power"))


def test_phone_screen_command_hides_login_boxes(intouch):
    masked = intouch.phone.mask_login_inputs([dict(e, id="") for e in LOGIN])
    assert SECRET not in json.dumps(masked) and "someone@example.com" not in json.dumps(masked)
    plain = [_n("Search", (0, 0, 10, 10), cls="EditText"), _n("milk", (0, 20, 10, 30), cls="EditText")]
    assert intouch.phone.mask_login_inputs(plain) == plain   # ordinary screens are untouched


# ---------------------------------------------------------------- never these buttons
@pytest.mark.parametrize("label", ["PIN OUT", "Pin Off", "SOS", "CHECK CALL", "Call Sam Manager",
                                   "REQUEST HOLIDAY", "End shift", "Book off", "Cancel shift", "Log out"])
def test_blocked_labels(intouch, label):
    with pytest.raises(intouch.PhoneError):
        intouch.phone.check_allowed(label, force=False)


@pytest.mark.parametrize("label", ["PIN IN", "YES", "TRY AGAIN", "CANCEL", "OK", "NO"])
def test_labels_the_flow_needs_are_allowed(intouch, label):
    intouch.phone.check_allowed(label, force=False)


def test_sos_position_is_never_tapped_in_any_flow(intouch, env):
    for screens in ([DETAILS(), CONFIRM, GPS, ON_SITE], [DETAILS(), CONFIRM, REFUSED, CONFIRM, ON_SITE]):
        env["taps"].clear()
        _go(intouch, env, screens)
        assert SOS_AT not in env["taps"]
        assert all(y > 280 or (x, y) == HEADER_CANCEL_AT for x, y in env["taps"])   # title bar: CANCEL only


# ---------------------------------------------------------------- the service around it
@pytest.fixture
def svc(intouch, env, monkeypatch):
    s = intouch._Service()
    monkeypatch.setattr(s, "link", lambda cfg, force=False: True)
    return s


def test_gps_refusal_retries_after_a_minute_and_tells_the_user_once(intouch, env, svc, monkeypatch):
    shift = {"start": "2026-11-24T14:00", "end": "2026-11-24T20:00"}
    results = iter([("no_gps", "InTouch could not confirm you are on site"),
                    ("no_gps", "InTouch could not confirm you are on site"),
                    ("booked", "InTouch shows the On Site screen")])
    calls = []
    monkeypatch.setattr(intouch, "book_on_once", lambda cfg, shift=None: (calls.append(1), next(results))[1])
    t = dt.datetime(2026, 11, 24, 13, 45)
    times = []
    while t <= dt.datetime(2026, 11, 24, 13, 49) and svc.state["shifts"].get(shift["start"], {}).get("status") != "booked":
        before = len(calls)
        svc.handle_shift(shift, intouch.DEFAULTS, t)
        if len(calls) > before:
            times.append(t)
        t += dt.timedelta(seconds=30)
    assert [f"{x:%H:%M:%S}" for x in times] == ["13:45:00", "13:46:00", "13:47:00"]
    assert env["sent"].count("InTouch can't see you on site yet") == 1
    assert svc.state["shifts"][shift["start"]]["status"] == "booked"


def test_one_shifts_crash_does_not_block_another(intouch, env, svc, monkeypatch):
    intouch.save_json(intouch.SCHEDULE_FILE, [{"start": "2026-11-24T14:00"}, {"start": "2026-11-24T14:05"}])
    svc.state["checks"] = {"x": "y"}
    svc.startup_pending = False
    seen = []

    def handle(shift, cfg, now):
        seen.append(shift["start"])
        if shift["start"].endswith("14:00"):
            raise RuntimeError("boom")
    monkeypatch.setattr(svc, "handle_shift", handle)
    monkeypatch.setattr(intouch, "resume_unlock_if_user_unlocked", lambda: None)
    svc.tick(dt.datetime(2026, 11, 24, 6, 0))
    assert seen == ["2026-11-24T14:00", "2026-11-24T14:05"]


def test_link_error_does_not_escape_the_tick(intouch, env, monkeypatch):
    s = intouch._Service()
    s.startup_pending = False
    monkeypatch.setattr(intouch.phone, "ensure_connected",
                        lambda: (_ for _ in ()).throw(intouch.PhoneError("offline")))
    monkeypatch.setattr(intouch, "reconnect_adb",
                        lambda: (_ for _ in ()).throw(intouch.PhoneError("adb timed out: connect 127.0.0.1:36015")))
    s.tick(dt.datetime(2026, 11, 24, 6, 0))                  # must not raise
    assert s.link_ok is False


def test_failed_unlock_is_audited_once_per_reason(intouch, env, monkeypatch):
    monkeypatch.setattr(intouch.phone, "in_call", lambda: False)
    monkeypatch.setattr(intouch.phone, "screen_state", lambda: {"awake": True, "locked": True})
    monkeypatch.setattr(intouch.phone, "pin_saved", lambda: True)
    monkeypatch.setattr(intouch.phone, "unlock_paused", lambda: False)
    n = {"k": 0}

    def unlock():
        n["k"] += 1
        raise intouch.PhoneError(f"Could not bring up the lock screen's PIN/password/pattern entry "
                                 f"(window in front: NotificationShade; {30 + n['k']} screen elements).")
    monkeypatch.setattr(intouch.phone, "unlock", unlock)
    for _ in range(5):
        assert intouch.ensure_awake_unlocked() == "locked"
    failed = [r for r in intouch.read_audit(1) if r["action"] == "unlock" and r["result"] == "failed"]
    assert len(failed) == 1 and "repeats today" in failed[0]["detail"]
    monkeypatch.setattr(intouch.phone, "unlock", lambda: "unlocked")
    assert intouch.ensure_awake_unlocked() == "ok"
    assert any("5 failed tries" in r["detail"] for r in intouch.read_audit(1))
    monkeypatch.setattr(intouch, "_UNLOCKED_BY_US", False)


def test_notification_failure_never_raises(intouch, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("intouch_notify", SCRIPTS / "intouch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(mod, "LOG_FILE", tmp_path / "log")
    monkeypatch.setattr(mod, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(mod, "SECRET_FILE", tmp_path / "password")
    monkeypatch.setenv("INTOUCH_VERBOSE", "0")
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/bin/termux-notification")

    def hang(*a, **k):
        raise mod.subprocess.TimeoutExpired("termux-notification", 20)
    monkeypatch.setattr(mod.subprocess, "run", hang)
    mod.notify("Title", "text")                              # must not raise
    assert "could not be shown" in (tmp_path / "log").read_text()


# ---------------------------------------------------------------- the password is typed hidden
class FakeLoginForm:
    """InTouch's login page: an email box, a password box with a show/hide eye, LOGIN."""
    BOX = (60, 560, 1010, 660)
    EYE = (1040, 570, 1160, 650)

    def __init__(self, showing, eye_works=True):
        self.showing, self.eye_works = showing, eye_works
        self.text, self.logged_in, self.exposed, self.submitted = "", False, [], []

    def screen(self):
        if self.logged_in:
            return LIST()
        shown = self.text if self.showing else "\u2022" * len(self.text)
        box = _n(shown or "Password", self.BOX, cls="EditText", clickable=True, password=not self.showing)
        return [_n("Login", (480, 150, 740, 240)),
                _n("someone@example.com", (60, 400, 1150, 500), cls="EditText", clickable=True),
                box, _n("", self.EYE, clickable=True, cls="ImageView"),
                _n("LOGIN", (60, 760, 1150, 900), clickable=True, cls="Button"),
                _n("Forgotten Password?", (380, 960, 840, 1020), clickable=True)]

    def shell(self, cmd, timeout=30):
        import shlex
        for part in cmd.split(";"):
            words = shlex.split(part)
            if words[:2] == ["input", "text"]:
                self.text += words[2]
                if self.showing and words[2] != "x":
                    self.exposed.append(words[2])         # real password characters readable on screen
            elif words[:2] == ["input", "keyevent"]:
                self.text = self.text[:max(0, len(self.text) - words.count("KEYCODE_DEL"))]
        return ""

    def tap(self, x, y):
        inside = lambda b: b[0] <= x <= b[2] and b[1] <= y <= b[3]  # noqa: E731
        if inside(self.EYE) and self.eye_works:
            self.showing = not self.showing
        elif inside((60, 760, 1150, 900)):
            self.submitted.append(self.text)
            self.logged_in = self.text == SECRET


def _login(intouch, env, monkeypatch, form):
    intouch.SECRET_FILE.write_text(SECRET)
    monkeypatch.setattr(intouch, "screen", form.screen)
    monkeypatch.setattr(intouch.phone, "shell", form.shell)
    monkeypatch.setattr(intouch.phone, "tap_xy", form.tap)
    return intouch.login(intouch.DEFAULTS, form.screen())


def test_password_box_in_show_mode_is_hidden_before_typing(intouch, env, monkeypatch):
    form = FakeLoginForm(showing=True)
    _login(intouch, env, monkeypatch, form)
    assert form.logged_in and form.submitted == [SECRET]
    assert form.exposed == [] and form.showing is False     # eye switched off first; nothing readable
    assert any("hidden" in r["detail"] for r in intouch.read_audit(1) if r["action"] == "login")
    assert SECRET not in intouch.AUDIT_FILE.read_text() + intouch.LOG_FILE.read_text()


def test_password_box_already_hidden_is_just_typed(intouch, env, monkeypatch):
    form = FakeLoginForm(showing=False)
    _login(intouch, env, monkeypatch, form)
    assert form.logged_in and form.exposed == [] and form.showing is False


def test_password_is_not_typed_if_the_box_will_not_hide(intouch, env, monkeypatch):
    form = FakeLoginForm(showing=True, eye_works=False)
    with pytest.raises(intouch.PhoneError, match="would not hide"):
        _login(intouch, env, monkeypatch, form)
    assert form.exposed == [] and form.submitted == []      # never typed, never sent


def test_password_goes_in_as_one_command(intouch):
    assert intouch._type_secret_command("Abc123!x") == "input text 'Abc123!x'"
    assert intouch._type_secret_command("a b") == "input text a%sb"
    assert intouch._type_secret_command("50%off").count("input") == 6   # a % needs the slow way


# ---------------------------------------------------------------- fixes from the review
CANT_YET = [_n("You can\u2019t start this shift yet", (161, 1169, 1055, 1255)),
            _n("This shift can be started at 10:45 am on Monday", (83, 1281, 1133, 1429)),
            _n("OK", (308, 1450, 516, 1606), clickable=True, cls="Button"),
            _n("REQUEST HOLIDAY", (516, 1450, 1094, 1606), clickable=True, cls="Button")]


def test_cant_start_message_left_open_is_closed_with_ok(intouch, env):
    env["screens"] = [CANT_YET, CANT_YET, LIST()]
    assert intouch._on_main_tabs(intouch.open_intouch(intouch.DEFAULTS))
    assert env["taps"] == [(412, 1528)]                      # OK -- never REQUEST HOLIDAY
    assert env["opened"] == 1


def test_another_app_in_front_is_never_tapped(intouch, env):
    chat = [_n("Delete this chat?", (100, 1100, 1100, 1200), pkg="com.chat"),
            _n("OK", (600, 1450, 1100, 1600), clickable=True, cls="Button", pkg="com.chat")]
    out, detail = _go(intouch, env, [DETAILS(), chat])
    assert out == "error" and "another app" in detail
    assert (850, 1525) not in env["taps"]


def test_two_button_dialogs_are_not_okayed(intouch, env):
    ask = [_n("Something else?", (100, 1100, 1100, 1200)),
           _n("CANCEL", (100, 1450, 500, 1600), clickable=True, cls="Button"),
           _n("OK", (600, 1450, 1100, 1600), clickable=True, cls="Button")]
    _go(intouch, env, [ask])
    assert (850, 1525) not in env["taps"]


def test_a_call_starting_mid_flow_stops_it(intouch, env, monkeypatch):
    monkeypatch.setattr(intouch.phone, "in_call", lambda: True)
    out, _ = _go(intouch, env, [DETAILS(), CONFIRM])
    assert out == "in_call" and env["taps"] == [CARD_AT]


def test_cancel_is_never_tapped_once_on_site_is_showing(intouch, env):
    both = DETAILS() + ON_SITE                               # mid-slide: both pages in one dump
    assert intouch._leave_pin_in_step(both) is None and env["taps"] == []
    assert intouch._leave_pin_in_step([e for e in DETAILS() if e["text"] != "PIN IN"]) is None


def test_password_is_not_typed_while_the_cursor_is_in_the_email_box(intouch, env, monkeypatch):
    form = FakeLoginForm(showing=False)
    plain = form.screen
    form.screen = lambda: [dict(e, focused=(e["text"] == "someone@example.com")) for e in plain()]
    with pytest.raises(intouch.PhoneError):
        _login(intouch, env, monkeypatch, form)
    assert form.text == "" and form.submitted == []          # nothing typed anywhere, nothing sent


def test_leftover_text_in_a_showing_box_is_not_proof_of_hiding(intouch, env, monkeypatch):
    form = FakeLoginForm(showing=True, eye_works=False)
    form.text = "abc"                                        # leftovers; no "x" in them
    monkeypatch.setattr(intouch, "screen", form.screen)
    monkeypatch.setattr(intouch.phone, "shell", lambda cmd, timeout=30: "")   # typing goes nowhere
    monkeypatch.setattr(intouch.phone, "tap_xy", form.tap)
    assert intouch._hide_password_box(form.screen()[2]) is False


def test_old_audit_lines_are_scrubbed_when_read_and_pruned(intouch, env):
    intouch.SECRET_FILE.write_text(SECRET)
    rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "action": "login", "result": "failed",
           "detail": "Login | a@b.c | " + SECRET + " | LOGIN"}
    intouch.AUDIT_FILE.write_text(json.dumps(rec) + "\n")   # as written by the old version
    assert SECRET not in intouch.format_audit(intouch.read_audit(1))
    intouch.prune_audit()
    assert SECRET not in intouch.AUDIT_FILE.read_text()


def test_login_message_does_not_give_the_password_length(intouch, env, monkeypatch):
    form = FakeLoginForm(showing=False)
    intouch.SECRET_FILE.write_text(SECRET)
    monkeypatch.setattr(intouch, "screen", form.screen)
    monkeypatch.setattr(intouch.phone, "shell", lambda cmd, timeout=30: "")   # nothing lands
    monkeypatch.setattr(intouch.phone, "tap_xy", form.tap)
    with pytest.raises(intouch.PhoneError) as err:
        intouch.login(intouch.DEFAULTS, form.screen())
    assert str(len(SECRET)) not in str(err.value) + intouch.AUDIT_FILE.read_text()


def test_wait_before_retry_counts_from_the_end_of_an_attempt(intouch, env, svc, monkeypatch):
    shift = {"start": "2026-11-24T14:00"}
    clock = {"t": 5000.0}
    monkeypatch.setattr(intouch.time, "time", lambda: clock["t"])

    def slow(cfg, shift=None):
        clock["t"] += 150                                    # the attempt itself took 2.5 minutes
        return "failed", "InTouch said: nothing"
    monkeypatch.setattr(intouch, "book_on_once", slow)
    svc.handle_shift(shift, intouch.DEFAULTS, dt.datetime(2026, 11, 24, 13, 45))
    assert svc.state["shifts"][shift["start"]]["last_attempt"] == "2026-11-24T13:47:30"
    assert env["sent"].count("Auto book-on problem") == 1    # a failed attempt is reported, once


def test_other_shift_on_site_is_reported_and_not_marked_booked(intouch, env, svc, monkeypatch):
    shift = {"start": "2026-11-24T14:00"}
    monkeypatch.setattr(intouch, "book_on_once",
                        lambda cfg, shift=None: ("other_shift", "earlier shift still pinned in"))
    svc.handle_shift(shift, intouch.DEFAULTS, dt.datetime(2026, 11, 24, 13, 45))
    assert svc.state["shifts"][shift["start"]]["status"] == "pending"
    assert "InTouch still shows an earlier shift" in env["sent"]
