#!/usr/bin/env bash
# Shared environment and helper functions for autonomy_park_sitl scripts.
# Must be *sourced*, not executed: `source scripts/set_env.sh`.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: set_env.sh must be sourced, not executed." >&2
    echo "  Run: source ${BASH_SOURCE[0]}" >&2
    exit 1
fi

# --- Project root -------------------------------------------------------
#
# Resolved from $PWD (not this script's location) so it stays correct no
# matter which directory the caller happened to `cd` into, e.g. deep inside
# PX4-Autopilot/build/. Preference order:
#   1. $PWD contains "autonomy_park_sitl" -> root is that directory.
#   2. $PWD contains "scripts"            -> root is one directory back.
#   3. Otherwise                          -> root is $PWD itself.
determine_project_root() {
    if [[ "$PWD" == *autonomy_park_sitl* ]]; then
        echo "${PWD%%autonomy_park_sitl*}autonomy_park_sitl"
    elif [[ "$PWD" == *scripts* ]]; then
        local before_scripts="${PWD%%scripts*}"
        echo "${before_scripts%/}"
    else
        echo "$PWD"
    fi
}
export PROJECT_ROOT="$(determine_project_root)"

# --- Shared helper functions ---------------------------------------------

# require_dir PATH [ERROR_MSG] - exits with an error unless PATH is a directory.
require_dir() {
    local path="$1"
    local msg="${2:-Error: directory '$path' not found.}"
    if [[ ! -d "$path" ]]; then
        echo "$msg" >&2
        exit 1
    fi
}

# dir_is_empty PATH - true if PATH has no entries (or doesn't exist).
dir_is_empty() {
    local path="$1"
    local entries=("$path"/*)
    [[ ! -e "${entries[0]}" ]]
}

# copy_contents SRC DEST - copies SRC's contents into DEST, requiring DEST
# to already exist and SRC to be non-empty.
copy_contents() {
    local src="$1" dest="$2"
    require_dir "$dest" "Error: destination directory '$dest' not found (unexpected PX4-Autopilot layout?)."
    if dir_is_empty "$src"; then
        echo "Error: '$src' is empty, nothing to copy." >&2
        exit 1
    fi
    cp -r "$src"/* "$dest/"
}

# --- PX4 SITL configuration ------------------------------------------------

# PX4 SITL home position (middle of the Autonomy Park)
export PX4_HOME_LAT=29.628147
export PX4_HOME_LON=-82.360333
export PX4_HOME_ALT=0.0

# Custom Gazebo world/model, added via px4-additions/ (see write_px4_with_px4_additions.sh)
export PX4_GZ_WORLD=autonomy_park
export PX4_SIMULATOR=gz
export PX4_SIM_MODEL=gz_homebrew
export PX4_SYS_AUTOSTART=4025
export PX4_GZ_MODEL_POSE="3.0,0,0.5,0,0,0"

# PX4's `make` target for this world/model combo (see rebuild_px4.sh)
export PX4_MAKE_TARGET="px4_sitl gz_homebrew_autonomy_park"

export PX4_DIR="$PROJECT_ROOT/PX4-Autopilot"
export PX4_ADDITIONS_DIR="$PROJECT_ROOT/px4-additions"
export ROS2_DIR="$PROJECT_ROOT/ros2_ws"
