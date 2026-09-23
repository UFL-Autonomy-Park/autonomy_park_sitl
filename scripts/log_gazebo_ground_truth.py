#!/usr/bin/env python3
"""Logs a Gazebo model's TRUE world pose straight to CSV, as an independent
sanity check against autonomy_park/pose (and therefore apark_rise_node's
logged x_m/y_m).

Subscribes to /world/<world>/dynamic_pose/info via gz-transport directly --
this is the exact feed Gazebo's own GUI renders from (see
SceneBroadcaster.cc), so "what you see in the Gazebo viewport" and what this
script logs are, by construction, the same data. It never touches
MAVROS/GPS/PX4/origin_r at all, so a mismatch against the flight CSV's
x_m/y_m narrows the bug to somewhere in that pipeline (NavSat -> PX4 EKF ->
MAVROS -> px4_telemetry's UTM+origin_r math -> autonomy_park/pose) rather
than the plotting code or the controller.

Position is in Gazebo's raw world (SDF) frame -- since this project's world
was built so that frame's X/Y axes already align with the apark frame (see
the heading_deg investigation), it should match autonomy_park/pose's x_m/y_m
directly, with no rotation needed, if everything upstream is correct.

Usage:
    venv_host/bin/python3 scripts/log_gazebo_ground_truth.py [--model homebrew_0] [--world autonomy_park] [--out PATH]
    Run this *during* a flight (alongside apark_rise_node/debugging_node),
    Ctrl-C when the flight ends to write the CSV.

To find the right --model name for a different vehicle/world, run:
    gz topic -e -t /world/<world>/dynamic_pose/info -n 1
and look for the top-level pose entry (not base_link/rotor_*/sensor links).
"""
import argparse
import csv
import os
import sys
import time

import gz.msgs10.pose_v_pb2 as pose_v_pb2
import gz.transport13 as transport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', default='homebrew_0',
                         help="Model name to filter on (default: homebrew_0).")
    parser.add_argument('--world', default='autonomy_park')
    parser.add_argument('--out', default=None,
                         help="Output CSV path (default: simulation_data/gazebo_ground_truth/run_N.csv)")
    args = parser.parse_args()

    topic = f"/world/{args.world}/dynamic_pose/info"
    rows: list[tuple[float, float, float, float]] = []

    def callback(msg: pose_v_pb2.Pose_V) -> None:
        for pose in msg.pose:
            if pose.name == args.model:
                t = msg.header.stamp.sec + msg.header.stamp.nsec / 1e9
                rows.append((t, pose.position.x, pose.position.y, pose.position.z))
                break

    node = transport.Node()
    if not node.subscribe(pose_v_pb2.Pose_V, topic, callback):
        print(f"[!] Failed to subscribe to {topic}", file=sys.stderr)
        sys.exit(1)
    print(f"[*] Subscribed to {topic}, filtering model='{args.model}'. Ctrl-C to stop and save.")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()

    if not rows:
        print(f"[!] No messages received for model='{args.model}' on {topic}. "
              "Is Gazebo running, and is --model correct? See this script's "
              "docstring for how to check.", file=sys.stderr)
        sys.exit(1)

    out_path = args.out
    if out_path is None:
        base_dir = "simulation_data/gazebo_ground_truth"
        os.makedirs(base_dir, exist_ok=True)
        existing = [f for f in os.listdir(base_dir) if f.startswith('run_') and f.endswith('.csv')]
        nums = []
        for f in existing:
            try:
                nums.append(int(f.replace('run_', '').replace('.csv', '')))
            except ValueError:
                pass
        out_path = os.path.join(base_dir, f"run_{(max(nums) + 1) if nums else 1}.csv")
    else:
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

    t0 = rows[0][0]
    with open(out_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Time_s", "x_m", "y_m", "z_m"])
        for t, x, y, z in rows:
            writer.writerow([t - t0, x, y, z])

    print(f"[+] Saved {len(rows)} ground-truth poses to {out_path}")


if __name__ == '__main__':
    main()
