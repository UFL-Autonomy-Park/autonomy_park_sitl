#!/usr/bin/env bash
# Kills the standalone Gazebo instance launched by launch_gazebo.sh, and only
# that - not any PX4 instance (see scripts/kill_all_homebrew_instances.sh for
# that) or any other Gazebo session running on the machine.
#
# launch_gazebo.sh launches `gz sim` (server + gui) via `setsid`, which puts
# both in a new session whose PGID equals the server's own PID. That PID is
# recorded in /tmp/gz_sim.pid. Killing -PGID (the negative form) signals the
# whole group at once - see kill_all_homebrew_instances.sh for why this is
# preferred over pattern-matching process names/command lines.
pidfile="/tmp/gz_sim.pid"

pid="$(cat "$pidfile" 2>/dev/null)"
rm -f "$pidfile"

[[ "$pid" =~ ^[0-9]+$ ]] || exit 0
kill -0 "-$pid" 2>/dev/null || exit 0  # group already gone

kill -TERM "-$pid" 2>/dev/null
for _ in $(seq 1 20); do
    kill -0 "-$pid" 2>/dev/null || break
    sleep 0.1
done
kill -KILL "-$pid" 2>/dev/null || true

exit 0
