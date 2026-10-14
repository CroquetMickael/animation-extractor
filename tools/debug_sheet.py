"""Contact sheet: source frame | GTA skeleton front view | side view. Usage: debug_sheet.py PROJECT_ID OUT.png FRAME [FRAME...]"""
import sys

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from animx import pipeline, project, skeleton  # noqa: E402

LINKS = [
    ("SKEL_Pelvis", "SKEL_Spine0"), ("SKEL_Spine0", "SKEL_Spine1"), ("SKEL_Spine1", "SKEL_Spine2"), ("SKEL_Spine2", "SKEL_Spine3"),
    ("SKEL_Spine3", "SKEL_Neck_1"), ("SKEL_Neck_1", "SKEL_Head"),
]
for s in "LR":
    LINKS += [(f"SKEL_{s}_Thigh", f"SKEL_{s}_Calf"), (f"SKEL_{s}_Calf", f"SKEL_{s}_Foot"), (f"SKEL_{s}_Foot", f"SKEL_{s}_Toe0"),
              ("SKEL_Spine3", f"SKEL_{s}_Clavicle"), (f"SKEL_{s}_Clavicle", f"SKEL_{s}_UpperArm"), (f"SKEL_{s}_UpperArm", f"SKEL_{s}_Forearm"),
              (f"SKEL_{s}_Forearm", f"SKEL_{s}_Hand"), (f"SKEL_{s}_Hand", f"SKEL_{s}_Finger20"), ("SKEL_Pelvis", f"SKEL_{s}_Thigh")]


def main():
    p = project.load(sys.argv[1])
    out = sys.argv[2]
    frames = [int(f) for f in sys.argv[3:]]
    skel = skeleton.load(p.settings["ped"])
    clip = {"id": "debug", "start": 0, "end": p.data["frames"] - 1, "inplace": True, "foot_lock": False, "speed": 1.0, "loop": False, "lock_heading": False}
    motion = pipeline.clip_motion(p, clip)
    local_t = np.broadcast_to(skel.bind_t, motion.local_r.shape[:-1] + (3,)).copy()
    local_t[:, 0] = motion.root_t
    _, world = skel.fk(motion.local_r, local_t)

    video = cv2.VideoCapture(str(p.video))
    fig, axes = plt.subplots(len(frames), 3, figsize=(12, 4 * len(frames)))
    axes = np.atleast_2d(axes)
    for row, f in enumerate(frames):
        video.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, image = video.read()
        axes[row, 0].imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if ok else np.zeros((10, 10, 3)))
        axes[row, 0].set_title(f"video frame {f}")
        for col, (axis, label) in enumerate(((0, "front (X right)"), (1, "side (Y forward)")), start=1):
            ax = axes[row, col]
            for a, b in LINKS:
                if not (skel.has(a) and skel.has(b)):
                    continue
                pa, pb = world[f, skel.index(a)], world[f, skel.index(b)]
                color = "tab:blue" if "_L_" in a + b else ("tab:orange" if "_R_" in a + b else "k")
                h = (-1 if axis == 0 else 1)
                ax.plot([pa[axis] * h, pb[axis] * h], [pa[2], pb[2]], color=color, lw=2)
            ax.axhline(-1.0, color="gray", lw=0.8)
            ax.set_aspect("equal")
            ax.set_xlim(-1, 1)
            ax.set_ylim(-1.1, 0.9)
            ax.set_title(f"GTA {label}")
    fig.tight_layout()
    fig.savefig(out, dpi=70)


if __name__ == "__main__":
    main()
