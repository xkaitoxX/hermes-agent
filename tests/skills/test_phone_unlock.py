"""Automatic unlock in the phone-control skill: PIN / password / pattern, verified, one try only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "android" / "phone-control" / "scripts"))
import phone  # noqa: E402

PIN_PAD = [{"desc": "PIN area", "text": "", "cls": "EditText", "id": "", "pkg": "com.android.systemui",
            "bounds": [0, 1505, 1216, 1583]}] + [
    {"desc": d, "text": "", "cls": "ViewGroup", "id": "", "pkg": "com.android.systemui", "bounds": [0, 0, 10, 10]}
    for d in "1234567890"]
PATTERN_VIEW = [{"desc": "", "text": "", "cls": "com.android.internal.widget.LockPatternView",
                 "id": "com.android.systemui:id/lockPatternView", "pkg": "com.android.systemui",
                 "bounds": [100, 1200, 1000, 2100]}]


@pytest.fixture
def fake_phone(tmp_path, monkeypatch):
    monkeypatch.setattr(phone, "PIN_FILE", tmp_path / "unlock-pin")
    monkeypatch.setattr(phone, "UNLOCK_BLOCK_FILE", tmp_path / "unlock_blocked")
    monkeypatch.setattr(phone, "STATE_DIR", tmp_path)
    monkeypatch.setattr(phone.time, "sleep", lambda s: None)
    sim = {"locked": True, "screen": PIN_PAD, "accept": None, "shell": [], "call": 0,
           "focus": "mCurrentFocus=Window{4560a6f u0 NotificationShade}"}

    def shell(cmd, timeout=30):
        sim["shell"].append(cmd)
        if cmd.startswith("wm size"):
            return "Physical size: 1216x2688"
        if "telephony.registry" in cmd:
            return f"  mCallState={sim['call']}\n"
        if "mCurrentFocus" in cmd:
            return sim["focus"]
        if sim["accept"] and sim["accept"] in cmd:
            sim["locked"] = False
        return ""

    monkeypatch.setattr(phone, "shell", shell)
    monkeypatch.setattr(phone, "screen_state", lambda: {"awake": True, "locked": sim["locked"]})
    monkeypatch.setattr(phone, "dump_screen", lambda: sim["screen"])
    return sim


def test_already_unlocked_types_nothing(fake_phone):
    fake_phone["locked"] = False
    assert phone.unlock() == "already"
    assert not any("input text" in c for c in fake_phone["shell"])


def test_pin_unlocks_once_and_is_verified(fake_phone):
    phone.PIN_FILE.write_text("4826")
    fake_phone["accept"] = "keyevent 66"
    assert phone.unlock() == "unlocked"
    assert sum("input text" in c for c in fake_phone["shell"]) == 1


WRONG_PIN = [{"desc": "", "text": "Wrong PIN", "cls": "TextView", "id": "", "pkg": "com.android.systemui",
               "bounds": [0, 900, 1216, 960]}]


def test_wrong_pin_pauses_further_unlocks(fake_phone):
    phone.PIN_FILE.write_text("0000")
    fake_phone["screen"] = PIN_PAD + WRONG_PIN  # Android says the PIN was wrong
    with pytest.raises(phone.PhoneError, match="paused"):
        phone.unlock()
    assert phone.unlock_paused()
    typed = sum("input text" in c for c in fake_phone["shell"])
    with pytest.raises(phone.PhoneError, match="paused"):
        phone.unlock()
    assert sum("input text" in c for c in fake_phone["shell"]) == typed  # no second PIN entry
    phone.resume_unlock()  # the user unlocked by hand
    assert not phone.unlock_paused()


def test_unlock_that_did_not_register_does_not_pause(fake_phone):
    # Touches blocked (pocket mode): no wrong-PIN message, so Android counted nothing.
    phone.PIN_FILE.write_text("4826")
    with pytest.raises(phone.PhoneError, match="no wrong-PIN message"):
        phone.unlock()
    assert not phone.unlock_paused()


def test_no_saved_secret_says_how_to_set_it(fake_phone):
    with pytest.raises(phone.PhoneError, match="set-unlock"):
        phone.unlock()


def test_pattern_is_drawn_on_the_right_dots(fake_phone):
    phone.PIN_FILE.write_text("pattern:14789")
    fake_phone["screen"] = PATTERN_VIEW
    fake_phone["accept"] = "motionevent UP"
    assert phone.unlock() == "unlocked"
    drawn = next(c for c in fake_phone["shell"] if "motionevent DOWN" in c)
    assert drawn.startswith("input motionevent DOWN 250 1350")      # dot 1 = top-left centre
    assert drawn.endswith("input motionevent UP 850 1950")          # dot 9 = bottom-right centre


def test_pin_saved_but_pattern_screen_enters_nothing(fake_phone):
    phone.PIN_FILE.write_text("4826")
    fake_phone["screen"] = PATTERN_VIEW
    with pytest.raises(phone.PhoneError, match="asks for a pattern"):
        phone.unlock()
    assert not any("input text" in c or "motionevent" in c for c in fake_phone["shell"])


def _entered_anything(sim) -> bool:
    return any("input text" in c or "motionevent" in c or "keyevent 66" in c for c in sim["shell"])


def test_no_unlock_during_a_call(fake_phone):
    phone.PIN_FILE.write_text("482915")
    fake_phone["call"] = 2  # off-hook
    with pytest.raises(phone.PhoneError, match="call"):
        phone.unlock()
    assert not _entered_anything(fake_phone)
    assert not phone.UNLOCK_BLOCK_FILE.exists()  # a call is not a failed unlock


def test_call_screen_in_front_enters_nothing(fake_phone):
    # The bouncer looked fine, but by typing time the in-call screen is the focused window.
    phone.PIN_FILE.write_text("482915")
    fake_phone["focus"] = "mCurrentFocus=Window{1 u0 com.google.android.dialer/com.android.dialer.incall.activity.ui.InCallActivity}"
    with pytest.raises(phone.PhoneError, match="nothing was entered"):
        phone.unlock()
    assert not _entered_anything(fake_phone)


def test_pattern_points_grid():
    assert phone._pattern_points("159", [0, 0, 300, 300]) == [(50, 50), (150, 150), (250, 250)]
