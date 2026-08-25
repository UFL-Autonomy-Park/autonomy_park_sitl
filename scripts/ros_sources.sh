#!/usr/bin/env bash
# Convenience for ad hoc `ros2` CLI use against the running SITL (topic
# list/echo, node info, etc.): sources both sitl_env.sh (the DDS/domain
# config every launched node uses - see README Troubleshooting for why
# this specifically, not just any shell, matters for `ros2 topic echo` to
# work) and ros2_ws/install/setup.bash (so `ros2` can see this workspace's
# packages: aero_common, apark_rise_controller, px4_msgs), in one step
# instead of two commands to remember.
#
# Must be *sourced*, not executed: `source scripts/ros_sources.sh`.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: ros_sources.sh must be sourced, not executed." >&2
    echo "  Run: source ${BASH_SOURCE[0]}" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/sitl_env.sh"

# colcon's generated setup.bash reads $COLCON_TRACE (and friends, via
# nested local_setup.bash files) without a default, which trips `set -u`.
# Restore whatever nounset state the caller actually had, rather than
# forcing it back on - this file is meant to be *sourced* into an
# interactive shell, and unconditionally leaving `set -u` on afterward
# broke bash's own tab-completion machinery in exactly that scenario
# ("COMPREPLY: unbound variable"), since bash-completion's internals
# aren't nounset-safe.
case $- in
    *u*) _ros_sources_had_nounset=1 ;;
    *)   _ros_sources_had_nounset=0 ;;
esac
set +u
source "$ROS2_DIR/install/setup.bash"
(( _ros_sources_had_nounset )) && set -u
unset _ros_sources_had_nounset
