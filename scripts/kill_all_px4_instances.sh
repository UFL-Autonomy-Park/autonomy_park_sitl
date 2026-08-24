#!/usr/bin/env bash
# Kills every PX4 instance spawned by spawn_one_homebrew_instance.sh and
# resets its vehicle model to a clean resting pose, but leaves Gazebo -
# and the model itself - otherwise alone (see scripts/library/
# kill_gazebo.sh to also stop Gazebo itself).
#
# Run this directly to stop PX4 (and leave the vehicle in a sane state)
# without restarting Gazebo, or just re-run spawn_one_homebrew_instance.sh,
# which calls this first.
#
# Deliberately does NOT remove the vehicle model from Gazebo. It's tempting
# to think it should (a "reset" sounds like it should clean up after
# itself), but Gazebo Harmonic's rendering engine reliably crashes (Ogre2
# assert, observed repeatedly while developing this script) when a model
# with camera/depth-camera sensors is removed and a same-named one created
# shortly after - so the model is left in place and reset in place instead
# (see library/homebrew_instance.sh's reset_model), which never touches
# that crash-prone code path. See spawn_one_homebrew_instance.sh for the
# other half of this (attaching PX4 to the model this leaves behind, rather
# than spawning a new one).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/library/set_env.sh"
source "$SCRIPT_DIR/library/process.sh"
source "$SCRIPT_DIR/library/homebrew_instance.sh"

shopt -s nullglob
for pidfile in /tmp/px4_instance_*.pid; do
    instance="$(basename "$pidfile" .pid)"
    instance="${instance#px4_instance_}"

    kill_pidfile_group "$pidfile" "PX4 instance $instance"

    echo "[*] Resetting model for instance $instance (if present)..."
    reset_model "$instance"
done

exit 0
