#!/usr/bin/env bash
# Launches a PX4 SITL instance against the custom Gazebo world/model defined
# in px4-additions/ (see write_px4_with_px4_additions.sh to sync them into
# PX4-Autopilot first, and scripts/set_env.sh for the env vars used below).
#
# To reset the EKF origin manually after launch:
#   $PX4_DIR/build/px4_sitl_default/bin/px4-commander set_ekf_origin <lat> <lon> <alt>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"

require_dir "$PX4_DIR/build/px4_sitl_default" "Error: no PX4 SITL build found. Run scripts/rebuild_px4.sh first."

echo "[*] Killing any leftover Gazebo/PX4 processes..."
"$SCRIPT_DIR/kill_gz.sh"

READY_STRING="Ready for takeoff!"

launch_px4() {
    local instance=$1
    local autostart=$2
    local model=$3
    local pose=${4:-}
    local logfile="/tmp/px4_instance_${instance}.log"

    echo "[*] Launching PX4 instance $instance (model=$model, autostart=$autostart)..."

    # -d disables px4's interactive "pxh>" shell. Without it, px4's getchar()
    # read loop never blocks once stdin isn't a real controlling terminal (as
    # here, backgrounded from a script) - it spins re-printing the prompt as
    # fast as the CPU allows, pegging a core and growing $logfile without
    # bound instead of settling down after startup.

    PX4_HOME_LAT="$PX4_HOME_LAT" \
    PX4_HOME_LON="$PX4_HOME_LON" \
    PX4_HOME_ALT="$PX4_HOME_ALT" \
    PX4_GZ_WORLD="$PX4_GZ_WORLD" \
    PX4_SYS_AUTOSTART="$autostart" \
    PX4_SIM_MODEL="$model" \
    PX4_GZ_MODEL_POSE="$pose" \
    "$PX4_DIR/build/px4_sitl_default/bin/px4" -i "$instance" -d < /dev/null > "$logfile" 2>&1 &

    echo "PID: $!"
}

wait_for_ready() {
    local instance=$1
    local logfile="/tmp/px4_instance_${instance}.log"
    local timeout=30  # seconds
    local elapsed=0

    echo "[*] Waiting for instance $instance to be ready..."

    while (( elapsed < timeout )); do
        if grep -q "$READY_STRING" "$logfile" 2>/dev/null; then
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

cd "$PX4_DIR"

launch_px4 0 "$PX4_SYS_AUTOSTART" "$PX4_SIM_MODEL" "0,20"
wait_for_ready 0

echo "[+] Gazebo simulation is ready!"
wait # Keep script alive so Ctrl-C reaches the backgrounded px4 process
