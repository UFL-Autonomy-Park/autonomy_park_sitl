#!/usr/bin/env python3
"""Overlay a flight's logged position (from apark_rise_node's/debugging_node's
CSV) against Gazebo's ground-truth model pose (from
scripts/log_gazebo_ground_truth.py) on the same top-down axes.

A frame-agnostic sanity check: the ground-truth trace never touches MAVROS/
GPS/origin_r, so if it and the logged trace disagree, the bug is somewhere
in that pipeline (NavSat -> PX4 EKF -> MAVROS -> px4_telemetry's UTM+origin_r
math -> autonomy_park/pose), not in the plotting code or the controller.

Usage:
    venv_host/bin/python3 scripts/compare_ground_truth.py \\
        --flight simulation_data/baseline/figure_eight/run_3.csv \\
        --ground-truth simulation_data/gazebo_ground_truth/run_2.csv \\
        [--out ground_truth_comparison.svg]

The two runs don't need matching timestamps -- this overlays shape/position
only (x/y range and path shape), not a time-synced animation, which is
sufficient to spot a frame/rotation/offset bug.
"""
import argparse
import os
import sys

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plot_csv_results import _apply_topdown_convention  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--flight', required=True, help="apark_rise_node/debugging_node run_N.csv")
    parser.add_argument('--ground-truth', required=True, help="log_gazebo_ground_truth.py run_N.csv")
    parser.add_argument('--out', default='ground_truth_comparison.svg')
    args = parser.parse_args()

    flight = pd.read_csv(args.flight)
    gt = pd.read_csv(args.ground_truth)

    fig, ax = plt.subplots(figsize=(9, 9))
    if 'xd_m' in flight.columns:
        ax.plot(flight['yd_m'], flight['xd_m'], 'k--', alpha=0.5, linewidth=1.5, label='Desired')
    ax.plot(flight['y_m'], flight['x_m'], 'b-', linewidth=2, label='Logged (autonomy_park/pose)')
    ax.plot(gt['y_m'], gt['x_m'], 'r:', linewidth=2.5, label='Gazebo ground truth (dynamic_pose/info)')
    ax.scatter([flight['y_m'].iloc[0]], [flight['x_m'].iloc[0]], color='blue', marker='o', s=60, zorder=5)
    ax.scatter([gt['y_m'].iloc[0]], [gt['x_m'].iloc[0]], color='red', marker='o', s=60, zorder=5)
    ax.set_title("Logged position vs. Gazebo ground truth")
    ax.grid(True)
    ax.axis('equal')
    _apply_topdown_convention(ax)
    ax.legend()
    plt.savefig(args.out)
    print(f"[+] Saved comparison to {args.out}")


if __name__ == '__main__':
    main()
