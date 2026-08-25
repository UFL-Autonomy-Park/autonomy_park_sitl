#!/usr/bin/env bash
# Builds every package under ros2_ws/src (aero_common, px4_msgs, etc.) with
# colcon. Run this once after cloning/updating submodules, then re-run
# after changing any ROS 2 package source. Run scripts/launch_ros2_autonomy_stack.sh
# to launch it afterward.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/sitl_env.sh"

require_dir "$ROS2_DIR/src/aero_common" "Error: ros2_ws/src/aero_common not found. Run scripts/init.sh first."

echo "[*] Will not check if you have already installed ros2. Assumed installed."

echo "[*] Building ros2_ws/src with colcon..."
( cd "$ROS2_DIR" && colcon build --symlink-install )

echo "[+] Build complete. Run scripts/launch_ros2_autonomy_stack.sh to launch it."
