#!/usr/bin/env bash
# Kills every PX4 instance spawned by launch_one_homebrew.sh and
# resets its vehicle model to a clean resting pose, but leaves Gazebo -
# and the model itself - otherwise alone (see lib/kill_gazebo.sh to also
# stop Gazebo itself).
#
# Internal helper, called by launch_one_homebrew.sh - safe to run directly
# too (e.g. to stop PX4 without restarting Gazebo), but you'll usually just
# re-run launch_one_homebrew.sh instead, which calls this first.
#
# Deliberately does NOT remove the vehicle model from Gazebo. It's tempting
# to think it should (a "reset" sounds like it should clean up after
# itself), but Gazebo Harmonic's rendering engine reliably crashes (Ogre2
# assert, observed repeatedly while developing this script) when a model
# with camera/depth-camera sensors is removed and a same-named one created
# shortly after - so the model is left in place and reset in place instead
# (see lib/homebrew_instance.sh's reset_model), which never touches
# that crash-prone code path. See launch_one_homebrew.sh for the
# other half of this (attaching PX4 to the model this leaves behind, rather
# than spawning a new one).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../sitl_env.sh"
source "$SCRIPT_DIR/process.sh"
source "$SCRIPT_DIR/homebrew_instance.sh"

# Any in-flight rise-controller experiment is about to be flying against a
# vehicle that's either gone or getting reset out from under it - kill it
# first rather than leave it streaming setpoints at a dead/reset instance.
echo "[*] Killing any running rise-controller experiment (vehicle is about to reset)..."
"$SCRIPT_DIR/kill_rise_controller.sh"

shopt -s nullglob

# 1. Kill every PX4 process we started (by its pidfile's process group).
for pidfile in /tmp/px4_instance_*.pid; do
    instance="$(basename "$pidfile" .pid)"
    instance="${instance#px4_instance_}"
    kill_pidfile_group "$pidfile" "PX4 instance $instance"
done

# 2. Reset every vehicle model that's actually in the running Gazebo world.
# Unconditional on purpose: don't infer whether a model "needs" resetting
# from whether a pidfile survived. PX4 can exit (crash, SIGKILL, a killed
# terminal) without its pidfile being cleaned up, and a model left behind
# by an earlier session has no pidfile here at all - either way the model
# is still sitting under the last rotor thrust PX4 commanded and must be
# reset. reset_model is idempotent and a no-op when nothing is there.
for instance in $(instances_with_models); do
    echo "[*] Resetting model for instance $instance..."
    reset_model "$instance"
done

exit 0
