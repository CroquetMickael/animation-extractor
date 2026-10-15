"""Manual corrections drawn in the editor.

Calibration: one local offset per bone, applied to every frame of every clip (fixes systematic retarget error).
Keys: {bone, frame, q, radius} local offsets that fade out over `radius` frames around `frame`
(radius < 0 = whole clip). Applied as L' = L * offset, so the editor can store Lbase^-1 * Ledited.
Move keys: {bone, frame, t, radius} shift a joint by t metres in the ped's space, solved by IK (see
apply_move_keys); bone ROOT_OFFSET shifts the whole body.
"""
import numpy as np

from . import cleanup, rot

ROOT_OFFSET = "__root_offset__"
# Joints that end a two-bone chain (upper, middle): moving one bends the knee or elbow to reach.
LIMB_ENDS = {f"SKEL_{s}_{end}": (f"SKEL_{s}_{upper}", f"SKEL_{s}_{middle}")
             for s in "LR" for upper, middle, end in (("Thigh", "Calf", "Foot"), ("UpperArm", "Forearm", "Hand"))}
# Knee and elbow: moving one swings the upper bone onto the goal, then the lower bone points back at
# where the foot or hand was (it follows as closely as the bone allows, keeping its orientation). With the
# hip and the ankle both pinned a knee could only roll around their axis: dragged 5 cm down it moved 1 cm.
LIMB_MIDDLES = {f"SKEL_{s}_{middle}": (f"SKEL_{s}_{upper}", f"SKEL_{s}_{end}")
                for s in "LR" for upper, middle, end in (("Thigh", "Calf", "Foot"), ("UpperArm", "Forearm", "Hand"))}


def apply_calibration(skel, local_r, calibration):
    out = local_r.copy()
    for name, q in (calibration or {}).items():
        if not skel.has(name):
            continue
        i = skel.index(name)
        out[:, i] = rot.normalize(rot.mul(out[:, i], np.asarray(q, dtype=np.float64)))
    return out


def key_weights(frames, frame, radius):
    if radius is None or radius < 0:
        return np.ones(frames)
    t = np.arange(frames)
    if radius == 0:
        return (t == frame).astype(np.float64)
    x = np.clip(1.0 - np.abs(t - frame) / float(radius + 1), 0.0, 1.0)
    return x * x * (3 - 2 * x)


def apply_keys(skel, local_r, keys):
    out = local_r.copy()
    frames = local_r.shape[0]
    for key in keys or []:
        name = key.get("bone")
        if "q" not in key or not skel.has(name):
            continue
        i = skel.index(name)
        offset = rot.normalize(np.asarray(key["q"], dtype=np.float64))
        w = key_weights(frames, int(key.get("frame", 0)), key.get("radius", 10))
        partial = rot.slerp(np.broadcast_to(rot.IDENTITY, (frames, 4)), np.broadcast_to(offset, (frames, 4)), w)
        out[:, i] = rot.normalize(rot.mul(out[:, i], partial))
    return out


def apply_root_keys(root_t, keys):
    out = root_t.copy()
    frames = root_t.shape[0]
    for key in keys or []:
        if key.get("bone") != ROOT_OFFSET:
            continue
        w = key_weights(frames, int(key.get("frame", 0)), key.get("radius", 10))
        out += np.asarray(key["t"], dtype=np.float64)[None, :] * w[:, None]
    return out


def apply_move_keys(skel, local_r, root_t, keys):
    """Move keys: each one drags a joint by `t` (ped space, metres, faded like the rotation keys).
    A foot or hand pulls its leg or arm (two-bone IK, its own orientation kept); a knee or elbow swings
    the upper bone and the foot or hand is put back; any other joint turns its parent towards the goal."""
    out = local_r.copy()
    frames = local_r.shape[0]
    local_t = np.broadcast_to(skel.bind_t, local_r.shape[:-1] + (3,)).copy()
    local_t[:, skel.index("SKEL_ROOT")] = root_t
    for key in keys or []:
        name = key.get("bone")
        if "t" not in key or name == ROOT_OFFSET or not skel.has(name):
            continue
        weight = key_weights(frames, int(key.get("frame", 0)), key.get("radius", 10))
        active = weight > 1e-4
        if not active.any():
            continue
        i = skel.index(name)
        world_r, world_p = skel.fk(out, local_t)
        goal = world_p[:, i] + np.asarray(key["t"], dtype=np.float64)[None, :] * weight[:, None]
        if name in LIMB_ENDS:
            upper, middle = (skel.index(b) for b in LIMB_ENDS[name])
            cleanup.two_bone_ik(skel, out, world_r, world_p, upper, middle, i, goal, active)
        elif name in LIMB_MIDDLES:
            end = skel.index(LIMB_MIDDLES[name][1])
            end_goal, end_world = world_p[:, end].copy(), world_r[:, end].copy()
            _aim_parent(skel, out, world_r, world_p, i, goal, active)
            world_r, world_p = skel.fk(out, local_t)
            _turn_towards(skel, out, world_r, world_p, i, end, end_goal, active)
            world_r, _ = skel.fk(out, local_t)
            out[active, end] = rot.normalize(rot.mul(rot.inv(world_r[active, i]), end_world[active]))
        else:
            _reach(skel, out, local_t, i, goal, active)
    return out


REACH_DEPTH = 3
REACH_PASSES = 6


def _reach(skel, local_r, local_t, joint, goal, active):
    """Cyclic coordinate descent over the joint's first REACH_DEPTH ancestors (SKEL_ROOT excluded, it
    carries the whole body): a short bone such as the neck cannot bring the head far on its own."""
    chain = []
    bone = joint
    while len(chain) < REACH_DEPTH and skel.parents[bone] >= 0 and skel.names[skel.parents[bone]] != "SKEL_ROOT":
        bone = skel.parents[bone]
        chain.append(bone)
    for _ in range(REACH_PASSES):
        for ancestor in chain:
            world_r, world_p = skel.fk(local_r, local_t)
            _turn_towards(skel, local_r, world_r, world_p, ancestor, joint, goal, active)


def _aim_parent(skel, local_r, world_r, world_p, joint, goal, active):
    """Turn the joint's parent bone so the joint points at the goal (the bone keeps its length)."""
    _turn_towards(skel, local_r, world_r, world_p, skel.parents[joint], joint, goal, active)


def _turn_towards(skel, local_r, world_r, world_p, pivot_bone, joint, goal, active):
    """Rotate pivot_bone about its own origin so that `joint` (one of its descendants) swings towards goal."""
    pivot = world_p[active, pivot_bone]
    turn = rot.between(world_p[active, joint] - pivot, goal[active] - pivot)
    pivot_world = rot.mul(turn, world_r[active, pivot_bone])
    parent = skel.parents[pivot_bone]
    above = world_r[active, parent] if parent >= 0 else np.broadcast_to(rot.IDENTITY, pivot_world.shape)
    local_r[active, pivot_bone] = rot.normalize(rot.mul(rot.inv(above), pivot_world))
