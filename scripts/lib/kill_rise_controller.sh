#!/usr/bin/env bash
# Kills the aviary_rise_controller experiment launched by
# scripts/launch_rise_controller.sh, and only that - not any other ROS 2
# node running on the machine. Safe to run any time, including when
# nothing is running.
#
# launch_rise_controller.sh launches `ros2 launch` via `setsid`, which puts
# it (and the aviary_rise_node it spawns as a child) in a new session whose
# PGID equals the launch process's own PID. That PID is recorded in
# /tmp/rise_controller.pid. See lib/process.sh for why PGID-based
# killing is used instead of pattern-matching process names/command lines -
# and for why SIGTERM (not SIGKILL) is sent first: `ros2 launch` treats it
# the same as SIGINT and forwards a graceful shutdown to aviary_rise_node,
# which lands the vehicle in its own `finally` block before exiting.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/process.sh"

kill_pidfile_group /tmp/rise_controller.pid "aviary_rise_controller"
exit 0
