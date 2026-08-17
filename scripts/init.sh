#!/usr/bin/env bash
set -e # Exit immediately if a command exits with a non-zero status

echo "==> Initializing and updating top-level submodules..."
git submodule update --init --recursive

echo "==> Verifying PX4-Autopilot checkout..."
cd PX4-Autopilot

# Ensure nested submodules within PX4 (NuttX, Mavlink, etc.) are populated
git submodule update --init --recursive

echo "==> PX4-Autopilot is ready at $(git describe --tags HEAD 2>/dev/null || git rev-parse --short HEAD)"
