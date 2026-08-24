#!/usr/bin/env bash
# Kills every PX4 instance spawned by spawn_one_homebrew_instance.sh, but
# leaves Gazebo - and its vehicle model(s) - alone (see
# scripts/library/kill_gazebo.sh to also stop Gazebo itself).
#
# Run this directly to stop PX4 without restarting Gazebo, or just re-run
# spawn_one_homebrew_instance.sh, which calls this first.
#
# Deliberately does NOT remove the vehicle model from Gazebo. It's tempting
# to think it should (a "reset" sounds like it should clean up after
# itself), but Gazebo Harmonic's rendering engine reliably crashes (Ogre2
# assert, observed repeatedly while developing this script) when a model
# with camera/depth-camera sensors is removed and a same-named one created
# shortly after - so spawn_one_homebrew_instance.sh instead leaves the
# model in place and re-attaches PX4 to it (resetting its pose separately),
# which never touches that crash-prone code path. See spawn_one_homebrew_
# instance.sh for the other half of this.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/library/set_env.sh"

# See scripts/library/kill_gazebo.sh for why PGID-based killing is used
# instead of pattern-matching process names/command lines.
shopt -s nullglob
for pidfile in /tmp/px4_instance_*.pid; do
    instance="$(basename "$pidfile" .pid)"
    instance="${instance#px4_instance_}"

    pid="$(cat "$pidfile" 2>/dev/null)"
    rm -f "$pidfile"

    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    kill -0 "-$pid" 2>/dev/null || continue  # group already gone

    echo "[*] Killing PX4 instance $instance (PID $pid)..."
    kill -TERM "-$pid" 2>/dev/null
    for _ in $(seq 1 50); do
        kill -0 "-$pid" 2>/dev/null || break
        sleep 0.1
    done
    kill -KILL "-$pid" 2>/dev/null || true
done

exit 0
