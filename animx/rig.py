"""Retargeting onto the GTA freemode skeleton.

Animation space (what Rockstar clips use): SKEL_ROOT identity => ped faces +Y, right +X, up +Z.
Both solvers produce per-frame world rotations for the "driven" bones; every other bone keeps its
reference-pose local rotation, so roll/IK/PH/facial bones ride along with their parents.
"""
import numpy as np

from . import rot

FORWARD = np.array([0.0, 1.0, 0.0])
UP = np.array([0.0, 0.0, 1.0])
RIGHT = np.array([1.0, 0.0, 0.0])

SPINE = ["SKEL_Spine0", "SKEL_Spine1", "SKEL_Spine2", "SKEL_Spine3"]

# Bone -> child used to measure its segment direction in the reference pose.
SEGMENT_CHILD = {
    "SKEL_Spine0": "SKEL_Spine1",
    "SKEL_Spine1": "SKEL_Spine2",
    "SKEL_Spine2": "SKEL_Spine3",
    "SKEL_Spine3": "SKEL_Neck_1",
    "SKEL_Neck_1": "SKEL_Head",
    "SKEL_L_Thigh": "SKEL_L_Calf",
    "SKEL_L_Calf": "SKEL_L_Foot",
    "SKEL_L_Foot": "SKEL_L_Toe0",
    "SKEL_R_Thigh": "SKEL_R_Calf",
    "SKEL_R_Calf": "SKEL_R_Foot",
    "SKEL_R_Foot": "SKEL_R_Toe0",
    "SKEL_L_Clavicle": "SKEL_L_UpperArm",
    "SKEL_L_UpperArm": "SKEL_L_Forearm",
    "SKEL_L_Forearm": "SKEL_L_Hand",
    "SKEL_L_Hand": "SKEL_L_Finger20",
    "SKEL_R_Clavicle": "SKEL_R_UpperArm",
    "SKEL_R_UpperArm": "SKEL_R_Forearm",
    "SKEL_R_Forearm": "SKEL_R_Hand",
    "SKEL_R_Hand": "SKEL_R_Finger20",
}

# Canonical T-pose: legs and spine vertical, arms horizontal, palms down (thumbs forward).
CANONICAL_DIRECTIONS = {
    **{bone: UP for bone in SPINE + ["SKEL_Neck_1"]},
    "SKEL_L_Thigh": -UP,
    "SKEL_L_Calf": -UP,
    "SKEL_R_Thigh": -UP,
    "SKEL_R_Calf": -UP,
    "SKEL_L_Clavicle": -RIGHT,
    "SKEL_L_UpperArm": -RIGHT,
    "SKEL_L_Forearm": -RIGHT,
    "SKEL_L_Hand": -RIGHT,
    "SKEL_R_Clavicle": RIGHT,
    "SKEL_R_UpperArm": RIGHT,
    "SKEL_R_Forearm": RIGHT,
    "SKEL_R_Hand": RIGHT,
}


# Limb chains whose roll is fixed after the swing: (bone rolled, axis from, axis to, marker a, marker b, wanted a->b direction).
# Arms: index knuckle ahead of pinky knuckle = palms down, thumbs forward. Legs: toes forward.
TWIST_TARGETS = [
    ("SKEL_L_UpperArm", "SKEL_L_UpperArm", "SKEL_L_Hand", "SKEL_L_Finger40", "SKEL_L_Finger10", FORWARD),
    ("SKEL_R_UpperArm", "SKEL_R_UpperArm", "SKEL_R_Hand", "SKEL_R_Finger40", "SKEL_R_Finger10", FORWARD),
    ("SKEL_L_Thigh", "SKEL_L_Thigh", "SKEL_L_Foot", "SKEL_L_Foot", "SKEL_L_Toe0", FORWARD),
    ("SKEL_R_Thigh", "SKEL_R_Thigh", "SKEL_R_Foot", "SKEL_R_Foot", "SKEL_R_Toe0", FORWARD),
]


def build_reference_pose(skel, directions, fix_twist=True):
    """Rotate the bind pose (root at identity) so each listed bone's segment points along `directions`.
    Returns local rotations (B, 4)."""
    local = skel.anim_rest_rotations()
    _swing_all(skel, local, directions)
    if not fix_twist:
        return local

    for bone, axis_from, axis_to, marker_a, marker_b, wanted in TWIST_TARGETS:
        # A leg's roll follows the source's own rest foot direction (SMPL toes point slightly out);
        # forcing them straight forward would twist the whole leg, knee included.
        wanted = directions.get(marker_a, wanted) if marker_a.endswith("_Foot") else wanted
        world_r, world_p = skel.fk(local)
        axis = world_p[skel.index(axis_to)] - world_p[skel.index(axis_from)]
        axis /= np.linalg.norm(axis)
        have = world_p[skel.index(marker_b)] - world_p[skel.index(marker_a)]
        have = have - np.dot(have, axis) * axis
        want = wanted - np.dot(wanted, axis) * axis
        if np.linalg.norm(have) < 1e-6 or np.linalg.norm(want) < 1e-6:
            continue
        _rotate_world(skel, local, world_r, skel.index(bone), rot.between(have, want))

    # The roll moved the end segments (feet, hands); point them again.
    _swing_all(skel, local, directions)
    return local


def _swing_all(skel, local, directions):
    for i in skel.order:
        name = skel.names[i]
        target = directions.get(name)
        child = SEGMENT_CHILD.get(name)
        if target is None or child is None or not skel.has(child):
            continue
        world_r, world_p = skel.fk(local)
        current = world_p[skel.index(child)] - world_p[i]
        _rotate_world(skel, local, world_r, i, rot.between(current, target))


def _rotate_world(skel, local, world_r, i, delta):
    new_world = rot.mul(delta, world_r[i])
    parent = skel.parents[i]
    local[i] = rot.normalize(rot.mul(rot.inv(world_r[parent]), new_world)) if parent >= 0 else new_world


def drive(skel, reference_local, driven_world):
    """driven_world: {bone name: (T, 4) world rotation}. Returns local rotations (T, B, 4)."""
    frames = next(iter(driven_world.values())).shape[0]
    world = np.empty((frames, skel.count, 4))
    local = np.empty((frames, skel.count, 4))
    driven_index = {skel.index(name): q for name, q in driven_world.items() if skel.has(name)}

    for i in skel.order:
        parent = skel.parents[i]
        if i in driven_index:
            world[:, i] = rot.normalize(driven_index[i])
            local[:, i] = world[:, i] if parent < 0 else rot.mul(rot.inv(world[:, parent]), world[:, i])
            continue
        local[:, i] = reference_local[i]
        world[:, i] = local[:, i] if parent < 0 else rot.mul(world[:, parent], local[:, i])
    return rot.normalize(local)


def reference_world(skel, reference_local):
    world_r, _ = skel.fk(reference_local)
    return world_r
