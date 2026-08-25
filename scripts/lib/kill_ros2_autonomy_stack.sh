#!/usr/bin/env bash
# Kills the ROS 2 autonomy stack (MAVROS, px4_telemetry, px4_teleop,
# px4_safety_lib, autonomy_park_viz) launched by this project's scripts, and
# only those - not any other ROS 2 nodes running on the machine.
#
# launch_ros2_autonomy_stack.sh launches `ros2 launch` via `setsid`, which
# puts it (and every node it spawns as a child) in a new session whose PGID
# equals the launch process's own PID. That PID is recorded in
# /tmp/ros2_autonomy_stack.pid. See lib/process.sh for why PGID-based
# killing is used instead of pattern-matching process names/command lines.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/process.sh"

kill_pidfile_group /tmp/ros2_autonomy_stack.pid "ROS 2 autonomy stack"
exit 0
