#!/usr/bin/env bash
# Rebuilds PX4 SITL from a clean state after changing px4-additions/
# (world, model, or airframe params). Run this, then scripts/spawn_sim_env.sh.
#
# Steps: kill any running sim, sync px4-additions/ into PX4-Autopilot,
# wipe the stale build dir (required so CMake re-globs the new
# world/airframe files - see write_px4_with_px4_additions.sh), and rebuild.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"

echo "[*] Killing any running Gazebo/PX4 processes..."
"$SCRIPT_DIR/kill_gz.sh"

echo "[*] Syncing px4-additions/ into PX4-Autopilot..."
"$SCRIPT_DIR/write_px4_with_px4_additions.sh"

echo "[*] Removing stale build directory..."
rm -rf "$PX4_DIR/build"

echo "[*] Building PX4 SITL ($PX4_MAKE_TARGET)..."
make -C "$PX4_DIR" $PX4_MAKE_TARGET

echo "[+] Build complete. Run scripts/spawn_sim_env.sh to launch the sim."
