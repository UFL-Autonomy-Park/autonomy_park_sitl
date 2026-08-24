#!/usr/bin/env bash
# Kills the standalone Gazebo instance launched by launch_gazebo.sh, and only
# that - not any PX4 instance (see scripts/kill_all_homebrew_instances.sh for
# that) or any other Gazebo session running on the machine.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/process.sh"

kill_pidfile_group /tmp/gz_sim.pid "Gazebo"
exit 0
