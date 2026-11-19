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

echo "== Fetching fork $FORK_URL ($FORK_BRANCH) into $SRC"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch --depth 1 origin "$FORK_BRANCH"
  git -C "$SRC" checkout -q -B "$FORK_BRANCH" FETCH_HEAD
else
  git clone --depth 1 --branch "$FORK_BRANCH" "$FORK_URL" "$SRC"
fi

echo "== Installing launcher"
install -m 0755 "$SRC/scripts/termux/custom/hermes-custom" "$PREFIX/bin/hermes-custom"

echo "== Versions"
echo "runtime: $(hermes --version 2>/dev/null | head -1)"
echo "custom:  $(hermes-custom --version 2>/dev/null | head -1)  [$(git -C "$SRC" log -1 --format='%h %s')]"
