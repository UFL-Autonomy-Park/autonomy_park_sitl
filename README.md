# autonomy_park_sitl

Gazebo Harmonic SITL with our lab's custom "homebrew" quadcopter models, flying in a
model of the UF Autonomy Park, on PX4 v1.16.2 with a ROS 2 Humble bridge.

## Layout

| Path | What it is |
|---|---|
| `PX4-Autopilot/` | PX4 flight stack (submodule, pinned to v1.16.2) |
| `Micro-XRCE-DDS-Agent/` | DDS agent that bridges PX4's uXRCE-DDS client to ROS 2 (submodule) |
| `ros2_ws/src/px4_msgs/` | ROS 2 message definitions matching PX4 v1.16.2 (submodule) |
| `px4-additions/` | **Source of truth** for the custom model, world, and airframe — see [Custom assets](#custom-assets-px4-additions) |
| `scripts/` | Setup and launch scripts, described below |

## Prerequisites

- Ubuntu 22.04, ROS 2 Humble
- Gazebo Harmonic (`gz sim`, tested against 8.15.0)
- `git-lfs` (large meshes/textures in `px4-additions/` are stored via LFS)
- PX4's own SITL build dependencies — if you haven't set these up before, run
  `PX4-Autopilot/Tools/setup/ubuntu.sh` after `scripts/init.sh` (step 1 below)

## One-time setup

### 1. Initialize submodules and pull LFS assets

```bash
./scripts/init.sh
```

This pulls the Git LFS content (custom STL meshes and world textures — these
are tracked as LFS pointers in git, so without this step they're a few bytes
of pointer text, not real meshes) and recursively initializes all
submodules, including PX4's own nested submodules (NuttX, MAVLink, etc.).

### 2. Sync the custom model/world/airframe into PX4-Autopilot

```bash
./scripts/write_px4_with_px4_additions.sh
```

(This sources `scripts/set_env.sh` itself — no need to source it first.)

This copies `px4-additions/{models,params,worlds}` into the matching
`PX4-Autopilot/{Tools/simulation/gz/models, ROMFS/.../airframes,
Tools/simulation/gz/worlds}` directories, and registers any new airframe
file in `airframes/CMakeLists.txt` (PX4 only stages airframes that are
explicitly listed there — see [Troubleshooting](#troubleshooting)). Re-run
this script any time you change something under `px4-additions/`. It's
idempotent — safe to run repeatedly.

If `PX4-Autopilot/build/` already exists, the script will remind you to
reconfigure (see below) so the new files actually take effect.

## Building

### PX4 SITL

```bash
cd PX4-Autopilot
make px4_sitl gz_homebrew_autonomy_park
```

This builds PX4 **and** launches it against Gazebo with the custom
`homebrew` model in the `autonomy_park` world in one step (PX4's build
system generates a `gz_<model>_<world>` target for every
model/world combination it finds). The first build takes a while.

To build without launching a simulation, use the default target:

```bash
make px4_sitl
```

### Micro XRCE-DDS Agent

```bash
cd Micro-XRCE-DDS-Agent
mkdir -p build && cd build
cmake -DUAGENT_USE_SYSTEM_FASTCDR=ON -DUAGENT_USE_SYSTEM_FASTDDS=ON ..
make -j"$(nproc)"
sudo make install
sudo ldconfig /usr/local/lib/
```

### px4_msgs / ROS 2 workspace

```bash
cd ros2_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select px4_msgs
source install/local_setup.bash
```

## Running a SITL simulation

In separate terminals:

```bash
# 1. DDS agent (bridges PX4 <-> ROS 2)
MicroXRCEAgent udp4 -p 8888

# 2. PX4 SITL + Gazebo, with the custom world
cd PX4-Autopilot && make px4_sitl gz_homebrew_autonomy_park
```

`scripts/spawn-sim-env.sh` is an alternative to step 2 for when you want to
launch the already-built `px4` binary directly (e.g. for scripted/headless
runs) instead of going through `make`. It sources `scripts/set_env.sh`
itself, so just run it:

```bash
./scripts/spawn-sim-env.sh
```

It launches a single PX4 instance against `PX4-Autopilot/build/px4_sitl_default/bin/px4`
using the model/world/home-position from `scripts/set_env.sh`, waits for the
"Ready for takeoff!" log line, and stays alive so the background process
doesn't get reaped — `Ctrl-C` to stop it.

Once running, `ros2 topic list` (after sourcing `ros2_ws/install/setup.bash`)
should show PX4's uORB topics bridged over DDS.

## Custom assets (`px4-additions/`)

- `models/homebrew/` — the flight model: includes `homebrew_base` plus
  sensor plugins (`LW20` downward LiDAR, `OakD-Lite` depth camera,
  `optical_flow`).
- `models/homebrew_base/` — the airframe body and motor meshes (`meshes/*.STL`,
  tracked via Git LFS).
- `params/4025_gz_homebrew` — the PX4 airframe startup script. Autostart ID
  `4025`.
- `worlds/autonomy_park.sdf` (+ `worlds/materials/`) — the UF Autonomy Park
  world, textures tracked via Git LFS.

**Note on the autostart ID:** PX4 reserves `4000`–`4999` for its own
built-in Gazebo models and `22000`–`22999` for custom ones (see the comment
in `PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/CMakeLists.txt`).
`4025` currently sits in PX4's own reserved range, so a future
`PX4-Autopilot` submodule bump could claim that number for a new stock
model. Consider renumbering to something in `22000`–`22999` (rename
`params/4025_gz_homebrew`, and update `PX4_SYS_AUTOSTART` in
`scripts/set_env.sh`) before relying on this long term.

To add or change a model/world/airframe: edit files under `px4-additions/`,
then re-run `scripts/write_px4_with_px4_additions.sh`.

## Troubleshooting

**`ERROR [init] Unknown model gz_homebrew (not found by name on
.../rootfs/etc/init.d-posix/airframes)`, even after removing `build/` and
reconfiguring:**
PX4 does not glob its airframes directory for the build — every staged file
must be listed explicitly in
`PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/CMakeLists.txt`'s
`px4_add_romfs_files(...)` call. `scripts/write_px4_with_px4_additions.sh`
now does this registration automatically; if you copied `px4-additions/`
into `PX4-Autopilot` by hand instead, add the airframe filename to that list
yourself.

**Gazebo logs `[Err] [STLLoader.cc] Unable to read STL[...]` /
`Cannot load mesh with zero sub-meshes`, or the model renders without any
of its meshes:**
The `.STL`/texture files are still Git LFS pointer stubs (a few hundred
bytes of text), not the real binary content — `git lfs pull` was never run.
`scripts/init.sh` does this for you; if you're hitting this after cloning
by hand, run `git lfs pull` at the repo root, then re-run
`scripts/write_px4_with_px4_additions.sh` to re-copy the real files into
`PX4-Autopilot`.

**A new world or airframe doesn't show up as a `make px4_sitl gz_<model>_<world>`
target after syncing:**
PX4's CMake globs the worlds directory and airframes list at *configure*
time. `scripts/write_px4_with_px4_additions.sh` will tell you if a
`build/` directory already exists; when it does, remove and rebuild:
`rm -rf PX4-Autopilot/build/px4_sitl_default`, then re-run your `make`
command.

## Scripts reference

| Script | Purpose |
|---|---|
| `scripts/init.sh` | Pulls Git LFS assets and initializes all submodules (including PX4's nested ones). Run once after cloning. |
| `scripts/set_env.sh` | Exports shared env vars (`PROJECT_ROOT`, `PX4_DIR`, `PX4_SIM_MODEL`, `PX4_GZ_WORLD`, home position, etc). The other scripts source it themselves — you only need to `source scripts/set_env.sh` by hand if you want these vars in your own shell, e.g. to override `PX4_GZ_WORLD` before `make px4_sitl gz_homebrew` (the world-less target) or to call PX4 tools directly. Must be `source`d, not executed. |
| `scripts/write_px4_with_px4_additions.sh` | Copies `px4-additions/` into `PX4-Autopilot/` and registers any new airframe. Re-run after editing `px4-additions/`. |
| `scripts/spawn-sim-env.sh` | Launches a single PX4 SITL instance directly against the built `px4` binary, without going through `make`. |
