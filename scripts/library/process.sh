#!/usr/bin/env bash
# Generic process-group helper shared by every kill_*.sh script. Deliberately
# standalone (does NOT source set_env.sh) so scripts that want to stay
# dependency-free - safe to run even mid-setup, without paying for
# set_env.sh's venv creation/activation - can just source this one function
# instead. Source directly: `source scripts/library/process.sh`.

# kill_pidfile_group PIDFILE [LABEL] - sends SIGTERM (escalating to SIGKILL
# after ~5s) to the process GROUP led by the PID recorded in PIDFILE, then
# removes PIDFILE. Every launch_*.sh script in this project starts its
# background process via `setsid`, putting it in a new session/process
# group whose PGID equals its own PID - killing -PGID (the negative form)
# reaches that whole tree (the process plus every child it spawns) in one
# shot, without pattern-matching process names/command lines system-wide,
# which would also catch any unrelated process a user happens to have
# running. Safe to call when PIDFILE is missing, or the process is already
# gone - every caller relies on this for idempotency.
kill_pidfile_group() {
    local pidfile="$1"
    local label="${2:-process}"

    local pid
    pid="$(cat "$pidfile" 2>/dev/null)"
    rm -f "$pidfile"

    [[ "$pid" =~ ^[0-9]+$ ]] || return 0
    kill -0 "-$pid" 2>/dev/null || return 0  # group already gone

    echo "[*] Killing $label (PID $pid)..."
    kill -TERM "-$pid" 2>/dev/null
    for _ in $(seq 1 50); do
        kill -0 "-$pid" 2>/dev/null || break
        sleep 0.1
    done
    kill -KILL "-$pid" 2>/dev/null || true
}
