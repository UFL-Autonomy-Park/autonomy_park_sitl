# autonomy_park_sitl

![Screenshot of UF Autonomy Park in Gazebo](images/autonomy_park_sitl.png)

Gazebo Harmonic SITL with custom "Homebrew" quadcopter models, flying in a
model of the UF Autonomy Park, on PX4 v1.16.2 with a ROS 2 Humble bridge.


## Layout

| Path | What it is |
|---|---|
| `PX4-Autopilot/` | PX4 flight stack (submodule, pinned to v1.16.2) |
| `Micro-XRCE-DDS-Agent/` | DDS agent that bridges PX4's uXRCE-DDS client to ROS 2 (submodule, pinned to 2.4.3, unused currently) |
| `ros2_ws/src/px4_msgs/` | ROS 2 message definitions for PX4 (submodule, pinned to v1.16, unused currently) |
| `ros2_ws/src/aero_common/` | MAVROS-based autonomy stack: telemetry, teleop, safety, viz (submodule) — see [Running the ROS 2 autonomy stack](#running-the-ros-2-autonomy-stack) |
| `px4-additions/` | Custom model, world, and parameters — see [Custom assets](#custom-assets-px4-additions) |
| `scripts/` | Setup and launch scripts, described below. `scripts/library/` holds helpers the scripts below call internally — you shouldn't need to run anything in there directly. |

## Prerequisites

### Ubuntu 22.04
Find an ISO at <https://releases.ubuntu.com/jammy/>. This SITL is untested with Docker.

### ROS 2 Humble

Install per <https://docs.ros.org/en/humble/Installation.html>. Also
requires `colcon` (`sudo apt install python3-colcon-common-extensions`) to
build `ros2_ws/`.

### Gazebo Harmonic

Install per <https://gazebosim.org/docs/harmonic/install_ubuntu/> (`gz sim`,
tested with 8.15.0).

### Git LFS

Install per <https://git-lfs.com/>.

## One-time setup

```bash
./scripts/init.sh
```

Pulls Git LFS content, initializes all submodules (including PX4's own
nested submodules), and installs PX4's own SITL build dependencies. Safe to
re-run — it skips steps that are already done. If something fails, the
error names the exact step and command, so just fix that and re-run.

## Building & running a SITL simulation

Syncs `px4-additions/` and builds PX4 SITL — re-run after changing anything
under `px4-additions/`:

```bash
./scripts/build_px4.sh
```

Launches the built PX4 SITL instance against Gazebo, waits for the "Ready
for takeoff!" log line, and stays alive so the background process doesn't
get reaped — `Ctrl-C` to stop it:

```bash
./scripts/launch_gazebo.sh
```

## Running the ROS 2 autonomy stack

Builds every package under `ros2_ws/src` with `colcon` — re-run after
changing anything there:

```bash
./scripts/build_ros2_autonomy_stack.sh
```

With Gazebo/PX4 already running (see above), this launches MAVROS,
`px4_telemetry`, `px4_teleop`, `px4_safety_lib`, and the RViz2
visualization together:

```bash
./scripts/launch_ros2_autonomy_stack.sh
```

This runs `ros2_ws/src/aero_common`'s single-agent launch file, which
connects MAVROS to PX4 SITL's default MAVLink port. Only single-agent
setups have been tested against this SITL — the multi-agent launch files
under `aero_common/minimal_startup_air/launch/` are untested here.

## Custom assets (`px4-additions/`)

- `models/homebrew/` — the flight model: includes `homebrew_base` plus
  sensor plugins (`LW20` downward LiDAR, `OakD-Lite` depth camera,
  `optical_flow`).
- `models/homebrew_base/` — the airframe body and motor meshes (`meshes/*.STL`,
  tracked via Git LFS).
- `params/22000_gz_homebrew` — the PX4 airframe startup script. Autostart
  ID `22000` — the start of PX4's own officially reserved range for custom
  models (see the `[22000, 22999] Reserve for custom models` comment in
  `PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/CMakeLists.txt`).
- `worlds/autonomy_park.sdf` (+ `worlds/materials/`) — the UF Autonomy Park
  world, textures tracked via Git LFS.

## Scripts reference

| Script | Purpose |
|---|---|
| `scripts/init.sh` | One-time setup: pulls Git LFS assets, initializes all submodules (including PX4's nested ones), and installs PX4's own SITL build dependencies. Run once after cloning. |
| `scripts/build_px4.sh` | Syncs `px4-additions/` into `PX4-Autopilot/` and rebuilds PX4 SITL from a clean state. Run after changing anything under `px4-additions/`. |
| `scripts/launch_gazebo.sh` | Launches the built PX4 SITL instance against Gazebo. |
| `scripts/build_ros2_autonomy_stack.sh` | Builds every package under `ros2_ws/src` with `colcon`. Run after changing anything there. |
| `scripts/launch_ros2_autonomy_stack.sh` | Launches MAVROS + the autonomy stack. Run after `scripts/launch_gazebo.sh`. |

## Contact

Max Gardenswartz — [mgardenswartz@ufl.edu](mailto:mgardenswartz@ufl.edu)
