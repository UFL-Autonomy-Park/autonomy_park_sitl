#!/usr/bin/env bash
# Shared environment and helper functions for autonomy_park_sitl scripts.
# Must be *sourced*, not executed: `source scripts/library/set_env.sh`.

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

# Custom Gazebo world/model, added via px4-additions/ (see library/write_px4_with_px4_additions.sh)
export PX4_GZ_WORLD=autonomy_park
export PX4_SIMULATOR=gz
export PX4_SIM_MODEL=gz_homebrew
export PX4_SYS_AUTOSTART=22000
export PX4_GZ_MODEL_POSE="3.0,0,0.5,0,0,0"

# PX4's `make` config target (see build_px4.sh). Deliberately just
# "px4_sitl", not "px4_sitl gz_homebrew_autonomy_park" - the gz_<model>_<world>
# target is PX4's own launch mechanism (it's a CMake custom target whose
# COMMAND runs the px4 binary directly), so naming it here would make a
# *build* also spawn Gazebo. Plain "px4_sitl" builds the default `all`
# target, which already includes px4 and px4_gz_plugins (declared ALL) -
# everything scripts/launch_gazebo.sh needs - without launching anything.
export PX4_MAKE_TARGET="px4_sitl"

export PX4_DIR="$PROJECT_ROOT/PX4-Autopilot"
export PX4_ADDITIONS_DIR="$PROJECT_ROOT/px4-additions"
export ROS2_DIR="$PROJECT_ROOT/ros2_ws"

# --- ROS 2 DDS configuration ------------------------------------------------
#
# ~/.bashrc points Fast-DDS at the physical lab network for real-hardware use
# (a static-IP interface whitelist + a remote discovery server) - on a
# machine that isn't on that network, that whitelist filters out every
# interface it actually has, so DDS discovery silently finds nothing:
# `ros2 topic list` shows only /parameter_events and /rosout, and every
# node's service/topic waits hang forever. SITL runs everything on this one
# machine, so force plain localhost DDS instead, scoped to just scripts that
# source this file - the real-hardware config in ~/.bashrc is left untouched
# for when this same shell is later used to fly the real vehicle.
unset FASTRTPS_DEFAULT_PROFILES_FILE
unset ROS_DISCOVERY_SERVER
export ROS_LOCALHOST_ONLY=1

# --- Python virtual environment ---------------------------------------------
#
# PX4's build system needs several Python packages (Tools/setup/requirements.txt)
# on PATH. Debian/Ubuntu's Python 3.11+ marks itself "externally managed"
# (PEP 668) and refuses `pip install` outside a virtualenv regardless of
# --user - and --user is invalid once you *are* inside one (pip errors
# outright). A project-local venv sidesteps both problems and keeps these
# packages out of the user's global site-packages. Created once here, then
# activated on every source of this file so every script gets it for free.
# --system-site-packages so the apt-installed ROS 2 Python packages (rclpy,
# colcon, ...) stay importable inside it too.
VENV_DIR="$PROJECT_ROOT/venv_host"
# Check for the activate script, not just the directory - `python3 -m venv`
# creates the directory before it can fail (e.g. missing ensurepip), which
# would otherwise leave a half-built venv_host/ behind that this check
# would then treat as "already created" on every subsequent run, masking
# the real error behind a confusing "No such file or directory" on the
# `source .../activate` below instead.
if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
    echo "[*] Creating Python virtual environment at $VENV_DIR..." >&2
    if ! python3 -m venv --system-site-packages "$VENV_DIR"; then
        rm -rf "$VENV_DIR"
        echo "Error: failed to create the Python virtual environment at $VENV_DIR." >&2
        echo "  This usually means python3-venv isn't installed:" >&2
        echo "    sudo apt install python3-venv" >&2
        echo "  Then re-run this script." >&2
        exit 1
    fi
fi

# venv's activate script references unset vars (e.g. $PS1) under `set -u`.
set +u
source "$VENV_DIR/bin/activate"
set -u
