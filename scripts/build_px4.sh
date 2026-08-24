#!/usr/bin/env bash
# Rebuilds PX4 SITL from a clean state after changing px4-additions/
# (world, model, or airframe params). Run this, then
# scripts/spawn_one_homebrew_instance.sh (Gazebo, if already running via
# scripts/launch_gazebo.sh, is left running - only the PX4 binary changes
# here; see the NOTE below about restarting Gazebo too if the world/models
# changed).
#
# Steps: kill any running PX4 instance (leaving Gazebo itself untouched),
# sync px4-additions/ into PX4-Autopilot, wipe the stale build dir (required
# so CMake re-globs the new world/airframe files - see
# library/write_px4_with_px4_additions.sh), and rebuild.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/library/set_env.sh"

echo "[*] Killing any running PX4 instance..."
"$SCRIPT_DIR/kill_all_homebrew_instances.sh"

echo "[*] Syncing px4-additions/ into PX4-Autopilot..."
"$SCRIPT_DIR/library/write_px4_with_px4_additions.sh"

echo "[*] Removing stale build directory..."
rm -rf "$PX4_DIR/build"

echo "[*] Building PX4 SITL ($PX4_MAKE_TARGET)..."
make -C "$PX4_DIR" $PX4_MAKE_TARGET

echo "[+] Build complete. Refer back to the README.md for next steps."
