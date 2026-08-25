#!/usr/bin/env bash
# Launches the ROS 2 autonomy stack (MAVROS, px4_telemetry, px4_teleop,
# px4_safety_lib, autonomy_park_viz) against a running PX4 SITL instance.
# Run scripts/build_ros2_autonomy_stack.sh first if ros2_ws/ hasn't been
# built, then scripts/launch_gazebo.sh and scripts/launch_one_homebrew.sh
# - this script connects to PX4 over MAVLink at udp://:14540@127.0.0.1:14580
# and will hang waiting for a connection if nothing is listening there yet.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/sitl_env.sh"

require_dir "$ROS2_DIR/src/aero_common" "Error: ros2_ws/src/aero_common not found. Run scripts/init.sh first."

echo "[*] Will not check if you have already installed ros2. Assumed installed."

echo "[*] Killing any leftover ROS 2 autonomy stack processes..."
"$SCRIPT_DIR/lib/kill_ros2_autonomy_stack.sh"

# colcon's generated setup.bash reads $COLCON_TRACE (and friends, via
# nested local_setup.bash files) without a default, which trips `set -u`.
set +u
source "$ROS2_DIR/install/setup.bash"
set -u

pidfile="/tmp/ros2_autonomy_stack.pid"
rm -f "$pidfile"

echo "[*] Launching ROS 2 autonomy stack..."

# setsid puts `ros2 launch` (and every node it spawns as a child) in a new
# session/process group, so lib/kill_ros2_autonomy_stack.sh can kill
# exactly this tree via its PGID - see launch_gazebo.sh's launch_px4() for
# why the pidfile is written from inside the process that execs `ros2`
# rather than trusting `$!`.
setsid bash -c 'echo $$ > "$1"; shift; exec "$@"' _ "$pidfile" \
    ros2 launch minimal_startup_air singleagent_homebrew_teleop.launch.py &
disown

# Wait for the pidfile write, not a fixed sleep - see launch_gazebo.sh.
for _ in $(seq 1 50); do
    [[ -s "$pidfile" ]] && break
    sleep 0.1
done

# `ros2 launch` runs in its own session (via setsid above), so it's no
# longer a child of this shell - `wait $!` would return immediately instead
# of blocking on it (same reason launch_gazebo.sh doesn't use a bare `wait`
# either). Trap the interrupt and clean up explicitly, then poll the PGID.
trap '"$SCRIPT_DIR/lib/kill_ros2_autonomy_stack.sh"; exit 0' INT TERM

while kill -0 "-$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; do
    sleep 1
done
echo "[!] ROS 2 autonomy stack exited unexpectedly." >&2
exit 1
