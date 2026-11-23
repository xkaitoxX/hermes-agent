#!/usr/bin/env python3
"""phone.py -- let an agent see and operate this Android phone through adb (stdlib only).

Runs inside Termux on the phone itself. adb talks to the phone's own adb daemon over
localhost (``adb tcpip 5555`` once per boot, then ``adb connect 127.0.0.1:5555``), so no
PC is needed once that is set up. See SKILL.md.

The screen is read as TEXT (Android's accessibility tree via ``uiautomator dump``), so a
text-only model can drive apps: ``screen`` prints numbered elements, ``tap N`` taps one.

Commands
  status                      adb link, screen on/locked, foreground app
  connect                     (re)connect adb to this phone over localhost
  screen [--all] [--json]     numbered list of on-screen elements (saved for `tap N`)
  tap N | tap --text T | tap --desc T | tap-xy X Y
  type TEXT                   type into the focused field
  key back|home|enter|recents|wake|tab|delete|search
  swipe up|down|left|right
  open PACKAGE                launch an app;  apps [FILTER]  list installed packages
  wait --text T [--timeout S] wait until text appears on screen
  current                     foreground package/activity

Safety: taps on elements whose text matches the block list (logout, delete, uninstall,
factory reset, payment words...) are refused unless --force is given. Edit
~/.config/phone-control/blocklist.txt to change it. Passwords and PINs must never be typed
by an agent: `type` refuses when the focused field is a password field.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SERIAL = os.environ.get("PHONE_ADB_SERIAL", "127.0.0.1:5555")
STATE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "phone-control"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "phone-control"
LAST_SCREEN = STATE_DIR / "last_screen.json"
PIN_FILE = CONFIG_DIR / "unlock-pin"              # written only by `set-unlock-pin` (the user types it)
UNLOCK_BLOCK_FILE = STATE_DIR / "unlock_blocked"  # present after a failed unlock: no more tries
DEFAULT_BLOCKLIST = [
    r"\blog ?out\b", r"\bsign ?out\b", r"\bdelete\b", r"\buninstall\b", r"\bfactory reset\b",
    r"\berase\b", r"\bremove account\b", r"\bpay now\b", r"\bbuy\b", r"\bpurchase\b",
    r"\btransfer\b", r"\bsend money\b", r"\bconfirm payment\b",
    # shift apps: booking on must never end a shift or file a request
    r"\brequest holiday\b", r"\bend shift\b", r"\bfinish shift\b", r"\bbook ?off\b", r"\bclock ?out\b",
    r"\bsign ?off\b",
]
KEYS = {
    "back": 4, "home": 3, "enter": 66, "recents": 187, "wake": 224, "tab": 61,
    "delete": 67, "search": 84, "menu": 82, "sleep": 223,
}


class PhoneError(RuntimeError):
    pass


# ---------------------------------------------------------------- adb plumbing
def _adb_bin() -> str:
    adb = shutil.which("adb")
    if not adb:
        raise PhoneError("adb not found. In Termux run: pkg install android-tools")
    return adb


def adb(*args: str, timeout: float = 30, check: bool = True, serial: bool = True) -> str:
    cmd = [_adb_bin()] + (["-s", SERIAL] if serial else []) + list(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PhoneError(f"adb timed out: {' '.join(args)}") from exc
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        if "device" in msg and ("not found" in msg or "offline" in msg or "unauthorized" in msg):
            msg += "\nThe adb link to this phone is down. Run: phone.py connect  (see SKILL.md 'Setup')"
        raise PhoneError(msg or f"adb {' '.join(args)} failed")
    return proc.stdout


def shell(cmd: str, timeout: float = 30) -> str:
    return adb("shell", cmd, timeout=timeout)


def connect() -> str:
    out = adb("connect", SERIAL, serial=False, check=False, timeout=15)
    devices = adb("devices", serial=False, check=False)
    line = next((l for l in devices.splitlines() if l.startswith(SERIAL)), "")
    if line.endswith("device"):
        return f"connected to {SERIAL}"
    if "unauthorized" in line:
        raise PhoneError("Phone shows 'Allow USB debugging?' -- tap 'Always allow' then 'Allow', and retry.")
    raise PhoneError(
        f"Could not connect to {SERIAL} ({out.strip()}).\n"
        "adb over localhost is off (it resets on every reboot). Re-enable it: see SKILL.md 'Setup'."
    )


def ensure_connected() -> None:
    devices = adb("devices", serial=False, check=False)
    line = next((l for l in devices.splitlines() if l.startswith(SERIAL)), "")
    if not line.endswith("device"):
        connect()


# ---------------------------------------------------------------- screen model
def _bounds(raw: str) -> tuple[int, int, int, int]:
    nums = [int(n) for n in re.findall(r"-?\d+", raw or "")]
    return tuple(nums) if len(nums) == 4 else (0, 0, 0, 0)  # type: ignore[return-value]


def dump_screen() -> list[dict]:
    """Return every node of the current UI tree as dicts (index order = document order)."""
    xml = ""
    for _ in range(3):
        xml = adb("exec-out", "uiautomator", "dump", "/dev/tty", timeout=40, check=False)
        start = xml.find("<?xml")
        if start >= 0:
            xml = xml[start:]
            end = xml.rfind("</hierarchy>")
            xml = xml[: end + len("</hierarchy>")] if end >= 0 else xml
            break
        time.sleep(1.0)  # "could not get idle state" while animating -- retry
    else:
        raise PhoneError("Could not read the screen (uiautomator dump failed). Is the screen on and unlocked?")
    root = ET.fromstring(xml)
    nodes = []
    for el in root.iter("node"):
        a = el.attrib
        x1, y1, x2, y2 = _bounds(a.get("bounds", ""))
        nodes.append({
            "text": a.get("text", ""), "desc": a.get("content-desc", ""),
            "id": a.get("resource-id", ""), "cls": a.get("class", "").rsplit(".", 1)[-1],
            "pkg": a.get("package", ""), "clickable": a.get("clickable") == "true",
            "checked": a.get("checked") == "true", "enabled": a.get("enabled") != "false",
            "password": a.get("password") == "true", "focused": a.get("focused") == "true",
            "bounds": [x1, y1, x2, y2], "center": [(x1 + x2) // 2, (y1 + y2) // 2],
        })
    return nodes


def visible_elements(nodes: list[dict], show_all: bool = False) -> list[dict]:
    out = []
    for n in nodes:
        x1, y1, x2, y2 = n["bounds"]
        if x2 <= x1 or y2 <= y1:
            continue
        meaningful = n["text"] or n["desc"] or n["clickable"] or "EditText" in n["cls"]
        if show_all or meaningful:
            out.append(n)
    for i, n in enumerate(out):
        n["i"] = i
    return out


def describe(n: dict) -> str:
    label = n["text"] or n["desc"] or (n["id"].split("/")[-1] if n["id"] else "")
    label = re.sub(r"\s+", " ", label).strip()
    if len(label) > 160:
        label = label[:157] + "..."
    flags = []
    if n["clickable"]:
        flags.append("tap")
    if "EditText" in n["cls"]:
        flags.append("input")
    if n["password"]:
        flags.append("PASSWORD")
    if n["checked"]:
        flags.append("checked")
    if not n["enabled"]:
        flags.append("disabled")
    if n["focused"]:
        flags.append("focused")
    return f"[{n['i']}] {n['cls']} \"{label}\" {'(' + ', '.join(flags) + ')' if flags else ''} @{n['center'][0]},{n['center'][1]}"


def save_screen(elems: list[dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_SCREEN.write_text(json.dumps({"t": time.time(), "elements": elems}))


def load_screen() -> list[dict]:
    try:
        data = json.loads(LAST_SCREEN.read_text())
    except (OSError, ValueError) as exc:
        raise PhoneError("No saved screen -- run `phone.py screen` first.") from exc
    if time.time() - data.get("t", 0) > 600:
        raise PhoneError("Saved screen is older than 10 minutes -- run `phone.py screen` again.")
    return data["elements"]


def blocklist() -> list[str]:
    path = CONFIG_DIR / "blocklist.txt"
    try:
        return [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]
    except OSError:
        return DEFAULT_BLOCKLIST


def check_allowed(label: str, force: bool) -> None:
    if force:
        return
    for pattern in blocklist():
        if re.search(pattern, label, re.IGNORECASE):
            raise PhoneError(f"Refused: '{label}' matches the safety block list ({pattern}). "
                             "Ask the user; only they can approve this (--force).")


def find_by(elems: list[dict], text: str | None, desc: str | None) -> dict:
    needle = (text or desc or "").lower()
    key = "text" if text else "desc"
    exact = [e for e in elems if e[key].strip().lower() == needle]
    partial = [e for e in elems if needle in e[key].lower()]
    hits = exact or partial
    if not hits:
        raise PhoneError(f"No element with {key} matching '{text or desc}' on screen.")
    clickable = [e for e in hits if e["clickable"]]
    return (clickable or hits)[0]


def foreground() -> str:
    out = shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -2")
    m = re.search(r"u0 ([\w.]+)/([\w.$]+)", out)
    return f"{m.group(1)}/{m.group(2)}" if m else out.strip()


def screen_state() -> dict:
    power = shell("dumpsys power | grep -E 'mWakefulness=|Display Power' | head -2")
    keyguard = shell("dumpsys window | grep -E 'isKeyguardShowing|mDreamingLockscreen|KeyguardShowing' | head -3")
    return {
        "awake": "Awake" in power or "state=ON" in power,
        "locked": bool(re.search(r"(isKeyguardShowing|KeyguardShowing)\s*=?\s*true", keyguard)),
    }


# ---------------------------------------------------------------- lock screen
def in_call() -> bool:
    """True while a phone call is ringing or active. Nothing may type or tap then: key presses
    on the in-call screen can be sent into the call as keypad tones."""
    out = shell("dumpsys telephony.registry | grep -m 4 mCallState=")
    return any(v != "0" for v in re.findall(r"mCallState=(\d+)", out))


def lockscreen_in_front() -> bool:
    """The focused window is SystemUI's lock screen / bouncer (shown as NotificationShade)."""
    out = shell("dumpsys window | grep -m 1 mCurrentFocus")
    return any(k in out for k in ("NotificationShade", "com.android.systemui", "Keyguard", "Bouncer"))


def pin_saved() -> bool:
    return PIN_FILE.exists()


def _read_pin() -> str | None:
    """The saved secret: 'pattern:<digits 1-9>' for a pattern, otherwise a PIN or password."""
    try:
        pin = PIN_FILE.read_text().strip()
    except OSError:
        return None
    return pin or None


def _pattern_points(seq: str, bounds: list[int]) -> list[tuple[int, int]]:
    """Centres of the 3x3 pattern dots (1 = top-left ... 9 = bottom-right) inside ``bounds``."""
    x1, y1, x2, y2 = bounds
    cw, ch = (x2 - x1) / 3, (y2 - y1) / 3
    pts = []
    for d in seq:
        i = int(d) - 1
        pts.append((int(x1 + cw * (i % 3) + cw / 2), int(y1 + ch * (i // 3) + ch / 2)))
    return pts


def _draw_pattern(seq: str, bounds: list[int]) -> None:
    pts = _pattern_points(seq, bounds)
    cmds = [f"input motionevent DOWN {pts[0][0]} {pts[0][1]}"]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        for k in range(1, 6):  # interpolate so every dot on the way registers
            cmds.append(f"input motionevent MOVE {int(ax + (bx - ax) * k / 5)} {int(ay + (by - ay) * k / 5)}")
    cmds.append(f"input motionevent UP {pts[-1][0]} {pts[-1][1]}")
    shell("; ".join(cmds))


def unlock() -> str:
    """Unlock the phone with the PIN the user saved (``set-unlock-pin``). Returns 'already' | 'unlocked'.

    One PIN entry per call, verified afterwards; a failed entry blocks further automatic unlocks
    (Android throttles and may wipe after repeated wrong PINs) until ``reset-unlock``. The PIN is
    never printed or logged. Agents must not call this to get into the phone on their own: it is for
    the user's own scheduled automations.
    """
    state = screen_state()
    if not state["awake"]:
        shell("input keyevent 224")
        time.sleep(1.0)
        state = screen_state()
    if not state["locked"]:
        return "already"
    if in_call():
        raise PhoneError("A phone call is in progress; not touching the lock screen.")
    if UNLOCK_BLOCK_FILE.exists():
        raise PhoneError("Automatic unlock is paused after a wrong PIN; it resumes after you next unlock "
                         "the phone by hand (or run: phone.py reset-unlock)")
    secret = _read_pin()
    if not secret:
        raise PhoneError("Phone is locked and no unlock PIN/password/pattern is saved "
                         "(phone.py set-unlock-pin or set-unlock-pattern).")
    pattern = secret[8:] if secret.startswith("pattern:") else None
    if pattern is None and any(ord(c) > 126 or ord(c) < 33 for c in secret):
        raise PhoneError("The saved unlock PIN/password has characters that cannot be typed automatically.")
    size = shell("wm size")
    m = re.search(r"(\d+)x(\d+)", size)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)
    kind, pattern_bounds = None, None
    for _ in range(3):  # bring up the bouncer (swipe up on the lock screen)
        shell(f"input swipe {w // 2} {int(h * 0.82)} {w // 2} {int(h * 0.30)} 250")
        time.sleep(1.3)
        if not screen_state()["locked"]:
            return "unlocked"  # face unlock or a non-secure lock got there first
        nodes = dump_screen()
        descs = {n["desc"].lower() for n in nodes}
        patt = next((n for n in nodes if "pattern" in (n["cls"] + n["id"] + n["desc"]).lower()
                     and n["bounds"][2] - n["bounds"][0] > 200), None)
        if patt is not None:
            kind, pattern_bounds = "pattern", patt["bounds"]
            break
        if "pin area" in descs or {"1", "2", "3"} <= {n["desc"] for n in nodes}:
            kind = "pin"
            break
        if any("EditText" in n["cls"] for n in nodes if n["pkg"].startswith("com.android.systemui")):
            kind = "password"
            break
        shell("input keyevent 224")
        time.sleep(0.8)
    if kind is None:
        raise PhoneError("Could not bring up the lock screen's PIN/password/pattern entry.")
    if (kind == "pattern") != (pattern is not None):
        raise PhoneError(f"The lock screen asks for a {kind}, but the saved secret is a "
                         f"{'pattern' if pattern else 'PIN/password'}. Nothing was entered.")
    if in_call() or not lockscreen_in_front():
        # A call (or any app) came to the front while the bouncer was opening -- never type into it.
        raise PhoneError("Something other than the lock screen is in front (call?); nothing was entered.")
    if kind == "pattern":
        _draw_pattern(pattern, pattern_bounds)
    else:
        shell("input text " + shlex.quote(secret))
        time.sleep(0.4)
        shell("input keyevent 66")
    for _ in range(8):
        time.sleep(0.6)
        if not screen_state()["locked"]:
            return "unlocked"
    # Pause only when Android itself says the PIN was wrong. If the entry never registered (pocket
    # mode / proximity sensor blocking touches, the bouncer closing), Android counted nothing, so
    # stopping auto-unlock for days -- as happened -- protects nothing.
    try:
        shown = " ".join(n["text"] + " " + n["desc"] for n in dump_screen()).lower()
    except PhoneError:
        shown = ""
    shell("input keyevent 4")
    if any(w in shown for w in ("wrong", "incorrect", "try again in", "attempts")):
        pause_unlock()
        raise PhoneError("The phone said the saved PIN is wrong. Automatic unlock is paused (to avoid "
                         "Android's lockout) until you next unlock the phone by hand.")
    raise PhoneError("The phone did not unlock, but no wrong-PIN message was shown (touches blocked? "
                     "phone in a pocket?). Will try again later.")


def unlock_paused() -> bool:
    return UNLOCK_BLOCK_FILE.exists()


def pause_unlock() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    UNLOCK_BLOCK_FILE.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))


def resume_unlock() -> None:
    UNLOCK_BLOCK_FILE.unlink(missing_ok=True)


def lock() -> bool:
    """Lock the phone now. The POWER key (not SLEEP) honours 'power button instantly locks', so
    there is no unlocked-but-dark gap of the lock-after-timeout delay. Returns True once locked."""
    if screen_state()["awake"]:
        shell("input keyevent 26")
    else:
        shell("input keyevent 223")
    for _ in range(6):
        time.sleep(0.5)
        if screen_state()["locked"]:
            return True
    return False


# ---------------------------------------------------------------- actions
def tap_xy(x: int, y: int) -> None:
    shell(f"input tap {int(x)} {int(y)}")


def type_text(text: str) -> None:
    focused = [n for n in dump_screen() if n["focused"]]
    if any(n["password"] for n in focused):
        raise PhoneError("Refused: the focused field is a password field. Agents never type passwords; "
                         "the user must enter it (or use the phone's autofill).")
    # `input text` treats spaces specially and the device shell parses the rest.
    escaped = text.replace("%", "%%").replace(" ", "%s")
    shell("input text " + shlex.quote(escaped))


def swipe(direction: str) -> None:
    size = shell("wm size")
    m = re.search(r"(\d+)x(\d+)", size)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)
    cx, cy = w // 2, h // 2
    dx, dy = {"up": (0, -h // 3), "down": (0, h // 3), "left": (-w // 3, 0), "right": (w // 3, 0)}[direction]
    # "swipe up" = finger moves up = content scrolls down (reveals what is below).
    shell(f"input swipe {cx - dx // 2} {cy - dy // 2} {cx + dx // 2} {cy + dy // 2} 300")


def open_app(package: str) -> None:
    out = shell(f"monkey -p {shlex.quote(package)} -c android.intent.category.LAUNCHER 1")
    if "No activities found" in out or "monkey aborted" in out:
        raise PhoneError(f"Could not launch {package} (not installed?)")


def wait_text(text: str, timeout: float) -> dict:
    deadline = time.time() + timeout
    needle = text.lower()
    while time.time() < deadline:
        for n in visible_elements(dump_screen()):
            if needle in n["text"].lower() or needle in n["desc"].lower():
                return n
        time.sleep(1.0)
    raise PhoneError(f"Timed out after {timeout:.0f}s waiting for '{text}'")


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="phone.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("connect")
    sub.add_parser("current")
    s = sub.add_parser("screen")
    s.add_argument("--all", action="store_true")
    s.add_argument("--json", action="store_true")
    t = sub.add_parser("tap")
    t.add_argument("index", nargs="?", type=int)
    t.add_argument("--text")
    t.add_argument("--desc")
    t.add_argument("--force", action="store_true")
    xy = sub.add_parser("tap-xy")
    xy.add_argument("x", type=int)
    xy.add_argument("y", type=int)
    ty = sub.add_parser("type")
    ty.add_argument("text")
    k = sub.add_parser("key")
    k.add_argument("name", choices=sorted(KEYS))
    sw = sub.add_parser("swipe")
    sw.add_argument("direction", choices=["up", "down", "left", "right"])
    o = sub.add_parser("open")
    o.add_argument("package")
    a = sub.add_parser("apps")
    a.add_argument("filter", nargs="?", default="")
    w = sub.add_parser("wait")
    w.add_argument("--text", required=True)
    w.add_argument("--timeout", type=float, default=15)
    sub.add_parser("set-unlock-pin", help="save the lock-screen PIN or password (you type it; not echoed)")
    sub.add_parser("set-unlock-pattern", help="save the lock-screen pattern as dot numbers 1-9 (not echoed)")
    sub.add_parser("clear-unlock-pin")
    sub.add_parser("reset-unlock", help="allow automatic unlock again after a failed attempt")
    args = p.parse_args(argv)

    try:
        if args.cmd == "connect":
            print(connect())
            return 0
        if args.cmd in ("set-unlock-pin", "set-unlock-pattern"):
            import getpass
            if not sys.stdin.isatty():
                raise SystemExit("Run this yourself in the Termux app so you can type it.")
            if args.cmd == "set-unlock-pattern":
                print("Number the dots like a keypad: 1 2 3 / 4 5 6 / 7 8 9, and type your pattern's dots "
                      "in order (e.g. an L shape is 14789).")
                prompt = "Pattern dots (not shown): "
            else:
                prompt = "Lock-screen PIN or password (not shown): "
            first = getpass.getpass(prompt)
            again = getpass.getpass("Again to confirm: ")
            if not first or first != again:
                raise SystemExit("They did not match; nothing saved.")
            if args.cmd == "set-unlock-pattern":
                if not re.fullmatch(r"[1-9]{4,9}", first) or len(set(first)) != len(first):
                    raise SystemExit("A pattern is 4-9 different dots numbered 1-9; nothing saved.")
                first = "pattern:" + first
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(CONFIG_DIR, 0o700)
            fd = os.open(PIN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(first)
            UNLOCK_BLOCK_FILE.unlink(missing_ok=True)
            print(f"Saved (readable only by Termux): {PIN_FILE}")
            return 0
        if args.cmd == "clear-unlock-pin":
            PIN_FILE.unlink(missing_ok=True)
            print("Saved unlock PIN deleted.")
            return 0
        if args.cmd == "reset-unlock":
            UNLOCK_BLOCK_FILE.unlink(missing_ok=True)
            print("Automatic unlock allowed again.")
            return 0
        ensure_connected()
        if args.cmd in ("tap", "tap-xy", "type", "key", "swipe", "open") and in_call() \
                and not getattr(args, "force", False):
            raise PhoneError("A phone call is in progress -- not tapping or typing (keys can become "
                             "keypad tones in the call). Try again after the call.")
        if args.cmd == "status":
            st = screen_state()
            print(json.dumps({"adb": SERIAL, "connected": True, **st, "foreground": foreground()}))
        elif args.cmd == "current":
            print(foreground())
        elif args.cmd == "screen":
            elems = visible_elements(dump_screen(), args.all)
            save_screen(elems)
            if args.json:
                print(json.dumps(elems))
            else:
                print(f"# {foreground()}  ({len(elems)} elements; tap with: phone.py tap N)")
                for e in elems:
                    print(describe(e))
        elif args.cmd == "tap":
            if args.index is not None:
                elems = load_screen()
                if not 0 <= args.index < len(elems):
                    raise PhoneError(f"No element [{args.index}] on the saved screen.")
                target = elems[args.index]
            elif args.text or args.desc:
                target = find_by(visible_elements(dump_screen()), args.text, args.desc)
            else:
                raise PhoneError("tap needs an index, --text or --desc")
            label = target["text"] or target["desc"]
            check_allowed(label, args.force)
            tap_xy(*target["center"])
            print(f"tapped [{target.get('i', '?')}] \"{label}\" @{target['center'][0]},{target['center'][1]}")
        elif args.cmd == "tap-xy":
            tap_xy(args.x, args.y)
            print(f"tapped @{args.x},{args.y}")
        elif args.cmd == "type":
            type_text(args.text)
            print(f"typed {len(args.text)} characters")
        elif args.cmd == "key":
            shell(f"input keyevent {KEYS[args.name]}")
            print(f"pressed {args.name}")
        elif args.cmd == "swipe":
            swipe(args.direction)
            print(f"swiped {args.direction}")
        elif args.cmd == "open":
            open_app(args.package)
            print(f"opened {args.package}")
        elif args.cmd == "apps":
            pkgs = sorted(l.split(":", 1)[1] for l in shell("pm list packages -3").splitlines() if ":" in l)
            print("\n".join(p for p in pkgs if args.filter.lower() in p.lower()))
        elif args.cmd == "wait":
            n = wait_text(args.text, args.timeout)
            print(f"found \"{n['text'] or n['desc']}\" @{n['center'][0]},{n['center'][1]}")
        return 0
    except PhoneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
