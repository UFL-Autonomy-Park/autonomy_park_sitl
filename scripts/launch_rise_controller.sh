#!/usr/bin/env bash
# Runs a single aviary_rise_controller experiment against an already-running
# MAVROS + autonomy stack (see scripts/launch_ros2_autonomy_stack.sh) and
# PX4 SITL instance (see scripts/launch_one_homebrew.sh). Stays alive
# for the length of one experiment (takeoff, trajectory, auto-land) -
# Ctrl-C stops it early and still lands the vehicle, since that's handled
# by the node's own `finally` block, not by this script.
#
# Usage: scripts/launch_rise_controller.sh [param_file] [namespace]
#   param_file - a filename under ros2_ws/src/aviary_rise_controller/param/
#                (e.g. baseline_params_1.yaml), or a path to a YAML
#                anywhere else. Defaults to baseline_params_1.yaml.
#   namespace  - must match the namespace singleagent_homebrew_teleop.launch.py
#                gave MAVROS (see launch_ros2_autonomy_stack.sh). Defaults to
#                homebrew_0.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/sitl_env.sh"

PARAM_FILE="${1:-baseline_params_1.yaml}"
NAMESPACE="${2:-homebrew_0}"

# Bare filename -> resolve against this package's own param/ dir; anything
# that already looks like a path (contains a '/') is used as-is.
if [[ "$PARAM_FILE" != */* ]]; then
    PARAM_FILE="$ROS2_DIR/src/aviary_rise_controller/param/$PARAM_FILE"
fi
[[ -f "$PARAM_FILE" ]] || { echo "Error: param file '$PARAM_FILE' not found." >&2; exit 1; }

require_dir "$ROS2_DIR/install/aviary_rise_controller" \
    "Error: aviary_rise_controller isn't built. Run scripts/build_ros2_autonomy_stack.sh first."

if [[ ! -f /tmp/ros2_autonomy_stack.pid ]] || ! kill -0 "-$(cat /tmp/ros2_autonomy_stack.pid)" 2>/dev/null; then
    echo "Error: the ROS 2 autonomy stack isn't running." >&2
    echo "  Run scripts/launch_one_homebrew.sh, then scripts/launch_ros2_autonomy_stack.sh, first." >&2
    exit 1
fi

echo "[*] Killing any leftover rise-controller experiment..."
"$SCRIPT_DIR/lib/kill_rise_controller.sh"

# colcon's generated setup.bash reads $COLCON_TRACE (and friends, via
# nested local_setup.bash files) without a default, which trips `set -u`.
set +u
source "$ROS2_DIR/install/setup.bash"
set -u

pidfile="/tmp/rise_controller.pid"
rm -f "$pidfile"

echo "[*] Launching aviary_rise_controller (namespace=$NAMESPACE, params=$PARAM_FILE)..."

# setsid puts `ros2 launch` (and aviary_rise_node, spawned as its child) in a
# new session/process group, so kill_rise_controller.sh can kill exactly
# this tree via its PGID - see launch_gazebo.sh's launch_px4() for why the
# pidfile is written from inside the process itself rather than trusting `$!`.
setsid bash -c 'echo $$ > "$1"; shift; exec "$@"' _ "$pidfile" \
    ros2 launch aviary_rise_controller rise_controller.launch.py \
    "params_file:=$PARAM_FILE" \
    "namespace:=$NAMESPACE" &
disown

# Wait for the pidfile write, not a fixed sleep - see launch_gazebo.sh.
for _ in $(seq 1 50); do
    [[ -s "$pidfile" ]] && break
    sleep 0.1
done

# `ros2 launch` runs in its own session (via setsid above), so it's no
# longer a child of this shell - Ctrl-C here won't reach it on its own, and
# a bare `wait` would return immediately instead of blocking on it. Trap the
# interrupt and clean up explicitly, then poll the PGID - see
# launch_ros2_autonomy_stack.sh for the same pattern.
trap '"$SCRIPT_DIR/lib/kill_rise_controller.sh"; exit 0' INT TERM

while kill -0 "-$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; do
    sleep 1
done
echo "[!] aviary_rise_controller exited (experiment finished, or it failed - check the output above)."
rm -f "$pidfile"
