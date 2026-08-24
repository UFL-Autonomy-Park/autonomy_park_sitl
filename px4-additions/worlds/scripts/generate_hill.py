"""
Regenerates the hill's shape file: hill_heightmap.png. Run this whenever you
change the hill's SIZE. You do NOT need this for moving the hill -- position
lives in the .sdf's <pos>/<pose> values, not here.

This same heightmap is used for BOTH the .sdf's visual and collision
geometry (native heightmap collision, not a hand-made proxy mesh -- an
earlier version of this script also generated a low-poly frustum .obj for
collision, which reliably stuck the vehicle's landing gear on the hill's
sloped sides: a box resting near a seam between two of the frustum's few
large flat faces is a known-bad case for generic mesh collision. Native
heightmap collision uses dedicated heightfield math instead, matching the
rendered terrain exactly with no seams).

After running, update BOTH of the .sdf's:
  <size>FOOT_X FOOT_Y HEIGHT</size>   (inside <heightmap>, visual AND collision)
to match whatever you set below.

Output paths are computed relative to THIS SCRIPT'S OWN location, not the
current working directory -- so it's safe to run from anywhere (`python3
generate_hill.py`, `python3 scripts/generate_hill.py` from elsewhere, an
IDE's run button, etc.) and it doesn't assume any particular project folder
name or location. It assumes only the fixed layout relative to itself:

    <world_dir>/
      scripts/generate_hill.py   <- this file
      materials/textures/        <- heightmap goes here

Requires: pip install pillow numpy
"""
from pathlib import Path
from PIL import Image
import numpy as np

# ---- Edit these, then run the script ----
FOOT_X = 18.0        # footprint size along world x (m)
FOOT_Y = 12.0         # footprint size along world y (m)
TRANSITION = 4.0     # width of the sloped ramp on every side (m)
HEIGHT = 0.75          # plateau height (m)
# -------------------------------------------

RES = 257  # heightmap pixel resolution -- MUST stay square (gz-sim requirement).
           # Doesn't need to change when FOOT_X/FOOT_Y change; higher = smoother
           # slope, at the cost of a bigger file. 257 is plenty for this scale.

# Paths relative to this script's own location, not the cwd.
SCRIPT_DIR = Path(__file__).resolve().parent
WORLD_DIR = SCRIPT_DIR.parent
TEXTURES_DIR = WORLD_DIR / "materials" / "textures"
HEIGHTMAP_PATH = TEXTURES_DIR / "hill_heightmap.png"


def smoothstep(t):
    return t * t * (3 - 2 * t)  # S-curve easing


def generate_heightmap():
    img = np.zeros((RES, RES), dtype=np.uint8)
    for iy in range(RES):
        y_off = iy / (RES - 1) * FOOT_Y
        dy = min(y_off, FOOT_Y - y_off)
        for ix in range(RES):
            x_off = ix / (RES - 1) * FOOT_X
            dx = min(x_off, FOOT_X - x_off)
            d = min(dx, dy)
            t = min(d / TRANSITION, 1.0)
            img[iy, ix] = int(round(smoothstep(t) * 255))
    TEXTURES_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img, mode='L').save(HEIGHTMAP_PATH)
    print(f"wrote {HEIGHTMAP_PATH}")


if __name__ == "__main__":
    generate_heightmap()
    print(f"\nNow update the .sdf's heightmap <size> (visual AND collision) to: {FOOT_X} {FOOT_Y} {HEIGHT}")
