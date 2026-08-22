#!/usr/bin/env bash
# One-time setup: run this once, right after cloning the repo. Pulls Git LFS
# assets and initializes all submodules (including PX4's own nested
# submodules such as NuttX and MAVLink).
set -euo pipefail

trap 'echo "ERROR: init.sh failed at line $LINENO: \"$BASH_COMMAND\"" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"

echo "==> Checking sudo access (step 4 needs it to install PX4's build deps)..."
if ! sudo -v; then
    echo "ERROR: could not get sudo access. This is a local machine/policy issue," >&2
    echo "  not something this script controls. If sudo hung above rather than" >&2
    echo "  failing outright, try restarting your terminal (or your machine)" >&2
    echo "  before re-running this script." >&2
    exit 1
fi

echo "==> [1/4] Fetching Git LFS assets (custom meshes/textures)..."
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

echo "==> [2/4] Initializing and updating submodules (including nested ones, e.g. aero_common's own submodules)..."
git -C "$PROJECT_ROOT" submodule update --init --recursive

echo "==> [3/4] Verifying PX4-Autopilot checkout..."
echo "    PX4-Autopilot is ready at $(git -C "$PX4_DIR" describe --tags HEAD 2>/dev/null || git -C "$PX4_DIR" rev-parse --short HEAD)"

echo "==> [4/4] Installing PX4's own SITL build dependencies..."
"$PX4_DIR/Tools/setup/ubuntu.sh"

echo
echo "Setup complete. Next: scripts/rebuild_px4.sh to build PX4 SITL."
