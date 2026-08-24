#!/usr/bin/env bash
# Spawns a single PX4 instance (instance 0) against an already-running
# Gazebo world (see scripts/launch_gazebo.sh), attaching to it rather than
# launching a new one. Re-run this any time you want to reset the vehicle's
# pose - it kills any previous instance first (see
# kill_all_homebrew_instances.sh), resets the model's pose, and attaches a
# fresh PX4 to it. Teleporting a running PX4's rigid body crashes its EKF (a
# PX4 limitation, not fixable from here), so a full PX4 restart is the only
# way to reset pose - this script makes that restart cheap by never
# touching the (slow-to-load) Gazebo world itself.
#
# On the very first run against a given Gazebo instance, no model exists
# yet, so this spawns one (PX4's normal path). On every run after that, the
# model from the previous run is still sitting in Gazebo - deliberately not
# removed, see kill_all_homebrew_instances.sh for why - so this instead
# resets its pose via Gazebo's `set_pose` service and attaches PX4 to the
# existing model (`PX4_GZ_MODEL_NAME`) rather than spawning a new one.
#
# To reset the EKF origin manually after launch:
#   $PX4_DIR/build/px4_sitl_default/bin/px4-commander set_ekf_origin <lat> <lon> <alt>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/library/set_env.sh"

require_dir "$PX4_DIR/build/px4_sitl_default" "Error: no PX4 SITL build found. Run scripts/build_px4.sh first."

# Must NOT let PX4 discover no world is running and launch its own - if it
# did, Gazebo would end up as a child of *this* instance's process group,
# and killing this instance (e.g. to reset pose) would take Gazebo down
# with it, defeating the entire point of splitting these scripts apart.
if ! gz service -i --service "/world/$PX4_GZ_WORLD/scene/info" 2>&1 | grep -q "Service providers"; then
    echo "Error: Gazebo isn't running (world '$PX4_GZ_WORLD' not found)." >&2
    echo "  Run scripts/launch_gazebo.sh first, then re-run this script." >&2
    exit 1
fi

# Matches PX4-Autopilot's own ROMFS/px4fmu_common/init.d-posix/px4-rc.gzsim:
# MODEL_NAME="${PX4_SIM_MODEL#*gz_}", instance name "${MODEL_NAME}_<N>".
MODEL_NAME="${PX4_SIM_MODEL#*gz_}"
MODEL_INSTANCE="${MODEL_NAME}_0"

echo "[*] Killing any previous PX4 instance..."
"$SCRIPT_DIR/kill_all_homebrew_instances.sh"

model_exists() {
    gz service -l 2>/dev/null | grep -q "^/world/$PX4_GZ_WORLD/model/$MODEL_INSTANCE/"
}

launch_px4() {
    local instance=$1
    local logfile="/tmp/px4_instance_${instance}.log"
    local pidfile="/tmp/px4_instance_${instance}.pid"
    local extra_env=()

    if model_exists; then
        # Same x/y/z px4-rc.gzsim's own spawn parses out of
        # PX4_GZ_MODEL_POSE - orientation is reset to identity too, matching
        # what a fresh spawn would get (px4-rc.gzsim's create request never
        # sets orientation either).
        local pos_x pos_y pos_z
        pos_x=$(echo "$PX4_GZ_MODEL_POSE" | awk -F',' '{print $1}')
        pos_y=$(echo "$PX4_GZ_MODEL_POSE" | awk -F',' '{print $2}')
        pos_z=$(echo "$PX4_GZ_MODEL_POSE" | awk -F',' '{print $3}')

        echo "[*] Model '$MODEL_INSTANCE' already exists - resetting its pose and re-attaching..."
        gz service -s "/world/$PX4_GZ_WORLD/set_pose" --reqtype gz.msgs.Pose \
            --reptype gz.msgs.Boolean --timeout 5000 \
            --req "name: \"$MODEL_INSTANCE\", position: {x: ${pos_x:-0}, y: ${pos_y:-0}, z: ${pos_z:-0}}, orientation: {x: 0, y: 0, z: 0, w: 1}" \
            >/dev/null

        extra_env=(PX4_GZ_MODEL_NAME="$MODEL_INSTANCE")
    else
        echo "[*] No existing model - spawning '$MODEL_INSTANCE' for the first time..."
    fi

    echo "[*] Launching PX4 instance $instance (model=$PX4_SIM_MODEL, autostart=$PX4_SYS_AUTOSTART)..."

    # -d disables px4's interactive "pxh>" shell. Without it, px4's getchar()
    # read loop never blocks once stdin isn't a real controlling terminal (as
    # here, backgrounded from a script) - it spins re-printing the prompt as
    # fast as the CPU allows, pegging a core and growing $logfile without
    # bound instead of settling down after startup.

    # setsid puts px4 in a new session/process group, so
    # kill_all_homebrew_instances.sh can kill exactly this process via its
    # PGID instead of pattern-matching process names system-wide - it will
    # NOT include Gazebo (see the scene/info check above). `$!` after
    # `setsid cmd &` is unreliable - setsid forks internally and $! can end
    # up pointing at an already-exited intermediate - so the pidfile is
    # written from inside the process that actually execs into px4,
    # guaranteeing it's correct.
    rm -f "$pidfile"
    setsid bash -c 'echo $$ > "$1"; shift; exec "$@"' _ "$pidfile" \
        env PX4_HOME_LAT="$PX4_HOME_LAT" \
            PX4_HOME_LON="$PX4_HOME_LON" \
            PX4_HOME_ALT="$PX4_HOME_ALT" \
            PX4_GZ_WORLD="$PX4_GZ_WORLD" \
            PX4_SYS_AUTOSTART="$PX4_SYS_AUTOSTART" \
            PX4_SIM_MODEL="$PX4_SIM_MODEL" \
            PX4_GZ_MODEL_POSE="$PX4_GZ_MODEL_POSE" \
            "${extra_env[@]}" \
            "$PX4_DIR/build/px4_sitl_default/bin/px4" -i "$instance" -d \
        < /dev/null > "$logfile" 2>&1 &
    disown

    # Wait for the pidfile write, not a fixed sleep - it lands within a
    # syscall or two of setsid's fork, so this is normally instant.
    for _ in $(seq 1 50); do
        [[ -s "$pidfile" ]] && break
        sleep 0.1
    done

    echo "PID: $(cat "$pidfile" 2>/dev/null || echo "unknown - check $pidfile")"
}

wait_for_ready() {
    local instance=$1
    local logfile="/tmp/px4_instance_${instance}.log"
    local timeout=30  # seconds
    local elapsed=0

    echo "[*] Waiting for instance $instance to be ready..."

    while (( elapsed < timeout )); do
        if grep -q "Ready for takeoff!" "$logfile" 2>/dev/null; then
            echo "[+] Instance $instance is ready!"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    echo "[!] Timeout waiting for instance $instance. Check $logfile" >&2
    return 1
}

# --- Launch sequence ---

# Matches PX4's own gz_<model>_<world> make target's WORKING_DIRECTORY, so
# dataman/logs/etc. land in the same place a `make` launch would put them.
cd "$PX4_DIR/build/px4_sitl_default/rootfs"

launch_px4 0
wait_for_ready 0

echo "[+] PX4 instance 0 is ready! Ctrl-C to stop (Gazebo keeps running)."

# px4 runs in its own session (via setsid in launch_px4), so it's no longer
# a child of this shell - Ctrl-C here won't reach it on its own, and a bare
# `wait` would return immediately instead of blocking on it. Trap the
# interrupt and clean up explicitly instead.
trap '"$SCRIPT_DIR/kill_all_homebrew_instances.sh"; exit 0' INT TERM

while kill -0 "-$(cat /tmp/px4_instance_0.pid 2>/dev/null)" 2>/dev/null; do
    sleep 1
done
echo "[!] PX4 instance 0 exited unexpectedly. Check /tmp/px4_instance_0.log" >&2
exit 1
