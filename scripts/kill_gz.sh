#!/usr/bin/env bash
# Kills any running Gazebo and PX4 SITL processes.
#
# pkill -f matches against full command lines, so a loose pattern like
# "gz|gazebo|px4" self-matches: it appears literally in pkill's own argv,
# and "gz" also appears in this script's own filename (kill_gz.sh) when
# invoked as `bash scripts/kill_gz.sh` - both would cause pkill to kill
# its own caller before it finishes. Matching actual binary/process names
# instead of loose substrings avoids both.
#
# pkill exits 1 when nothing matches, which would trip `set -e` in a
# caller; always exit 0 - "nothing to kill" is success, not failure.
pkill -9 -f "gz sim|gzserver|gzclient|px4-gz-bridge|bin/px4" || true
