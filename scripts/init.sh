#!/usr/bin/env bash
# Initializes all git submodules required to build PX4 (including nested
# submodules such as NuttX and Mavlink).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Fetching Git LFS assets (custom meshes/textures)..."
if command -v git-lfs >/dev/null 2>&1; then
    git -C "$PROJECT_ROOT" lfs install --local
    git -C "$PROJECT_ROOT" lfs pull
else
    echo "WARNING: git-lfs is not installed. px4-additions/models/*/meshes/*.STL" >&2
    echo "  and worlds/materials/textures/* will remain empty LFS pointer files," >&2
    echo "  and Gazebo will fail to load the custom model's meshes." >&2
    echo "  Install git-lfs, then re-run this script." >&2
fi

echo "==> Initializing and updating top-level submodules..."
git -C "$PROJECT_ROOT" submodule update --init --recursive

echo "==> Verifying PX4-Autopilot checkout..."
PX4_DIR="$PROJECT_ROOT/PX4-Autopilot"

# Ensure nested submodules within PX4 (NuttX, Mavlink, etc.) are populated
git -C "$PX4_DIR" submodule update --init --recursive

echo "==> PX4-Autopilot is ready at $(git -C "$PX4_DIR" describe --tags HEAD 2>/dev/null || git -C "$PX4_DIR" rev-parse --short HEAD)"
