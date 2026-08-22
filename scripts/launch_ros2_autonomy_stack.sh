#!/usr/bin/env bash
# Launches the ROS 2 autonomy stack (MAVROS, px4_telemetry, px4_teleop,
# px4_safety_lib, autonomy_park_viz) against a running PX4 SITL instance.
# Run scripts/build_ros2_autonomy_stack.sh first if ros2_ws/ hasn't been
# built, then scripts/launch_gazebo.sh - this script connects to it over
# MAVLink at udp://:14540@127.0.0.1:14580 and will hang waiting for a
# connection if nothing is listening there yet.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/library/set_env.sh"

require_dir "$ROS2_DIR/src/aero_common" "Error: ros2_ws/src/aero_common not found. Run scripts/init.sh first."

echo "[*] Will not check if you have already installed ros2. Assumed installed."

# colcon's generated setup.bash reads $COLCON_TRACE (and friends, via
# nested local_setup.bash files) without a default, which trips `set -u`.
set +u
source "$ROS2_DIR/install/setup.bash"
set -u

echo "[*] Launching ROS 2 autonomy stack..."
ros2 launch minimal_startup_air singleagent_homebrew_teleop.launch.py
