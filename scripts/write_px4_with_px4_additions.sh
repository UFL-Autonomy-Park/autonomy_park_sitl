# Run this script from the project root, not within scripts/.


# Define source and destination paths
SRC_DIR="$PROJECT_ROOT/px4-additions"
PX4_DIR="$PROJECT_ROOT/PX4-Autopilot"

# Validate paths
if [[ ! -d "$SRC_DIR" ]]; then
    echo "Error: Source directory '$SRC_DIR' not found." >&2
    exit 1
fi

if [[ ! -d "$PX4_DIR" ]]; then
    echo "Error: PX4-Autopilot directory '$PX4_DIR' not found." >&2
    exit 1
fi

echo "Project Root: $PROJECT_ROOT"
echo "Copying additions from $SRC_DIR to $PX4_DIR..."

# 1. Copy Gazebo Simulation Models
# Dest: PX4-Autopilot/Tools/simulation/gz/models/
GZ_MODELS_DIR="$PX4_DIR/Tools/simulation/gz/models"
mkdir -p "$GZ_MODELS_DIR"
cp -r "$SRC_DIR/models/"* "$GZ_MODELS_DIR/"

# 2. Copy Airframe Parameter files
# Dest: PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/
AIRFRAMES_DIR="$PX4_DIR/ROMFS/px4fmu_common/init.d-posix/airframes"
mkdir -p "$AIRFRAMES_DIR"
cp -r "$SRC_DIR/params/"* "$AIRFRAMES_DIR/"

# 3. Copy Gazebo Simulation Worlds & Textures
# Dest: PX4-Autopilot/Tools/simulation/gz/worlds/
GZ_WORLDS_DIR="$PX4_DIR/Tools/simulation/gz/worlds"
mkdir -p "$GZ_WORLDS_DIR"
cp -r "$SRC_DIR/worlds/"* "$GZ_WORLDS_DIR/"

echo "Successfully synchronized custom assets into PX4-Autopilot."
