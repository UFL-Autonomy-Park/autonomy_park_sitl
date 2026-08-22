#!/usr/bin/env bash
# Kills the ROS 2 autonomy stack (MAVROS, px4_telemetry, px4_teleop,
# px4_safety_lib, autonomy_park_viz) launched by this project's scripts, and
# only those - not any other ROS 2 nodes running on the machine.
#
# launch_ros2_autonomy_stack.sh launches `ros2 launch` via `setsid`, which
# puts it (and every node it spawns as a child) in a new session whose PGID
# equals the launch process's own PID. That PID is recorded in
# /tmp/ros2_autonomy_stack.pid. Killing -PGID (the negative form) signals the
# whole group at once, so this reaches every node `ros2 launch` started
# without matching on process names/command lines at all - if `ros2 launch`
# ever dies without cleanly reaping its children (e.g. the underlying PX4
# instance disappearing out from under it), untracked orphaned nodes are
# exactly what pattern-matching by name would (unreliably) try to catch, and
# what PGID-based tracking avoids needing to.
pidfile="/tmp/ros2_autonomy_stack.pid"

pid="$(cat "$pidfile" 2>/dev/null)"
rm -f "$pidfile"

[[ "$pid" =~ ^[0-9]+$ ]] || exit 0
kill -0 "-$pid" 2>/dev/null || exit 0  # group already gone

kill -TERM "-$pid" 2>/dev/null
for _ in $(seq 1 50); do
    kill -0 "-$pid" 2>/dev/null || break
    sleep 0.1
done
kill -KILL "-$pid" 2>/dev/null || true

exit 0
