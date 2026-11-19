#!/data/data/com.termux/files/usr/bin/bash
# Install or update the custom Hermes fork on Android (Termux).
#
#   bash install-custom.sh            # install/update from the default fork + branch
#   FORK_URL=... FORK_BRANCH=... bash install-custom.sh
#
# 1. Makes sure the official runtime (hermes-agent, canary APT channel) is installed.
# 2. Clones or fast-forwards the fork into ~/hermes-custom (shallow).
# 3. Installs the hermes-custom launcher into $PREFIX/bin.
set -euo pipefail
# This file lives inside the checkout it updates; bash reads scripts incrementally, so a
# checkout that rewrites it mid-run would execute a mix of old and new lines. Run from a copy.
if [ -z "${INSTALL_CUSTOM_COPY:-}" ]; then
  copy="${TMPDIR:-/data/data/com.termux/files/usr/tmp}/install-custom.$$.sh"
  cp "$0" "$copy"
  INSTALL_CUSTOM_COPY=1 exec bash "$copy" "$@"
fi
trap 'rm -f "$0"' EXIT
FORK_URL="${FORK_URL:-https://github.com/xkaitoxX/hermes-agent.git}"
FORK_BRANCH="${FORK_BRANCH:-android}"
SRC="${HERMES_CUSTOM_SRC:-$HOME/hermes-custom}"
KEY_FPR="C572B5FDD1A29CCFA9A912B6840B0848E139156D"
CANARY="https://hermes-assets.nousresearch.com/releases/termux/canary"

if [ ! -x "$PREFIX/lib/hermes-agent/venv/bin/python" ]; then
  echo "== Installing the Hermes runtime (canary channel)"
  pkg install -y curl gnupg git
  mkdir -p "$PREFIX/etc/apt/keyrings" "$PREFIX/etc/apt/sources.list.d"
  curl -fsSL "$CANARY/key.asc" -o "$PREFIX/etc/apt/keyrings/hermes-agent.asc"
  fpr=$(gpg --show-keys --with-colons "$PREFIX/etc/apt/keyrings/hermes-agent.asc" | awk -F: '/^fpr/ {print $10; exit}')
  [ "$fpr" = "$KEY_FPR" ] || { echo "Signing key fingerprint mismatch ($fpr) - aborting"; rm -f "$PREFIX/etc/apt/keyrings/hermes-agent.asc"; exit 1; }
  echo "deb [signed-by=$PREFIX/etc/apt/keyrings/hermes-agent.asc] $CANARY hermes-canary main" > "$PREFIX/etc/apt/sources.list.d/hermes-agent.list"
  pkg update -y
  pkg install -y hermes-agent
fi

echo "== Phone tools for the android skills (python, adb, termux-api)"
missing=""
command -v python >/dev/null 2>&1 || missing="$missing python"
command -v adb >/dev/null 2>&1 || missing="$missing android-tools"
command -v termux-notification >/dev/null 2>&1 || missing="$missing termux-api"
command -v git >/dev/null 2>&1 || missing="$missing git"
if [ -n "$missing" ]; then
  pkg install -y $missing
fi

echo "== Fetching fork $FORK_URL ($FORK_BRANCH) into $SRC"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch --depth 1 origin "$FORK_BRANCH"
  git -C "$SRC" checkout -q -B "$FORK_BRANCH" FETCH_HEAD
else
  git clone --depth 1 --branch "$FORK_BRANCH" "$FORK_URL" "$SRC"
fi

echo "== Installing launcher"
install -m 0755 "$SRC/scripts/termux/custom/hermes-custom" "$PREFIX/bin/hermes-custom"

# A gateway left running from before the update keeps executing the old code in memory;
# always stop it (a no-op when none runs) so the next turn starts one from the updated checkout.
echo "== Syncing bundled skills (adds new ones such as skills/android/*)"
hermes-custom --run-module tools.skills_sync 2>&1 | tail -1 || true

echo "== Restarting the gateway onto the updated code"
hermes-custom gateway stop >/dev/null 2>&1 || true
if ps -eo args 2>/dev/null | grep -q "[h]ermes_cli.main .*gateway run"; then
  pkill -f "hermes_cli.main .*gateway run" 2>/dev/null || true
fi

echo "== Versions"
echo "runtime: $(hermes --version 2>/dev/null | head -1)"
echo "custom:  $(hermes-custom --version 2>/dev/null | head -1)  [$(git -C "$SRC" log -1 --format='%h %s')]"
