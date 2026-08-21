#!/usr/bin/env bash
# One-time setup: run this once, right after cloning the repo. Pulls Git LFS
# assets and initializes all submodules (including PX4's own nested
# submodules such as NuttX and MAVLink).
set -euo pipefail

trap 'echo "ERROR: init.sh failed at line $LINENO: \"$BASH_COMMAND\"" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> [1/3] Fetching Git LFS assets (custom meshes/textures)..."
if command -v git-lfs >/dev/null 2>&1; then
    git -C "$PROJECT_ROOT" lfs install --local
    git -C "$PROJECT_ROOT" lfs pull
else
    echo "WARNING: git-lfs is not installed. px4-additions/models/*/meshes/*.STL" >&2
    echo "  and worlds/materials/textures/* will remain empty LFS pointer files," >&2
    echo "  and Gazebo will fail to load the custom model's meshes." >&2
    echo "  Install git-lfs, then re-run this script." >&2
fi

echo "==> [2/3] Initializing and updating top-level submodules..."
git -C "$PROJECT_ROOT" submodule update --init --recursive

echo "==> [3/4] Verifying PX4-Autopilot checkout..."
PX4_DIR="$PROJECT_ROOT/PX4-Autopilot"

# Ensure nested submodules within PX4 (NuttX, Mavlink, etc.) are populated
git -C "$PX4_DIR" submodule update --init --recursive

echo "    PX4-Autopilot is ready at $(git -C "$PX4_DIR" describe --tags HEAD 2>/dev/null || git -C "$PX4_DIR" rev-parse --short HEAD)"

echo "==> [4/4] Installing PX4's own SITL build dependencies..."
"$PX4_DIR/Tools/setup/ubuntu.sh"

echo
echo "Setup complete. Next: scripts/rebuild_px4.sh to build PX4 SITL."
