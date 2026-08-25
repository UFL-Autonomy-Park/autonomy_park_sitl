#!/usr/bin/env bash
# !!! NUCLEAR OPTION -- READ THIS BEFORE RUNNING !!!
#
# Forcefully SIGKILLs every Gazebo/PX4/ROS 2 process this project's scripts
# can start, by matching command lines. Unlike every other kill_*.sh script
# in this project, this one does NOT track PIDs via a pidfile, does NOT try
# SIGTERM first, and does NOT give any process a chance to shut down on its
# own. It is the last resort for when something is stuck badly enough that
# the polite, pidfile-tracked scripts (kill_rise_controller.sh,
# lib/kill_ros2_autonomy_stack.sh, lib/kill_all_px4_instances.sh,
# lib/kill_gazebo.sh - all built on lib/process.sh's kill_pidfile_group)
# aren't cutting it - e.g. because a pidfile went stale relative to the
# process it was tracking (this happens: kill_pidfile_group removes its
# pidfile up front, before confirming the kill actually succeeded, so a
# second Ctrl-C landing mid-cleanup, or anything else that clobbers the
# pidfile, can leave the real process alive with nothing left tracking it).
#
# CONSEQUENCES OF RUNNING THIS - READ BEFORE YOU RUN IT:
#   - Any vehicle currently flying will NOT land. Motors cut instantly,
#     mid-air, exactly like a real quad that lost power. Only run this
#     against a vehicle that's already on the ground, or one you've
#     accepted losing.
#   - This matches processes by COMMAND LINE PATTERN across the WHOLE
#     machine, not by pidfile - it will kill every matching process
#     regardless of which terminal/session started it. If you're running
#     more than one instance of this SITL (another terminal, another
#     user), this kills that one too.
#   - SIGKILL cannot be caught or ignored. No cleanup code in any of these
#     processes gets to run - not PX4's, not MAVROS's, not Gazebo's.
#
# Prefer, in order: Ctrl-C the relevant launch_*.sh terminal, or run its
# matching kill_*.sh script directly. Reach for this only when those
# genuinely aren't working.
set -uo pipefail  # NOT -e: individual kills are allowed to fail/no-op

echo "############################################################" >&2
echo "#  NUCLEAR CLEANUP - forcefully SIGKILLing every SITL-      #" >&2
echo "#  related process on this machine, right now.              #" >&2
echo "#  Any vehicle currently flying will NOT land -- motors cut  #" >&2
echo "#  instantly, mid-air. Ctrl-C in the next 3 seconds to abort.#" >&2
echo "############################################################" >&2
sleep 3

PATTERNS=(
    "ros2"
    "mavros"
    "px4_telemetry_node"
    "px4_teleop_node"
    "autonomy_park_viz_node"
    "rviz2"
    "px4"
    "gz"
)

pids_for() { pgrep -f "$1" 2>/dev/null || true; }

for pattern in "${PATTERNS[@]}"; do
    pids="$(pids_for "$pattern")"
    [[ -z "$pids" ]] && continue
    echo "[*] SIGKILL: '$pattern' (PID(s): $pids)"
    # shellcheck disable=SC2086
    kill -KILL $pids 2>/dev/null || true
done

# Not PID tracking - just tidying up stale files these processes' own
# (now-bypassed) pidfile-based kill scripts would otherwise mistake for
# something still worth checking.
rm -f /tmp/rise_controller.pid /tmp/ros2_autonomy_stack.pid /tmp/gz_sim.pid /tmp/px4_instance_*.pid

echo "[*] Restarting the ros2 daemon to clear any stale discovery cache..."
ros2 daemon stop >/dev/null 2>&1 || true

echo "[+] Done. Run 'ros2 topic list' (in a new shell) to confirm a clean slate."
