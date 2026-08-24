"""
Regenerates the hill's two shape files: hill_heightmap.png (visual) and
hill_collision_box.obj (collision). Run this whenever you change the hill's
SIZE. You do NOT need this for moving the hill -- position lives in the
.sdf's <pos>/<pose> values, not here.

After running, update the .sdf's:
  <size>FOOT_X FOOT_Y HEIGHT</size>   (inside the visual's <heightmap>)
to match whatever you set below. The collision mesh needs no <size> tag --
its own vertices already encode the size.

Output paths are computed relative to THIS SCRIPT'S OWN location, not the
current working directory -- so it's safe to run from anywhere (`python3
generate_hill.py`, `python3 scripts/generate_hill.py` from elsewhere, an
IDE's run button, etc.) and it doesn't assume any particular project folder
name or location. It assumes only the fixed layout relative to itself:

    <world_dir>/
      scripts/generate_hill.py   <- this file
      materials/textures/        <- heightmap goes here
      meshes/                    <- collision obj goes here

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
MESHES_DIR = WORLD_DIR / "meshes"
HEIGHTMAP_PATH = TEXTURES_DIR / "hill_heightmap.png"
COLLISION_OBJ_PATH = MESHES_DIR / "hill_collision_box.obj"


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


def generate_frustum_obj():
    bottom_x, bottom_y = FOOT_X, FOOT_Y
    top_x = FOOT_X - 2 * TRANSITION
    top_y = FOOT_Y - 2 * TRANSITION
    if top_x <= 0 or top_y <= 0:
        raise ValueError(
            f"TRANSITION ({TRANSITION}) is too large for this footprint -- "
            f"the plateau would have zero or negative size ({top_x} x {top_y})."
        )

    bx, by = bottom_x / 2, bottom_y / 2
    tx, ty = top_x / 2, top_y / 2

    verts = np.array([
        (-bx, -by, 0), (bx, -by, 0), (bx, by, 0), (-bx, by, 0),          # 0-3 bottom
        (-tx, -ty, HEIGHT), (tx, -ty, HEIGHT), (tx, ty, HEIGHT), (-tx, ty, HEIGHT),  # 4-7 top
    ])
    centroid = verts.mean(axis=0)
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]

    def fix_winding(face):
        a, b, c = verts[face[0]], verts[face[1]], verts[face[2]]
        normal = np.cross(b - a, c - a)
        face_center = verts[list(face)].mean(axis=0)
        return face if np.dot(normal, face_center - centroid) >= 0 else tuple(reversed(face))

    lines = [f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}" for v in verts]

    fixed_faces = [fix_winding(f) for f in faces]

    # One flat normal per face (not per vertex) -- correct for a faceted solid
    # like this frustum, where each face is planar and shouldn't be smoothed
    # into its neighbors. Re-derived from the (already winding-corrected) face.
    normal_lines = []
    for f in fixed_faces:
        a, b, c = verts[f[0]], verts[f[1]], verts[f[2]]
        n = np.cross(b - a, c - a)
        n = n / np.linalg.norm(n)
        normal_lines.append(f"vn {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}")
    lines += normal_lines

    for face_idx, f in enumerate(fixed_faces):
        a, b, c, d = [i + 1 for i in f]  # OBJ is 1-indexed
        vn = len(verts) + face_idx + 1   # this face's normal index (1-indexed, after all v lines)
        lines.append(f"f {a}//{vn} {b}//{vn} {c}//{vn}")
        lines.append(f"f {a}//{vn} {c}//{vn} {d}//{vn}")

    MESHES_DIR.mkdir(parents=True, exist_ok=True)
    with open(COLLISION_OBJ_PATH, 'w') as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {COLLISION_OBJ_PATH} (bottom {bottom_x}x{bottom_y}, "
          f"top {top_x}x{top_y}, height {HEIGHT})")


if __name__ == "__main__":
    generate_heightmap()
    generate_frustum_obj()
    print(f"\nNow update the .sdf's heightmap <size> to: {FOOT_X} {FOOT_Y} {HEIGHT}")
