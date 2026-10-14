"""Hand placement: keep where the hands are relative to the body, not just the arm angles.

The freemode torso is ~30% taller than an average human's (pelvis->shoulder 0.62 m vs 0.48 m) while the
arms are the same length, so copying arm rotations alone lifts a hand resting on the hip up to the belly.
Low hands are therefore placed relative to the pelvis, raised hands relative to the shoulder, and a
two-bone IK bends the arm to reach that point (wrist orientation and elbow plane are kept).
"""
import numpy as np

from .. import cleanup
from . import smpl

SIDES = (
    ("L", smpl.L_SHOULDER, smpl.L_WRIST),
    ("R", smpl.R_SHOULDER, smpl.R_WRIST),
)
# Hand height on the torso (0 = pelvis, 1 = shoulder) where the anchor moves from pelvis to shoulder.
PELVIS_ANCHOR_BELOW = 0.45
SHOULDER_ANCHOR_ABOVE = 0.95


# How much of the remaining extension the arm may use to reach the placement goal (0 = keep the source
# elbow bend, 1 = straighten fully). Unbounded, a hand resting on the hip of a taller freemode torso
# locked the elbow straight (5° flexion against Rockstar's 50-75° in mini@tennis).
EXTRA_REACH = 0.35


def _limit_reach(shoulder, elbow, wrist, goal):
    """Pull the goal toward the shoulder so the elbow opens only a little beyond its captured bend."""
    full = np.linalg.norm(elbow - shoulder, axis=-1) + np.linalg.norm(wrist - elbow, axis=-1)
    reach = np.linalg.norm(wrist - shoulder, axis=-1)
    allowed = reach + EXTRA_REACH * (full - reach)
    offset = goal - shoulder
    distance = np.linalg.norm(offset, axis=-1).clip(1e-9)
    scale = np.minimum(1.0, allowed / distance)[:, None]
    return shoulder + offset * scale


def place_hands(skel, local_r, joints):
    """joints: source body joints (T, 22, 3) in the same space and scale as the ped (root at the pelvis)."""
    out = local_r.copy()
    world_r, world_p = skel.fk(out)
    pelvis_src = joints[:, smpl.PELVIS]
    up = joints[:, smpl.NECK] - pelvis_src
    up /= np.linalg.norm(up, axis=-1, keepdims=True).clip(1e-9)
    gta_pelvis = world_p[:, skel.index("SKEL_Pelvis")]

    for side, shoulder_j, wrist_j in SIDES:
        upper, fore, hand = (skel.index(f"SKEL_{side}_{b}") for b in ("UpperArm", "Forearm", "Hand"))
        wrist_src = joints[:, wrist_j]
        shoulder_src = joints[:, shoulder_j]

        height = np.sum((wrist_src - pelvis_src) * up, axis=-1)
        span = np.sum((shoulder_src - pelvis_src) * up, axis=-1).clip(1e-3)
        x = np.clip((height / span - PELVIS_ANCHOR_BELOW) / (SHOULDER_ANCHOR_ABOVE - PELVIS_ANCHOR_BELOW), 0.0, 1.0)
        to_shoulder = (x * x * (3 - 2 * x))[:, None]

        from_pelvis = gta_pelvis + (wrist_src - pelvis_src)
        from_shoulder = world_p[:, upper] + (wrist_src - shoulder_src)
        goal = from_pelvis * (1 - to_shoulder) + from_shoulder * to_shoulder
        goal = _limit_reach(world_p[:, upper], world_p[:, fore], world_p[:, hand], goal)

        active = np.ones(len(out), dtype=bool)
        cleanup.two_bone_ik(skel, out, world_r, world_p, upper, fore, hand, goal, active)
        world_r, world_p = skel.fk(out)
    return out
