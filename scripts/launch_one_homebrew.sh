#!/usr/bin/env bash
# Kills any previous PX4 instance, resets the vehicle's pose if its model
# already exists in Gazebo, then (re)launches a single PX4 instance
# (instance 0) against an already-running Gazebo world (see
# scripts/launch_gazebo.sh). Re-run this any time you want to reset the
# vehicle's pose. Teleporting a running PX4's rigid body crashes its EKF (a
# PX4 limitation, not fixable from here), so a full PX4 restart is the only
# way to reset pose - this script makes that restart cheap by never
# touching the (slow-to-load) Gazebo world itself.
#
# On the very first run against a given Gazebo instance, no model exists
# yet, so this spawns one (PX4's normal path). On every run after that, the
# model from the previous run is still sitting in Gazebo, already reset by
# lib/kill_all_px4_instances.sh below - deliberately not removed, see that
# script for why - so this attaches PX4 to the existing model
# (`PX4_GZ_MODEL_NAME`) rather than spawning a new one. See
# lib/homebrew_instance.sh for both halves of this (launch_px4).
#
# To reset the EKF origin manually after launch:
#   $PX4_DIR/build/px4_sitl_default/bin/px4-commander set_ekf_origin <lat> <lon> <alt>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/sitl_env.sh"
source "$SCRIPT_DIR/lib/homebrew_instance.sh"

require_dir "$PX4_DIR/build/px4_sitl_default" "Error: no PX4 SITL build found. Run scripts/build_px4.sh first."

# Must NOT let PX4 discover no world is running and launch its own - if it
# did, Gazebo would end up as a child of *this* instance's process group,
# and killing this instance (e.g. to reset pose) would take Gazebo down
# with it, defeating the entire point of splitting these scripts apart.
if ! gz service -i --service "/world/$PX4_GZ_WORLD/scene/info" 2>&1 | grep -q "Service providers"; then
    echo "Error: Gazebo isn't running (world '$PX4_GZ_WORLD' not found)." >&2
    echo "  Run scripts/launch_gazebo.sh first, then re-run this script." >&2
    exit 1
fi

echo "[*] Killing any previous PX4 instance..."
"$SCRIPT_DIR/lib/kill_all_px4_instances.sh"

# --- Launch sequence ---

# Matches PX4's own gz_<model>_<world> make target's WORKING_DIRECTORY, so
# dataman/logs/etc. land in the same place a `make` launch would put them.
cd "$PX4_DIR/build/px4_sitl_default/rootfs"

launch_px4 0
wait_for_ready 0

echo "[+] PX4 instance 0 is ready! Ctrl-C to stop (Gazebo keeps running)."

# px4 runs in its own session (via setsid in launch_px4), so it's no longer
# a child of this shell - Ctrl-C here won't reach it on its own, and a bare
# `wait` would return immediately instead of blocking on it. Trap the
# interrupt and clean up explicitly instead.
trap '"$SCRIPT_DIR/lib/kill_all_px4_instances.sh"; exit 0' INT TERM

while kill -0 "-$(cat /tmp/px4_instance_0.pid 2>/dev/null)" 2>/dev/null; do
    # PX4 itself doesn't notice Gazebo is gone right away - it sits waiting
    # on its lockstep connection until its own internal timeout finally
    # kills it, so without this check the user just sees this script hang
    # for a while after Ctrl-C'ing launch_gazebo.sh's terminal, then the
    # generic "exited unexpectedly" message below. Checking Gazebo's own
    # pidfile catches it within one poll interval instead.
    if ! kill -0 "-$(cat /tmp/gz_sim.pid 2>/dev/null)" 2>/dev/null; then
        echo "[!] Gazebo has already quit. Stopping PX4 instance 0 too." >&2
        "$SCRIPT_DIR/lib/kill_all_px4_instances.sh"
        exit 1
    fi
    sleep 1
done
echo "[!] PX4 instance 0 exited unexpectedly. Check /tmp/px4_instance_0.log" >&2
exit 1
