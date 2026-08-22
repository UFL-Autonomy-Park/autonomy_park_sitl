#!/usr/bin/env bash
# Kills PX4/Gazebo instances launched by this project's scripts, and only
# those instances - not any other Gazebo/PX4 process on the machine.
#
# launch_gazebo.sh launches px4 via `setsid`, which puts px4 (and the gz
# sim server/gui it spawns as direct children) in a new session whose PGID
# equals px4's own PID. That PID is recorded in /tmp/px4_instance_<N>.pid.
# Killing -PGID (the negative form) signals the whole group at once, so
# this reaches px4 and both gz sim processes without matching on process
# names/command lines at all - a previous version here used
# `pkill -f "gz sim|gzserver|..."`, which would also kill any *unrelated*
# Gazebo session someone happens to have running on the same machine.
shopt -s nullglob
for pidfile in /tmp/px4_instance_*.pid; do
    pid="$(cat "$pidfile" 2>/dev/null)"
    rm -f "$pidfile"

    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    kill -0 "-$pid" 2>/dev/null || continue  # group already gone

    kill -TERM "-$pid" 2>/dev/null
    for _ in $(seq 1 20); do
        kill -0 "-$pid" 2>/dev/null || break
        sleep 0.1
    done
    kill -KILL "-$pid" 2>/dev/null || true
done

exit 0
