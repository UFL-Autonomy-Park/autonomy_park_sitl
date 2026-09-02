#!/usr/bin/env bash
# One-time setup: run this once, right after cloning the repo. Installs Git
# LFS (if needed) and pulls its assets, and initializes all submodules
# (including PX4's own nested submodules such as NuttX and MAVLink).
set -euo pipefail

trap 'echo "ERROR: init.sh failed at line $LINENO: \"$BASH_COMMAND\"" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/sitl_env.sh"

echo "############################################################"
echo "#  First-time setup takes about 20 minutes. Go grab a       #"
echo "#  coffee.                                                  #"
echo "############################################################"
echo

echo "==> Checking sudo access (several steps below need it to install packages)..."
if ! sudo -v; then
    echo "ERROR: could not get sudo access. This is a local machine/policy issue," >&2
    echo "  not something this script controls. If sudo hung above rather than" >&2
    echo "  failing outright, try restarting your terminal (or your machine)" >&2
    echo "  before re-running this script." >&2
    exit 1
fi

echo "==> [1/10] Installing Git LFS and fetching assets (custom meshes/textures)..."
if ! command -v git-lfs >/dev/null 2>&1; then
    curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | sudo bash
    sudo apt-get install -y git-lfs
    git lfs install
fi
git -C "$PROJECT_ROOT" lfs install --local
git -C "$PROJECT_ROOT" lfs pull

echo "==> [2/10] Initializing and updating submodules (including nested ones, e.g. aero_common's own submodules)..."
git -C "$PROJECT_ROOT" submodule update --init --recursive

echo "==> [3/10] Installing colcon (needed to build ros2_ws/)..."
sudo apt-get install -y python3-colcon-common-extensions

echo "==> [4/10] Installing MAVROS..."
sudo apt-get install -y ros-humble-mavros ros-humble-mavros-extras ros-humble-mavros-msgs

echo "==> [5/10] Installing MAVROS's GeographicLib datasets..."

# Force a fresh download by clearing ALL files matching the prefix
# (including .tar.bz2 or .part leftovers), not just the final .pgm
sudo rm -f /usr/share/GeographicLib/geoids/egm96-5*
sudo rm -f /usr/share/GeographicLib/gravity/egm96*
sudo rm -f /usr/share/GeographicLib/magnetic/emm2015*

curl -LsSf https://raw.githubusercontent.com/mavlink/mavros/ros2/mavros/scripts/install_geographiclib_datasets.sh | sudo bash

GEOID_FILE="/usr/share/GeographicLib/geoids/egm96-5.pgm"
GEOID_EXPECTED_SIZE=18671448  # confirmed against a known-good install

if [[ "$(stat -c%s "$GEOID_FILE" 2>/dev/null || echo 0)" != "$GEOID_EXPECTED_SIZE" ]]; then
    echo "ERROR: GeographicLib egm96-5 geoid dataset download failed or is incomplete." >&2
    echo "  Check your network connection and re-run this script." >&2
    exit 1
fi

# Max's old step 5 code
#echo "==> [5/10] Installing MAVROS's GeographicLib datasets..."
# Always force a fresh download - the upstream installer skips downloading
# if a file named egm96-5* already exists, even a truncated leftover from a
# previous failed/interrupted run (it only checks presence, not
# completeness). That let a corrupt download go unnoticed here and instead
# crash mavros_node/px4_telemetry_node later at runtime with "File has the
# wrong length ... egm96-5.pgm" (seen in the wild on a fresh clone).
# GEOID_FILE="/usr/share/GeographicLib/geoids/egm96-5.pgm"
# sudo rm -f "$GEOID_FILE"
# curl -LsSf https://raw.githubusercontent.com/mavlink/mavros/ros2/mavros/scripts/install_geographiclib_datasets.sh | sudo bash
# GEOID_EXPECTED_SIZE=18671448  # confirmed against a known-good install
# if [[ "$(stat -c%s "$GEOID_FILE" 2>/dev/null || echo 0)" != "$GEOID_EXPECTED_SIZE" ]]; then
#     echo "ERROR: GeographicLib egm96-5 geoid dataset download failed or is incomplete." >&2
#     echo "  Check your network connection and re-run this script." >&2
#     exit 1
# fi

echo "==> [6/10] Installing geodesy (needed by aero_common)..."
sudo apt-get install -y ros-humble-geodesy

echo "==> [7/10] Verifying PX4-Autopilot checkout..."
echo "    PX4-Autopilot is ready at $(git -C "$PX4_DIR" describe --tags HEAD 2>/dev/null || git -C "$PX4_DIR" rev-parse --short HEAD)"

echo "==> [8/10] Installing PX4's own SITL build dependencies..."
sudo "$PX4_DIR/Tools/setup/ubuntu.sh"

# ubuntu.sh above makes its own best-effort attempt at these too, but that
# runs as root (via sudo) with root's own PATH, so it can't see - and won't
# reliably install into - the venv_host virtualenv set_env.sh activated when
# this script started. This is the step that actually matters: installing
# into that already-active venv, as our own (non-root) user, no --user flag
# needed (or accepted - pip errors if you pass --user inside a venv).
echo "==> [9/10] Installing PX4's Python build dependencies into venv_host..."
pip3 install -r "$PX4_DIR/Tools/setup/requirements.txt"

# mkdir -p (not plain mkdir) so re-running this doesn't fail on an existing
# build dir - cmake/make are themselves safe to re-run against one.
echo "==> [10/10] Building Micro-XRCE-DDS-Agent..."
mkdir -p "$PROJECT_ROOT/Micro-XRCE-DDS-Agent/build"
(
    cd "$PROJECT_ROOT/Micro-XRCE-DDS-Agent/build"
    cmake ..
    make
    sudo make install
)
sudo ldconfig /usr/local/lib/

echo
echo "Setup complete. Next: scripts/build_px4.sh to build PX4 SITL."
