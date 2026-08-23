#!/usr/bin/env bash
# One-time setup: run this once, right after cloning the repo. Installs Git
# LFS (if needed) and pulls its assets, and initializes all submodules
# (including PX4's own nested submodules such as NuttX and MAVLink).
set -euo pipefail

trap 'echo "ERROR: init.sh failed at line $LINENO: \"$BASH_COMMAND\"" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/library/set_env.sh"

echo "==> Checking sudo access (several steps below need it to install packages)..."
if ! sudo -v; then
    echo "ERROR: could not get sudo access. This is a local machine/policy issue," >&2
    echo "  not something this script controls. If sudo hung above rather than" >&2
    echo "  failing outright, try restarting your terminal (or your machine)" >&2
    echo "  before re-running this script." >&2
    exit 1
fi

echo "==> [1/8] Installing Git LFS and fetching assets (custom meshes/textures)..."
if ! command -v git-lfs >/dev/null 2>&1; then
    curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | sudo bash
    sudo apt-get install -y git-lfs
    git lfs install
fi
git -C "$PROJECT_ROOT" lfs install --local
git -C "$PROJECT_ROOT" lfs pull

echo "==> [2/8] Initializing and updating submodules (including nested ones, e.g. aero_common's own submodules)..."
git -C "$PROJECT_ROOT" submodule update --init --recursive

echo "==> [3/8] Verifying PX4-Autopilot checkout..."
echo "    PX4-Autopilot is ready at $(git -C "$PX4_DIR" describe --tags HEAD 2>/dev/null || git -C "$PX4_DIR" rev-parse --short HEAD)"

echo "==> [4/8] Installing PX4's own SITL build dependencies..."
sudo "$PX4_DIR/Tools/setup/ubuntu.sh"

# ubuntu.sh above makes its own best-effort attempt at these too, but that
# runs as root (via sudo) with root's own PATH, so it can't see - and won't
# reliably install into - the venv_host virtualenv set_env.sh activated when
# this script started. This is the step that actually matters: installing
# into that already-active venv, as our own (non-root) user, no --user flag
# needed (or accepted - pip errors if you pass --user inside a venv).
echo "==> [5/8] Installing PX4's Python build dependencies into venv_host..."
pip3 install -r "$PX4_DIR/Tools/setup/requirements.txt"

echo "==> [6/8] Installing MAVROS..."
sudo apt-get install -y ros-humble-mavros ros-humble-mavros-extras ros-humble-mavros-msgs

echo "==> [7/8] Installing MAVROS's GeographicLib datasets..."
curl -LsSf https://raw.githubusercontent.com/mavlink/mavros/ros2/mavros/scripts/install_geographiclib_datasets.sh | sudo bash

echo "==> [8/8] Installing geodesy (needed by aero_common)..."
sudo apt-get install -y ros-humble-geodesy

echo
echo "Setup complete. Next: scripts/build_px4.sh to build PX4 SITL."
