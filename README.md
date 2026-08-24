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
| `ros2_ws/src/aero_common/` | MAVROS-based autonomy stack: telemetry, teleop, safety, viz (submodule) — see [Running the SITL](#running-the-sitl) |
| `px4-additions/` | Custom model, world, and parameters — see [Custom assets](#custom-assets-px4-additions) |
| `scripts/` | Setup and launch scripts, described below. `scripts/library/` holds helpers the scripts below call internally — you shouldn't need to run anything in there directly. |

## Prerequisites

### Ubuntu 22.04
Find an ISO at <https://releases.ubuntu.com/jammy/>. This SITL is untested with Docker, but we have one at
<https://github.com/UFL-Autonomy-Park/ros2-docker/> that works on Windows and Mac (see container tags).
Pass-through of the Gazebo GUI is not available on Mac. TLDR; don't use Gazebo on Mac even with Docker (confer: <https://docs.px4.io/v1.16/en/simulation/>).

### ROS 2 Humble
Install per <https://docs.ros.org/en/humble/Installation.html>. **NOT** installed by `init.sh`.

### Gazebo Harmonic
Install per <https://gazebosim.org/docs/harmonic/install_ubuntu/> (`gz sim`,
tested with 8.15.0). **NOT** installed by `init.sh`.

### MAVROS
Will be installed by `init.sh`.

### geodesy
Will be installed by `init.sh`.

### Git LFS
Will be installed by `init.sh`.

## One-time setup

```bash
./scripts/init.sh
```

Installs above prequisites, initializes all submodules (including PX4's own nested submodules),
and installs PX4's own SITL build dependencies (into a project-local Python venv, `venv_host/`).
Safe to re-run. If something fails, the
error names the exact step and command, so just fix that and re-run.

## Building the SITL

Rebuilds PX4 SITL from a clean state — re-run after changing anything under
`px4-additions/`:

```bash
./scripts/build_px4.sh
```

Builds every package under `ros2_ws/src` with `colcon` — re-run after
changing anything there:

```bash
./scripts/build_ros2_autonomy_stack.sh
```

| Script | Purpose |
|---|---|
| `scripts/build_px4.sh` | Syncs `px4-additions/` into `PX4-Autopilot/` and rebuilds PX4 SITL from a clean state. Run after changing anything under `px4-additions/`. |
| `scripts/build_ros2_autonomy_stack.sh` | Builds every package under `ros2_ws/src` with `colcon`. Run after changing anything there or after cloning for the first time. |

## Running the SITL

Only a single Homebrew instance has been tested so far — this runs
`ros2_ws/src/aero_common`'s single-agent launch file, which connects MAVROS
to PX4 SITL's default MAVLink port; the multi-agent launch files under
`aero_common/minimal_startup_air/launch/` are untested against this SITL.

Each command below runs in the foreground and stays alive until you
`Ctrl-C` it — run each in its own terminal, in order:

Terminal 1 — launches a standalone Gazebo instance (no PX4 yet) and stays
alive. Loading the world is the slow part, so run this once and leave it
running:

```bash
./scripts/launch_gazebo.sh
```

Terminal 2 — once Gazebo is ready, spawns a single PX4 instance against it
and stays alive. Re-run this any time you want to reset the vehicle's pose
— it resets and re-attaches to the existing model rather than reloading the
world:

```bash
./scripts/spawn_one_homebrew_instance.sh
```

Terminal 3 — once PX4 is ready, launches minimal startup from the autonomy stack at `https://github.com/UFL-Autonomy-Park/aero_common`.

```bash
./scripts/launch_ros2_autonomy_stack.sh
```

To reset just the vehicle without restarting Gazebo, re-run Terminal 2's
command (it does this automatically), or run this from any terminal, any
time:

```bash
./scripts/kill_all_homebrew_instances.sh
```

| Script | Purpose |
|---|---|
| `scripts/launch_gazebo.sh` | Launches a standalone Gazebo instance (no PX4). Run once; leave it running. |
| `scripts/spawn_one_homebrew_instance.sh` | Spawns a single PX4 instance against an already-running Gazebo (errors if Gazebo isn't up yet). Re-run any time to reset the vehicle's pose — kills any previous PX4 instance, then resets and re-attaches to the existing model rather than recreating it. |
| `scripts/kill_all_homebrew_instances.sh` | Kills whatever PX4 instance `spawn_one_homebrew_instance.sh` last spawned, without touching Gazebo or the vehicle model. Safe to run any time. |
| `scripts/launch_ros2_autonomy_stack.sh` | Launches MAVROS + the autonomy stack . Run after `scripts/spawn_one_homebrew_instance.sh`. |

## Custom assets (`px4-additions/`)

- `models/homebrew/` — the flight model: includes `homebrew_base` plus
  sensor plugins (`LW20` downward LiDAR, `OakD-Lite` depth camera represening
  our ZED 2 cameras, and `optical_flow` sensors).
- `models/homebrew_base/` — the airframe body and motor meshes (`meshes/*.stl`,
  tracked via Git LFS).
- `params/22000_gz_homebrew` — the PX4 airframe startup script. Autostart
  ID `22000` — the start of PX4's own officially reserved range for custom
  models (see the `[22000, 22999] Reserve for custom models` comment in
  `PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/CMakeLists.txt`).
- `worlds/autonomy_park.sdf` (+ `worlds/materials/`) — the UF Autonomy Park
  world, textures tracked via Git LFS.

## Troubleshooting

> [!WARNING]
> All scripts in this SITL source a file called `set_env.sh`
which sets `ROS_LOCALHOST_ONLY=1`
and unsets any config (`FASTRTPS_DEFAULT_PROFILES_FILE`,
`ROS_DISCOVERY_SERVER`, `RMW_IMPLEMENTATION`) your `~/.bashrc` might set. If
you need to echo topics from the SITL, run `source scripts/library/set_env.sh` first. Otherwise,
while topics may display, they will never echo any messgaes! Since there is only
one `ros2` daemon on any system, this is not fixable. If a topic listing looks wrong
or need to do real-world robotics work, run `ros2 daemon stop` and run the scripts
you need to ensure the `ros2` daemon uses the config in `scripts/library/set_env.sh`.
