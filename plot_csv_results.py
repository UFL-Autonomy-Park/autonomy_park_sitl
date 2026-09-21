"""Post-flight CSV analysis: static summary/trajectory plots and a real-time
synced MP4 animation. Ported from Unity SITL's src/plotting.py (shared there by
src/run_sim.py's save_data path and scripts/plot_csv_results.py's standalone CLI)
to read aviary_rise_node.write_csv's column names instead -- see
column_mapping in run_post_flight_analysis. In this repo the standalone CLI
counterpart is plot_csv_results.py at the repo root, not under scripts/.

Note: aviary_rise_node.write_csv names its NN feedforward columns "Phi{i}_mps2"
(unit-suffixed, matching this repo's naming convention) rather than Unity SITL's
bare "Phi{i}" -- _plot_control_diagnostics's phi_cols lookup below only matches
on a "Phi" prefix, so this still works without any column_mapping entry.
"""
from __future__ import annotations

import os
import argparse

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation


def _plot_control_diagnostics(
    df: pd.DataFrame,
    output_dir: str,
    base_filename: str,
    cost: float | None,
    e_rms: float | None,
    u_rms: float | None,
    u_dot_rms: float | None,
) -> None:
    """2x2: phi (NN feedforward term) components, u components, ||u||, ||u_dot||
    -- phi only exists for resnet/integrated_resnet (src/run_sim.py leaves
    Phi* columns out of the CSV entirely for other controller types)."""
    fig, ((ax_phi, ax_u), (ax_u_norm, ax_udot_norm)) = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"Control Diagnostics: {base_filename}", fontsize=16, fontweight='bold', y=0.985)

    summary_parts = []
    if cost is not None:
        summary_parts.append(f"Cost: {cost:.4f}")
    if e_rms is not None:
        summary_parts.append(f"e_RMS: {e_rms:.4f} m")
    if u_rms is not None:
        summary_parts.append(f"u_RMS: {u_rms:.4f} m/s²")
    if u_dot_rms is not None:
        summary_parts.append(f"u_dot_RMS: {u_dot_rms:.4f} m/s³")
    if summary_parts:
        fig.text(0.5, 0.945, "   |   ".join(summary_parts), ha='center', fontsize=12)

    phi_cols = [col for col in df.columns if col.startswith('Phi')]
    if phi_cols:
        for phi_col in phi_cols:
            ax_phi.plot(df['Time_s'], df[phi_col], linewidth=1.5, label=phi_col)
        ax_phi.legend()
    else:
        ax_phi.text(0.5, 0.5, "No phi (NN feedforward) term\nfor this controller type",
                    ha='center', va='center', transform=ax_phi.transAxes, fontsize=11, color='gray')
    ax_phi.set_title(r"NN Feedforward Term ($\phi$) Components")
    ax_phi.set_xlabel("Time (s)")
    ax_phi.set_ylabel(r"$\phi$ (m/s²)")
    ax_phi.grid(True)

    ax_u.plot(df['Time_s'], df['ux_mps2'], linewidth=1.5, label='ux_mps2')
    ax_u.plot(df['Time_s'], df['uy_mps2'], linewidth=1.5, label='uy_mps2')
    ax_u.plot(df['Time_s'], df['uz_mps2'], linewidth=1.5, label='uz_mps2')
    ax_u.set_title("Control Input ($u$) Components")
    ax_u.set_xlabel("Time (s)")
    ax_u.set_ylabel("u (m/s²)")
    ax_u.legend()
    ax_u.grid(True)

    ax_u_norm.plot(df['Time_s'], df['Control_Output_Norm_mps2'], 'b-', linewidth=1.5)
    ax_u_norm.set_title(r"$||u||$ Over Time")
    ax_u_norm.set_xlabel("Time (s)")
    ax_u_norm.set_ylabel("||u|| (m/s²)")
    ax_u_norm.grid(True)

    udot_norm = np.linalg.norm(df[['udotx_mps3', 'udoty_mps3', 'udotz_mps3']].to_numpy(), axis=1)
    ax_udot_norm.plot(df['Time_s'], udot_norm, 'r-', linewidth=1.5)
    ax_udot_norm.set_title(r"$||\dot{u}||$ Over Time")
    ax_udot_norm.set_xlabel("Time (s)")
    ax_udot_norm.set_ylabel(r"$||\dot{u}||$ (m/s³)")
    ax_udot_norm.grid(True)

    plt.tight_layout(rect=(0, 0, 1, 0.93))
    diagnostics_filepath = os.path.join(output_dir, f"{base_filename}_control_diagnostics.svg")
    plt.savefig(diagnostics_filepath)
    print(f"[*] Saved control diagnostics plot to: {diagnostics_filepath}")
    plt.close(fig)


def run_post_flight_analysis(
    latest_csv: str,
    write_plots: bool = True,
    write_animation: bool = False,
    cost: float | None = None,
    e_rms: float | None = None,
    u_rms: float | None = None,
    u_dot_rms: float | None = None,
) -> None:
    if not (write_plots or write_animation):
        return

    print(f"[*] Analyzing: {latest_csv}")
    df = pd.read_csv(latest_csv)

    # Standardize column names to ros_node format. aviary_rise_node.write_csv's
    # position columns carry a _m unit suffix (x_m/y_m/z_m/xd_m/yd_m/zd_m) unlike
    # Unity SITL's src/run_sim.py (bare x/y/z/xd/yd/zd) -- both map down to the same
    # bare names the rest of this module plots against.
    column_mapping = {
        'time': 'Time_s',
        'error_norm': 'Error_Norm_m',
        'q_x': 'x', 'q_y': 'y', 'q_z': 'z',
        'qd_x': 'xd', 'qd_y': 'yd', 'qd_z': 'zd',
        'x_m': 'x', 'y_m': 'y', 'z_m': 'z',
        'xd_m': 'xd', 'yd_m': 'yd', 'zd_m': 'zd',
    }
    for col in df.columns:
        if col.startswith('w_'):
            column_mapping[col] = f"W{col[2:]}"
    df = df.rename(columns=column_mapping)

    # --- Calculate Decoupled Errors ---
    # XY Tracking Error Norm: sqrt((x - xd)^2 + (y - yd)^2)
    df['Error_XY'] = np.sqrt((df['x'] - df['xd'])**2 + (df['y'] - df['yd'])**2)

    # Z Tracking Error Norm: |z - zd|
    df['Error_Z'] = np.abs(df['z'] - df['zd'])

    # --- Setup Output Directory ---
    output_dir = os.path.dirname(latest_csv)
    # If the file is just in the current directory, os.path.dirname might return ''
    if not output_dir:
        output_dir = "."
    base_filename = os.path.basename(latest_csv).replace('.csv', '')

    if write_plots:
        # --- Generate Static Summary Plot ---
        fig_static = plt.figure(figsize=(14, 8))
        plt.suptitle(f"Flight Analysis: {base_filename}", fontsize=16, fontweight='bold')

        summary_parts = []
        if cost is not None:
            summary_parts.append(f"Cost: {cost:.4f}")
        if e_rms is not None:
            summary_parts.append(f"e_RMS: {e_rms:.4f} m")
        if u_rms is not None:
            summary_parts.append(f"u_RMS: {u_rms:.4f} m/s²")
        if u_dot_rms is not None:
            summary_parts.append(f"u_dot_RMS: {u_dot_rms:.4f} m/s³")
        if summary_parts:
            fig_static.text(0.5, 0.93, "   |   ".join(summary_parts), ha='center', fontsize=12)

        # Subplot 1: Top-Down XY View
        ax1 = plt.subplot(1, 2, 1)
        ax1.plot(df['xd'], df['yd'], 'k--', label='Desired Trajectory', alpha=0.7)
        ax1.plot(df['x'], df['y'], 'b-', label='Actual Flight Path', linewidth=2)
        ax1.scatter(df['x'].iloc[0], df['y'].iloc[0], color='green', marker='o', s=100, label='Start')
        ax1.scatter(df['x'].iloc[-1], df['y'].iloc[-1], color='red', marker='X', s=100, label='End')
        ax1.set_title("Top-Down Trajectory (X-Y Plane)")
        ax1.set_xlabel("X Position (m)")
        ax1.set_ylabel("Y Position (m)")
        ax1.legend()
        ax1.grid(True)
        ax1.axis('equal')

        # Subplot 2: XY Error
        ax2 = plt.subplot(2, 2, 2)
        ax2.plot(df['Time_s'], df['Error_XY'], 'm-', linewidth=2)
        ax2.set_title("Horizontal Tracking Error Norm ($e_{xy}$)")
        ax2.set_ylabel("Error (m)")
        ax2.grid(True)

        # Subplot 3: Z Error
        ax3 = plt.subplot(2, 2, 4, sharex=ax2)
        ax3.plot(df['Time_s'], df['Error_Z'], 'c-', linewidth=2)
        ax3.set_title("Vertical Tracking Error Norm ($e_z$)")
        ax3.set_xlabel("Time (s)")
        ax3.set_ylabel("Error (m)")
        ax3.grid(True)

        plt.tight_layout()
        static_filepath = os.path.join(output_dir, f"{base_filename}_summary.svg")
        plt.savefig(static_filepath)
        print(f"[*] Saved static summary to: {static_filepath}")
        plt.close(fig_static)

        # --- Generate Weights Plot ---
        weight_cols = [col for col in df.columns if col.startswith('W')]
        if weight_cols:
            fig_weights = plt.figure(figsize=(12, 6))
            plt.title(f"ResNet Weights Evolution: {base_filename}", fontsize=14, fontweight='bold')
            for w_col in weight_cols:
                plt.plot(df['Time_s'], df[w_col], alpha=0.6, linewidth=1)
            plt.xlabel("Time (s)")
            plt.ylabel("Weight Value")
            plt.grid(True)
            plt.tight_layout()
            weights_filepath = os.path.join(output_dir, f"{base_filename}_weights.svg")
            plt.savefig(weights_filepath)
            print(f"[*] Saved weights plot to: {weights_filepath}")
            plt.close(fig_weights)

        # --- Generate Desired Trajectory 3D and Projections Plot ---
        fig_traj = plt.figure(figsize=(14, 10))
        plt.suptitle(f"Desired Trajectory: {base_filename}", fontsize=16, fontweight='bold')

        # 3D View
        ax_3d = fig_traj.add_subplot(2, 2, 1, projection='3d')
        ax_3d.plot(df['xd'], df['yd'], df['zd'], 'k--', label='Desired Trajectory')
        ax_3d.scatter(df['xd'].iloc[0], df['yd'].iloc[0], df['zd'].iloc[0], color='green', marker='o', s=50, label='Start')
        ax_3d.scatter(df['xd'].iloc[-1], df['yd'].iloc[-1], df['zd'].iloc[-1], color='red', marker='X', s=50, label='End')
        ax_3d.set_title("3D View")
        ax_3d.set_xlabel("X (m)")
        ax_3d.set_ylabel("Y (m)")
        ax_3d.set_zlabel("Z (m)")
        ax_3d.grid(True)
        ax_3d.legend()

        # Top View (XY)
        ax_xy = fig_traj.add_subplot(2, 2, 2)
        ax_xy.plot(df['xd'], df['yd'], 'k--')
        ax_xy.scatter(df['xd'].iloc[0], df['yd'].iloc[0], color='green', marker='o', s=50)
        ax_xy.scatter(df['xd'].iloc[-1], df['yd'].iloc[-1], color='red', marker='X', s=50)
        ax_xy.set_title("Top View (XY Plane)")
        ax_xy.set_xlabel("X (m)")
        ax_xy.set_ylabel("Y (m)")
        ax_xy.grid(True)
        ax_xy.axis('equal')

        # Side View (XZ)
        ax_xz = fig_traj.add_subplot(2, 2, 3)
        ax_xz.plot(df['xd'], df['zd'], 'k--')
        ax_xz.scatter(df['xd'].iloc[0], df['zd'].iloc[0], color='green', marker='o', s=50)
        ax_xz.scatter(df['xd'].iloc[-1], df['zd'].iloc[-1], color='red', marker='X', s=50)
        ax_xz.set_title("Side View (XZ Plane)")
        ax_xz.set_xlabel("X (m)")
        ax_xz.set_ylabel("Z (m)")
        ax_xz.grid(True)
        ax_xz.axis('equal')

        # Side View (YZ)
        ax_yz = fig_traj.add_subplot(2, 2, 4)
        ax_yz.plot(df['yd'], df['zd'], 'k--')
        ax_yz.scatter(df['yd'].iloc[0], df['zd'].iloc[0], color='green', marker='o', s=50)
        ax_yz.scatter(df['yd'].iloc[-1], df['zd'].iloc[-1], color='red', marker='X', s=50)
        ax_yz.set_title("Side View (YZ Plane)")
        ax_yz.set_xlabel("Y (m)")
        ax_yz.set_ylabel("Z (m)")
        ax_yz.grid(True)
        ax_yz.axis('equal')

        plt.tight_layout()
        traj_filepath = os.path.join(output_dir, f"{base_filename}_desired_trajectory.svg")
        plt.savefig(traj_filepath)
        print(f"[*] Saved desired trajectory plot to: {traj_filepath}")
        plt.close(fig_traj)

        # --- Generate Control Diagnostics Plot (phi / u / u_dot) ---
        _plot_control_diagnostics(df, output_dir, base_filename, cost, e_rms, u_rms, u_dot_rms)

    if write_animation:
        # --- Generate Animated XY Plot (Real-Time Synced) ---
        print("[*] Generating animation...")
        fig_anim, ax_anim = plt.subplots(figsize=(8, 8))
        ax_anim.set_title("Top-Down Trajectory Animation (Real-Time)")
        ax_anim.set_xlabel("X Position (m)")
        ax_anim.set_ylabel("Y Position (m)")
        ax_anim.grid(True)
        ax_anim.axis('equal')

        # Set static limits based on data bounds with a 10% margin
        x_min, x_max = min(df['x'].min(), df['xd'].min()), max(df['x'].max(), df['xd'].max())
        y_min, y_max = min(df['y'].min(), df['yd'].min()), max(df['y'].max(), df['yd'].max())
        margin_x = (x_max - x_min) * 0.1
        margin_y = (y_max - y_min) * 0.1
        ax_anim.set_xlim(x_min - margin_x, x_max + margin_x)
        ax_anim.set_ylim(y_min - margin_y, y_max + margin_y)

        # Plot static desired trajectory in background
        ax_anim.plot(df['xd'], df['yd'], 'k--', label='Desired Path', alpha=0.4)

        # Initialize moving elements
        line_actual, = ax_anim.plot([], [], 'b-', linewidth=2, label='Flight Path (5s trail)')
        point_actual, = ax_anim.plot([], [], 'ro', markersize=8, label='Quadcopter')
        point_desired, = ax_anim.plot([], [], 'go', markerfacecolor='none', markersize=10, markeredgewidth=2, label='Target Position')

        # Initialize Stopwatch (Anchored to top-left of the axes)
        time_text = ax_anim.text(0.03, 0.95, '', transform=ax_anim.transAxes, fontsize=12,
                                 fontweight='bold', bbox=dict(facecolor='white', alpha=0.8, edgecolor='black'))

        ax_anim.legend(loc="upper right")

        # --- Real-Time Sync & Interpolation ---
        fps = 30  # Change this to 60 if you want a smoother video, time will still be 1x real-time
        duration = df['Time_s'].max()
        video_times = np.arange(0, duration, 1.0 / fps)

        # Interpolate data to match exact video frames to prevent speed-up/slow-down
        x_vals = np.interp(video_times, df['Time_s'], df['x'])
        y_vals = np.interp(video_times, df['Time_s'], df['y'])
        xd_vals = np.interp(video_times, df['Time_s'], df['xd'])
        yd_vals = np.interp(video_times, df['Time_s'], df['yd'])

        # Trail mathematics
        trail_length_seconds = 5.0
        trail_frames = int(trail_length_seconds * fps)

        def init():
            line_actual.set_data([], [])
            point_actual.set_data([], [])
            point_desired.set_data([], [])
            time_text.set_text('')
            return line_actual, point_actual, point_desired, time_text

        def update(frame):
            # Calculate start index for the 5-second disappearing trail
            start_idx = max(0, frame - trail_frames)

            # Update trail
            line_actual.set_data(x_vals[start_idx:frame+1], y_vals[start_idx:frame+1])

            # Update leading points
            point_actual.set_data([x_vals[frame]], [y_vals[frame]])
            point_desired.set_data([xd_vals[frame]], [yd_vals[frame]])

            # Update stopwatch
            time_text.set_text(f"Elapsed: {video_times[frame]:.2f} s")

            return line_actual, point_actual, point_desired, time_text

        anim = animation.FuncAnimation(
            fig_anim, update, frames=len(video_times),
            init_func=init, blit=True
        )

        anim_filepath = os.path.join(output_dir, f"{base_filename}_animation.mp4")
        writer = animation.FFMpegWriter(fps=fps, metadata=dict(artist='Aviary'), bitrate=2500)

        print(f"[*] Saving MP4 animation at 1x real-time (this takes a few seconds)...")
        anim.save(anim_filepath, writer=writer)

        print(f"[*] Saved animation to: {anim_filepath}")
        plt.close(fig_anim)

    print("[*] Analysis Complete.")


def main():
    parser = argparse.ArgumentParser(description="Analyze and Plot Flight CSV")
    parser.add_argument("csv_path", type=str, help="Path to the flight data CSV file")
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"[!] Error: File not found at {args.csv_path}")
        return

    run_post_flight_analysis(args.csv_path)


if __name__ == "__main__":
    main() 