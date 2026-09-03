#!/usr/bin/env bash
# Copies the custom Gazebo models, airframe params, and world/textures from
# px4-additions/ into the PX4-Autopilot submodule.
#
# Safe to run from any directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../sitl_env.sh"

require_dir "$PX4_ADDITIONS_DIR"
require_dir "$PX4_DIR" "Error: PX4-Autopilot directory '$PX4_DIR' not found. Run scripts/init.sh first."

echo "Project Root: $PROJECT_ROOT"
echo "Copying additions from $PX4_ADDITIONS_DIR to $PX4_DIR..."

# copy_contents() is defined in sitl_env.sh

# 1. Gazebo simulation models -> PX4-Autopilot/Tools/simulation/gz/models/
copy_contents "$PX4_ADDITIONS_DIR/models" "$PX4_DIR/Tools/simulation/gz/models"

# 2. Airframe parameter files -> PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/
AIRFRAMES_DIR="$PX4_DIR/ROMFS/px4fmu_common/init.d-posix/airframes"

# px4-additions/params/ is the single source of truth for our custom
# airframes. Before re-copying, remove anything a previous sync left
# behind - a file we've since renamed or deleted in px4-additions/, or a
# stray "foo (copy)" from a file manager - otherwise it lingers in the PX4
# tree and PX4's own gz_bridge/CMakeLists.txt globs it into an
# add_custom_target(gz_<suffix>_<world>), which fails the build on a
# duplicate suffix or one containing spaces/parens.
#
# Every *stock* airframe is committed in the pinned PX4 submodule; only our
# additions are untracked, so `git clean` here removes exactly what we
# added and nothing else. CMakeLists.txt is only ever modified by
# register_airframe below, so restoring the committed version drops stale
# registrations without touching anything we care about.
echo "Clearing previously-synced custom airframes and stale registrations..."
git -C "$PX4_DIR" checkout -- "$AIRFRAMES_DIR/CMakeLists.txt"
git -C "$PX4_DIR" clean -f -- "$AIRFRAMES_DIR"

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
