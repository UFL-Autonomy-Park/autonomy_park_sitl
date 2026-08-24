#!/usr/bin/env bash
# Launches a standalone Gazebo instance against the custom world defined in
# px4-additions/ (see library/write_px4_with_px4_additions.sh to sync it
# into PX4-Autopilot first, and library/set_env.sh for the env vars used
# below). Does NOT launch any PX4 instance - run this once, leave it
# running, and use spawn_one_homebrew_instance.sh (repeatedly, if needed) to
# add/reset a vehicle in it. Kept separate because loading the world is slow
# but relaunching PX4 is not, and PX4 (correctly) crashes its own EKF if you
# teleport its rigid body mid-run - resetting the drone's pose means
# restarting PX4 against an already-loaded world, not reloading the world.
#
# Set HEADLESS=1 to skip the GUI client.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/library/set_env.sh"

require_dir "$PX4_DIR/build/px4_sitl_default" "Error: no PX4 SITL build found. Run scripts/build_px4.sh first."

# Adds worlds/models/plugins - including px4-additions/worlds/ once synced in
# - to GZ_SIM_RESOURCE_PATH, and sets PX4_GZ_WORLDS (used below). Generated
# by CMake at build time; it appends to GZ_SIM_RESOURCE_PATH/
# GZ_SIM_SYSTEM_PLUGIN_PATH without checking they're already set, which
# trips `set -u` on a fresh shell.
export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}"
export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"
source "$PX4_DIR/build/px4_sitl_default/rootfs/gz_env.sh"

WORLD_SDF="$PX4_GZ_WORLDS/$PX4_GZ_WORLD.sdf"
[[ -f "$WORLD_SDF" ]] || { echo "Error: world file '$WORLD_SDF' not found." >&2; exit 1; }

echo "[*] Killing any leftover Gazebo processes..."
"$SCRIPT_DIR/library/kill_gazebo.sh"

pidfile="/tmp/gz_sim.pid"
logfile="/tmp/gz_sim.log"
rm -f "$pidfile"

echo "[*] Launching Gazebo (world=$PX4_GZ_WORLD)..."

# setsid puts the server (and the gui client spawned alongside it) in a new
# session/process group, so library/kill_gazebo.sh can kill exactly this
# tree via its PGID - see spawn_one_homebrew_instance.sh's launch_px4() for
# why the pidfile is written from inside the process itself rather than
# trusting `$!`.
setsid bash -c '
    echo $$ > "$1"; shift
    world_sdf="$1"; shift
    gz sim --verbose="${GZ_VERBOSE:-1}" -r -s "$world_sdf" &
    server_pid=$!
    if [[ -z "${HEADLESS:-}" ]]; then
        gz sim -g >/dev/null 2>&1 &
    fi
    wait "$server_pid"
' _ "$pidfile" "$WORLD_SDF" > "$logfile" 2>&1 &
disown

# Wait for the pidfile write, not a fixed sleep - it lands within a syscall
# or two of setsid's fork, so this is normally instant.
for _ in $(seq 1 50); do
    [[ -s "$pidfile" ]] && break
    sleep 0.1
done
echo "PID: $(cat "$pidfile" 2>/dev/null || echo "unknown - check $pidfile")"

# Poll the same "/world/<world>/scene/info" service PX4 itself waits on
# before attaching (see PX4-Autopilot's px4-rc.gzsim) - once it responds,
# the world is fully loaded and spawn_one_homebrew_instance.sh can attach.
echo "[*] Waiting for the world to be ready..."
ATTEMPTS=30
while (( ATTEMPTS > 0 )); do
    if gz service -i --service "/world/$PX4_GZ_WORLD/scene/info" 2>&1 | grep -q "Service providers"; then
        echo "[+] Gazebo world '$PX4_GZ_WORLD' is ready! Ctrl-C to stop."
        break
    fi
    ATTEMPTS=$((ATTEMPTS - 1))
    if (( ATTEMPTS == 0 )); then
        echo "[!] Timeout waiting for the world to be ready. Check $logfile" >&2
        exit 1
    fi
    sleep 1
done

# gz sim runs in its own session (via setsid above), so it's no longer a
# child of this shell - Ctrl-C here won't reach it on its own, and a bare
# `wait` would return immediately instead of blocking on it. Trap the
# interrupt and clean up explicitly instead.
trap '"$SCRIPT_DIR/library/kill_gazebo.sh"; exit 0' INT TERM

while kill -0 "-$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; do
    sleep 1
done
echo "[!] Gazebo exited unexpectedly. Check $logfile" >&2
exit 1
