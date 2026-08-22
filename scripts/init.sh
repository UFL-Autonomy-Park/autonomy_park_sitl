#!/usr/bin/env bash
# One-time setup: run this once, right after cloning the repo. Pulls Git LFS
# assets and initializes all submodules (including PX4's own nested
# submodules such as NuttX and MAVLink).
set -euo pipefail

trap 'echo "ERROR: init.sh failed at line $LINENO: \"$BASH_COMMAND\"" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/library/set_env.sh"

echo "==> Checking sudo access (step 4 needs it to install PX4's build deps)..."
if ! sudo -v; then
    echo "ERROR: could not get sudo access. This is a local machine/policy issue," >&2
    echo "  not something this script controls. If sudo hung above rather than" >&2
    echo "  failing outright, try restarting your terminal (or your machine)" >&2
    echo "  before re-running this script." >&2
    exit 1
fi

echo "==> [1/5] Fetching Git LFS assets (custom meshes/textures)..."
if command -v git-lfs >/dev/null 2>&1; then
    git -C "$PROJECT_ROOT" lfs install --local
    git -C "$PROJECT_ROOT" lfs pull
else
    echo "ERROR: git-lfs is not installed. px4-additions/models/*/meshes/*" >&2
    echo "  and worlds/materials/textures/* would remain empty LFS pointer files," >&2
    echo "  and Gazebo would fail to load the custom model's meshes." >&2
    echo "  Install git-lfs, then re-run this script." >&2
    exit 1
fi

echo "==> [2/5] Initializing and updating submodules (including nested ones, e.g. aero_common's own submodules)..."
git -C "$PROJECT_ROOT" submodule update --init --recursive

echo "==> [3/5] Verifying PX4-Autopilot checkout..."
echo "    PX4-Autopilot is ready at $(git -C "$PX4_DIR" describe --tags HEAD 2>/dev/null || git -C "$PX4_DIR" rev-parse --short HEAD)"

echo "==> [4/5] Installing PX4's own SITL build dependencies..."
sudo "$PX4_DIR/Tools/setup/ubuntu.sh"

# ubuntu.sh above makes its own best-effort attempt at these too, but that
# runs as root (via sudo) with root's own PATH, so it can't see - and won't
# reliably install into - the venv_host virtualenv set_env.sh activated when
# this script started. This is the step that actually matters: installing
# into that already-active venv, as our own (non-root) user, no --user flag
# needed (or accepted - pip errors if you pass --user inside a venv).
echo "==> [5/5] Installing PX4's Python build dependencies into venv_host..."
pip3 install -r "$PX4_DIR/Tools/setup/requirements.txt"

echo
echo "Setup complete. Next: scripts/build_px4.sh to build PX4 SITL."
