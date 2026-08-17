#!/usr/bin/env bash
# Shared environment for autonomy_park_sitl scripts.
# Must be *sourced*, not executed: `source scripts/set_env.sh`.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: set_env.sh must be sourced, not executed." >&2
    echo "  Run: source ${BASH_SOURCE[0]}" >&2
    exit 1
fi

# Determine script directory regardless of symlinks
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Determine project root based on invocation location
if [[ "$(basename "$SCRIPT_DIR")" == "scripts" ]]; then
    export PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    export PROJECT_ROOT="$SCRIPT_DIR"
fi

# PX4 SITL home position (Autonomy Park, UF campus)
export PX4_HOME_LAT=29.6282703
export PX4_HOME_LON=-82.3606036
export PX4_HOME_ALT=30.861857569478296

# Custom Gazebo world/model, added via px4-additions/ (see write_px4_with_px4_additions.sh)
export PX4_GZ_WORLD=autonomy_park
# NOTE: keep the "gz_" prefix — rcS matches this against the airframe
# filename (4025_gz_homebrew) verbatim; px4-rc.gzsim strips the prefix
# itself to get the bare Tools/simulation/gz/models/ directory name.
export PX4_SIM_MODEL=gz_homebrew
export PX4_SYS_AUTOSTART=4025
export PX4_GZ_MODEL_POSE="3.0,20.0,0.05,0,0,0"

export PX4_DIR="$PROJECT_ROOT/PX4-Autopilot"
export PX4_ADDITIONS_DIR="$PROJECT_ROOT/px4-additions"
export ROS2_DIR="$PROJECT_ROOT/ros2_ws"
