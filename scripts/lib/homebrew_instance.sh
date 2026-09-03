#!/usr/bin/env bash
# Shared functions for managing a single "homebrew" PX4/Gazebo vehicle
# instance - used by both launch_one_homebrew.sh and
# lib/kill_all_px4_instances.sh, which is the only reason this lives apart
# from either of them. Relies on PX4_* env vars set by sitl_env.sh, so
# source that first: `source scripts/sitl_env.sh` then
# `source scripts/lib/homebrew_instance.sh`. Not meant to be run directly.

# Resolved from this file's own location (not the caller's SCRIPT_DIR, which
# may point elsewhere) so zero_rotor_commands.py is found regardless of who
# sources this.
_HOMEBREW_INSTANCE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# model_instance_name INSTANCE - the Gazebo model name PX4 uses for a given
# instance number, e.g. "homebrew_0". Matches PX4-Autopilot's own ROMFS/
# px4fmu_common/init.d-posix/px4-rc.gzsim: MODEL_NAME="${PX4_SIM_MODEL#*gz_}",
# instance name "${MODEL_NAME}_<N>".
model_instance_name() {
    local instance="$1"
    echo "${PX4_SIM_MODEL#*gz_}_${instance}"
}

# model_exists INSTANCE - true if that instance's vehicle model is already
# present in the running Gazebo world.
model_exists() {
    local instance="$1"
    local model_instance
    model_instance="$(model_instance_name "$instance")"
    gz service -l 2>/dev/null | grep -q "^/world/$PX4_GZ_WORLD/model/$model_instance/"
}

# instances_with_models - prints the instance number of every vehicle model
# (for the current $PX4_SIM_MODEL) currently present in the running Gazebo
# world, one per line. Empty if Gazebo is down or no such model exists.
instances_with_models() {
    local prefix="${PX4_SIM_MODEL#*gz_}_"
    gz service -l 2>/dev/null \
        | sed -n "s#^/world/$PX4_GZ_WORLD/model/${prefix}\([0-9]\{1,\}\)/.*#\1#p" \
        | sort -u
}

# reset_model INSTANCE - resets that instance's vehicle model to a clean
# resting pose ($PX4_GZ_MODEL_POSE, identity orientation) with zero rotor
# velocity. Safe to call any time, including when Gazebo isn't running or
# the model doesn't exist yet (nothing to reset then).
#
# TODO(multi-agent): every instance is reset to the same $PX4_GZ_MODEL_POSE
# - correct today since only instance 0 ever exists, but wrong once
# multiple agents with distinct spawn points exist. At that point this
# needs a per-instance pose (e.g. a PX4_GZ_MODEL_POSE_<N> env var, or a
# small array/lookup keyed by instance number) instead of one shared value.
reset_model() {
    local instance=$1
    local model_instance
    model_instance="$(model_instance_name "$instance")"

    # Without an active PX4 instance, the MulticopterMotorModel plugin
    # driving each rotor has no failsafe: it holds the last velocity it was
    # ever commanded (whatever thrust/torque PX4 last sent) forever, rather
    # than decaying to zero once PX4 stops publishing - so killing PX4
    # alone leaves the vehicle under real, ongoing thrust with nothing
    # controlling it (an actual uncontrolled crash, same as a real quad
    # that lost its flight controller mid-flight). This is exactly what
    # exposed the problem: resetting position/orientation below did not
    # stick on its own - the model kept tumbling/drifting again within a
    # couple of seconds even after being reset, because that stale thrust
    # was still being applied the whole time. Zeroing every rotor's
    # commanded velocity removes that runaway force; only once that's done
    # does the pose reset actually hold, verified by watching the pose for
    # several seconds after both steps with no further drift.
    # zero_rotor_commands.py waits for gz-transport's own subscriber
    # discovery to actually settle before publishing, rather than guessing
    # a fixed `gz topic -p ... --duration` - a duration guess was tried
    # first (1s, then 2s) and neither was verified reliable across many
    # runs; this ties the wait to an observed condition instead. See that
    # script for the full story.
    python3 "$_HOMEBREW_INSTANCE_LIB_DIR/zero_rotor_commands.py" \
        "/${model_instance}/command/motor_speed" || true

    local pos_x pos_y pos_z
    pos_x=$(echo "$PX4_GZ_MODEL_POSE" | awk -F',' '{print $1}')
    pos_y=$(echo "$PX4_GZ_MODEL_POSE" | awk -F',' '{print $2}')
    pos_z=$(echo "$PX4_GZ_MODEL_POSE" | awk -F',' '{print $3}')

    gz service -s "/world/$PX4_GZ_WORLD/set_pose" --reqtype gz.msgs.Pose \
        --reptype gz.msgs.Boolean --timeout 5000 \
        --req "name: \"$model_instance\", position: {x: ${pos_x:-0}, y: ${pos_y:-0}, z: ${pos_z:-0}}, orientation: {x: 0, y: 0, z: 0, w: 1}" \
        >/dev/null 2>&1 || true
}

# wait_for_ready INSTANCE - blocks (up to 30s) until that instance's PX4
# log shows "Ready for takeoff!".
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

# launch_px4 INSTANCE - launches a PX4 instance against the already-running
# Gazebo world ($PX4_GZ_WORLD). If that instance's model already exists
# (left behind by a previous run, and already reset by
# kill_all_px4_instances.sh), attaches to it (PX4_GZ_MODEL_NAME);
# otherwise spawns it for the first time (PX4's normal create path).
launch_px4() {
    local instance=$1
    local logfile="/tmp/px4_instance_${instance}.log"
    local pidfile="/tmp/px4_instance_${instance}.pid"
    local extra_env=()

    if model_exists "$instance"; then
        echo "[*] Model '$(model_instance_name "$instance")' already exists - re-attaching..."
        extra_env=(PX4_GZ_MODEL_NAME="$(model_instance_name "$instance")")
    else
        echo "[*] No existing model - spawning '$(model_instance_name "$instance")' for the first time..."
    fi

    echo "[*] Launching PX4 instance $instance (model=$PX4_SIM_MODEL, autostart=$PX4_SYS_AUTOSTART)..."

    # -d disables px4's interactive "pxh>" shell. Without it, px4's getchar()
    # read loop never blocks once stdin isn't a real controlling terminal (as
    # here, backgrounded from a script) - it spins re-printing the prompt as
    # fast as the CPU allows, pegging a core and growing $logfile without
    # bound instead of settling down after startup.

    # setsid puts px4 in a new session/process group, so
    # kill_pidfile_group (see lib/process.sh) can kill exactly this
    # process via its PGID instead of pattern-matching process names
    # system-wide - it will NOT include Gazebo, since spawn_one_homebrew_
    # instance.sh refuses to run unless Gazebo is already up on its own.
    # `$!` after `setsid cmd &` is unreliable - setsid forks internally and
    # $! can end up pointing at an already-exited intermediate - so the
    # pidfile is written from inside the process that actually execs into
    # px4, guaranteeing it's correct.
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
