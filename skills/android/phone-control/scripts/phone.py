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
DEFAULT_BLOCKLIST = [
    r"\blog ?out\b", r"\bsign ?out\b", r"\bdelete\b", r"\buninstall\b", r"\bfactory reset\b",
    r"\berase\b", r"\bremove account\b", r"\bpay now\b", r"\bbuy\b", r"\bpurchase\b",
    r"\btransfer\b", r"\bsend money\b", r"\bconfirm payment\b",
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
    args = p.parse_args(argv)

    try:
        if args.cmd == "connect":
            print(connect())
            return 0
        ensure_connected()
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
