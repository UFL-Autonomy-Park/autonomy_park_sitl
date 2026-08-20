#!/usr/bin/env bash
# Copies the custom Gazebo models, airframe params, and world/textures from
# px4-additions/ into the PX4-Autopilot submodule.
#
# Safe to run from any directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"

require_dir "$PX4_ADDITIONS_DIR"
require_dir "$PX4_DIR" "Error: PX4-Autopilot directory '$PX4_DIR' not found. Run scripts/init.sh first."

echo "Project Root: $PROJECT_ROOT"
echo "Copying additions from $PX4_ADDITIONS_DIR to $PX4_DIR..."

# copy_contents() is defined in set_env.sh

# 1. Gazebo simulation models -> PX4-Autopilot/Tools/simulation/gz/models/
copy_contents "$PX4_ADDITIONS_DIR/models" "$PX4_DIR/Tools/simulation/gz/models"

# 2. Airframe parameter files -> PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/
AIRFRAMES_DIR="$PX4_DIR/ROMFS/px4fmu_common/init.d-posix/airframes"
copy_contents "$PX4_ADDITIONS_DIR/params" "$AIRFRAMES_DIR"

# PX4 does NOT glob this directory for its build: airframes/CMakeLists.txt
# lists every staged file explicitly via px4_add_romfs_files(...). A file
# that merely exists in the directory but isn't in that list is silently
# skipped when the ROMFS is packed into the build rootfs - no cmake
# reconfigure or clean rebuild will pick it up. Register any new custom
# airframe files here so `make px4_sitl gz_<model>` can find them.
register_airframe() {
    local airframe="$1"
    local cmake_file="$AIRFRAMES_DIR/CMakeLists.txt"

    if grep -qE "^[[:space:]]*${airframe}[[:space:]]*\$" "$cmake_file"; then
        return
    fi

    echo "Registering '$airframe' in $cmake_file (px4_add_romfs_files)"
    # Insert as a new entry right before the closing ')' of
    # px4_add_romfs_files(...), which is the file's last line.
    sed -i "\$i\\	${airframe}" "$cmake_file"
}

for airframe_path in "$PX4_ADDITIONS_DIR/params/"*; do
    register_airframe "$(basename "$airframe_path")"
done

# 3. Gazebo simulation worlds & textures -> PX4-Autopilot/Tools/simulation/gz/worlds/
copy_contents "$PX4_ADDITIONS_DIR/worlds" "$PX4_DIR/Tools/simulation/gz/worlds"

echo "Successfully synchronized custom assets into PX4-Autopilot."

if [[ -d "$PX4_DIR/build" ]]; then
    echo
    echo "NOTE: an existing build/ dir was found. PX4's CMake globs the"
    echo "worlds directory and the gz_bridge build-target list at configure"
    echo "time, so a new world, or a newly-registered airframe, won't take"
    echo "effect until you reconfigure: rm -rf '$PX4_DIR/build/px4_sitl_default'"
    echo "and rebuild, or re-run 'cmake' in that build directory."
fi
