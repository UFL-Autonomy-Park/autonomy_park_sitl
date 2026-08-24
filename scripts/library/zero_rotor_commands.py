#!/usr/bin/env python3
"""Zero a homebrew model's commanded rotor velocities over gz-transport.

Used by reset_model() in homebrew_instance.sh. `gz topic -p ...` (a
separate one-shot CLI process) has no way to know when ITS OWN discovery of
a topic's existing subscribers has actually completed, so it either has to
guess a fixed --duration and hope that's long enough, or risk dropping the
message on a subscriber it hasn't found yet - both observed in practice
(the duration guess needed bumping from 1s to 2s, and even then wasn't
verified reliable across many runs). This instead polls the SAME
long-lived node's own view of the topic's subscriber count until it
stabilizes (or a timeout elapses, as a fallback for when nothing is
listening at all - e.g. Gazebo not running) before publishing, so the wait
is tied to an observed condition instead of a guessed duration.
"""
import sys
import time

import gz.transport13 as transport
from gz.msgs10.actuators_pb2 import Actuators

NUM_ROTORS = 4
SETTLE_CHECKS = 3     # consecutive identical, non-zero subscriber counts
POLL_INTERVAL = 0.05  # seconds between checks
TIMEOUT = 5.0         # seconds - fallback only, e.g. nothing listening at all


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: zero_rotor_commands.py <topic>", file=sys.stderr)
        return 1
    topic = sys.argv[1]

    node = transport.Node()
    pub = node.advertise(topic, Actuators)
    if not pub.valid():
        print(f"error: could not advertise {topic}", file=sys.stderr)
        return 1

    deadline = time.monotonic() + TIMEOUT
    last_count = -1
    stable = 0
    while time.monotonic() < deadline:
        _publishers, subscribers = node.topic_info(topic)
        count = len(subscribers)
        if count > 0 and count == last_count:
            stable += 1
            if stable >= SETTLE_CHECKS:
                break
        else:
            stable = 0
        last_count = count
        time.sleep(POLL_INTERVAL)

    msg = Actuators()
    msg.velocity.extend([0.0] * NUM_ROTORS)
    pub.publish(msg)
    # Brief moment for the publish to actually flush over the wire before
    # this process (and its advertisement) exits.
    time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
