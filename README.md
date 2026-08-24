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

### MAVROS

`sudo apt-get install ros-humble-mavros ros-humble-mavros-extras ros-humble-mavros-msgs`
(will be installed by `init.sh`).

### geodesy

`sudo apt-get install ros-humble-geodesy` (needed by `aero_common`; will be
installed by `init.sh`).

### Gazebo Harmonic

Install per <https://gazebosim.org/docs/harmonic/install_ubuntu/> (`gz sim`,
tested with 8.15.0).

### Git LFS

Install per <https://git-lfs.com/> (will be installed by `init.sh` if not
already present).

## One-time setup

```bash
./scripts/init.sh
```

Installs Git LFS (if needed) and pulls its content, initializes all
submodules (including PX4's own nested submodules), installs PX4's own SITL
build dependencies (into a project-local Python venv, `venv_host/`), and
installs MAVROS and geodesy. Safe to re-run — it skips steps that are
already done. If something fails, the
error names the exact step and command, so just fix that and re-run.

## Building & running a SITL simulation

Syncs `px4-additions/` and builds PX4 SITL — re-run after changing anything
under `px4-additions/`:

```bash
./scripts/build_px4.sh
```

Launches a standalone Gazebo instance (no PX4 yet), waits for the world to
be ready, and stays alive so the background process doesn't get reaped —
`Ctrl-C` to stop it. Loading the world is the slow part, so run this once
and leave it running:

```bash
./scripts/launch_gazebo.sh
```

With Gazebo already running (see above), spawns a single PX4 instance
against it and stays alive — `Ctrl-C` to stop just PX4, leaving Gazebo
running. Re-run this any time you want to reset the vehicle's pose: it kills
any previous PX4 instance first (see below), then either spawns the vehicle
model for the first time or, if it's still there from a previous run,
resets its pose and re-attaches PX4 to it. PX4's EKF crashes if you
teleport its rigid body mid-run (a PX4 limitation), so a full PX4 restart —
not a world reload — is the only way to reset pose, which is why this is a
separate script from `launch_gazebo.sh`:

```bash
./scripts/spawn_one_homebrew_instance.sh
```

Kills whatever PX4 instance `spawn_one_homebrew_instance.sh` last spawned,
without restarting Gazebo or touching the vehicle model — Gazebo Harmonic's
rendering engine reliably crashes if a model with camera sensors is removed
and recreated, so the model is deliberately left in place and reused on the
next spawn instead. Safe to run any time, including when nothing is
running — `spawn_one_homebrew_instance.sh` also calls this itself before
spawning:

```bash
./scripts/kill_all_homebrew_instances.sh
```

## Running the ROS 2 autonomy stack

Builds every package under `ros2_ws/src` with `colcon` — re-run after
changing anything there:

```bash
./scripts/build_ros2_autonomy_stack.sh
```

With Gazebo and a PX4 instance already running (see above), this launches MAVROS,
`px4_telemetry`, `px4_teleop`, `px4_safety_lib`, and the RViz2
visualization together:

```bash
./scripts/launch_ros2_autonomy_stack.sh
```

This runs `ros2_ws/src/aero_common`'s single-agent launch file, which
connects MAVROS to PX4 SITL's default MAVLink port. Only single-agent
setups have been tested against this SITL — the multi-agent launch files
under `aero_common/minimal_startup_air/launch/` are untested here.

### DDS scoping (`ROS_LOCALHOST_ONLY`)

`set_env.sh` forces every script that sources it onto `ROS_LOCALHOST_ONLY=1`
and unsets any lab/robot-network DDS config (`FASTRTPS_DEFAULT_PROFILES_FILE`,
`ROS_DISCOVERY_SERVER`, `RMW_IMPLEMENTATION`) your `~/.bashrc` might set for
real-hardware use, so this SITL never has to fight a static-IP interface
whitelist or an unreachable discovery server. This only takes effect for
processes actually started from a shell that sourced `set_env.sh` — a DDS
participant's config is fixed at that process's own startup and nothing
sourced afterward, in this or any other terminal, can change it. So:

- Launch everything for this SITL (`launch_gazebo.sh`,
  `launch_ros2_autonomy_stack.sh`, and any manual `ros2 run`/`rviz2`/etc.)
  from a terminal that has sourced `set_env.sh`. A stray node started from a
  plain terminal will keep broadcasting on your real network interfaces for
  as long as it runs, not just localhost.
- `ros2 topic list` (and `node list`, etc.) can be misleading: those
  commands are served by a single background `ros2` daemon shared by every
  terminal on the machine, which locks in whatever DDS config was active
  when it first started and ignores what any later terminal sources. So a
  terminal that never sourced `set_env.sh` can still *list* this SITL's
  topics if that shared daemon happens to be loopback-scoped from an earlier
  session — but `ros2 topic echo`/actual subscriptions open their own
  connection using that terminal's real env, so they'll correctly hang with
  no messages. If a topic listing looks wrong, run `ros2 daemon stop` (it
  respawns fresh on the next `ros2` command) rather than trusting it as-is.

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
| `scripts/launch_gazebo.sh` | Launches a standalone Gazebo instance (no PX4). Run once; leave it running. |
| `scripts/spawn_one_homebrew_instance.sh` | Spawns a single PX4 instance against an already-running Gazebo. Run after `scripts/launch_gazebo.sh`; re-run any time to reset the vehicle's pose. |
| `scripts/kill_all_homebrew_instances.sh` | Kills whatever `spawn_one_homebrew_instance.sh` last spawned, without touching Gazebo. Safe to run any time. |
| `scripts/build_ros2_autonomy_stack.sh` | Builds every package under `ros2_ws/src` with `colcon`. Run after changing anything there or after cloning for the first time. |
| `scripts/launch_ros2_autonomy_stack.sh` | Launches MAVROS + the autonomy stack. Run after `scripts/spawn_one_homebrew_instance.sh`. |

## Contact

Max Gardenswartz — [mgardenswartz@ufl.edu](mailto:mgardenswartz@ufl.edu)
