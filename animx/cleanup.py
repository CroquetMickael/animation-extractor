"""Post-processing on GTA-space motion: smoothing, foot locking, looping, heading, speed."""
import numpy as np
from scipy.ndimage import gaussian_filter1d

from . import ground, rot


def smooth_rotations(local_r, sigma, bone_indices):
    if sigma <= 0 or local_r.shape[0] < 3:
        return local_r
    out = local_r.copy()
    for i in bone_indices:
        q = rot.make_continuous(local_r[:, i])
        out[:, i] = rot.normalize(gaussian_filter1d(q, sigma, axis=0, mode="nearest"))
    return out


def smooth_vectors(v, sigma):
    if sigma <= 0 or v.shape[0] < 3:
        return v
    return gaussian_filter1d(v, sigma, axis=0, mode="nearest")


def lock_heading(local_r, root_index):
    """Remove the performer's yaw drift: keep the root's tilt, cancel its turn around Z."""
    root = local_r[:, root_index]
    yaw = rot.yaw_only(root)
    out = local_r.copy()
    out[:, root_index] = rot.mul(rot.inv(yaw), root)
    return out


def resample(local_r, root_t, speed):
    if abs(speed - 1.0) < 1e-6:
        return local_r, root_t
    frames = local_r.shape[0]
    count = max(2, int(round((frames - 1) / speed)) + 1)
    src = np.linspace(0, frames - 1, count)
    i0 = np.floor(src).astype(int).clip(0, frames - 1)
    i1 = (i0 + 1).clip(0, frames - 1)
    alpha = (src - i0)[:, None]
    q = rot.make_continuous(local_r)
    out_r = rot.slerp(q[i0], q[i1], np.broadcast_to(alpha[:, None], q[i0].shape[:-1]))
    out_t = root_t[i0] * (1 - alpha) + root_t[i1] * alpha
    return out_r, out_t


def resample_scalar(values, speed):
    if abs(speed - 1.0) < 1e-6:
        return values
    frames = len(values)
    count = max(2, int(round((frames - 1) / speed)) + 1)
    return np.interp(np.linspace(0, frames - 1, count), np.arange(frames), values)


def make_loop(local_r, root_t, blend_frames):
    """Cross-fade the tail into the head so frame N-1 flows back into frame 0."""
    frames = local_r.shape[0]
    n = int(min(blend_frames, frames // 2))
    if n < 2:
        return local_r, root_t
    out_r = rot.make_continuous(local_r).copy()
    out_t = root_t.copy()
    for k in range(n):
        t = frames - n + k
        w = 0.5 - 0.5 * np.cos(np.pi * (k + 1) / n)
        out_r[t] = rot.slerp(local_r[t], local_r[k], np.full(local_r.shape[1], w))
        out_t[t] = root_t[t] * (1 - w) + root_t[k] * w
    return out_r, out_t


def lock_feet(skel, local_r, root_t, fps, blend=3):
    """Pin each foot while it is in contact (two-bone IK on thigh/calf, foot world rotation preserved)."""
    soles = ground.sole_points(skel, local_r, root_t)
    contacts = ground.detect_contacts(soles, fps)
    local_t = np.broadcast_to(skel.bind_t, local_r.shape[:-1] + (3,)).copy()
    local_t[:, skel.index("SKEL_ROOT")] = root_t
    world_r, world_p = skel.fk(local_r, local_t)
    out = local_r.copy()

    for s, side in enumerate(("L", "R")):
        thigh, calf, foot = (skel.index(f"SKEL_{side}_{b}") for b in ("Thigh", "Calf", "Foot"))
        ankle = world_p[:, foot]
        target = ankle.copy()
        weight = np.zeros(len(ankle))
        for start, end in _runs(contacts[:, s]):
            anchor = ankle[start:end].mean(axis=0)
            anchor[2] = ankle[start:end, 2].min()
            target[start:end] = anchor
            weight[start:end] = 1.0
            for k in range(1, blend + 1):
                if start - k >= 0 and weight[start - k] < 1.0:
                    target[start - k] = anchor
                    weight[start - k] = max(weight[start - k], 1.0 - k / (blend + 1))
                if end - 1 + k < len(ankle) and weight[end - 1 + k] < 1.0:
                    target[end - 1 + k] = anchor
                    weight[end - 1 + k] = max(weight[end - 1 + k], 1.0 - k / (blend + 1))

        active = weight > 0
        if not active.any():
            continue
        goal = ankle + (target - ankle) * weight[:, None]
        two_bone_ik(skel, out, world_r, world_p, thigh, calf, foot, goal, active)
    return out


def two_bone_ik(skel, local_r, world_r, world_p, thigh, calf, foot, goal, active):
    hip = world_p[active, thigh]
    knee = world_p[active, calf]
    ankle = world_p[active, foot]
    goal = goal[active]
    l1 = np.linalg.norm(knee - hip, axis=-1)
    l2 = np.linalg.norm(ankle - knee, axis=-1)

    to_goal = goal - hip
    d = np.linalg.norm(to_goal, axis=-1).clip(1e-6, (l1 + l2) * 0.999)
    direction = to_goal / np.linalg.norm(to_goal, axis=-1, keepdims=True).clip(1e-9)
    pole = (knee - hip) - np.sum((knee - hip) * direction, axis=-1, keepdims=True) * direction
    pole /= np.linalg.norm(pole, axis=-1, keepdims=True).clip(1e-9)
    cos_a = ((l1 ** 2 + d ** 2 - l2 ** 2) / (2 * l1 * d)).clip(-1, 1)
    new_knee = hip + direction * (l1 * cos_a)[:, None] + pole * (l1 * np.sqrt(1 - cos_a ** 2))[:, None]
    new_ankle = hip + direction * d[:, None]

    thigh_world = rot.mul(rot.between(knee - hip, new_knee - hip), world_r[active, thigh])
    moved_ankle = new_knee + rot.apply(rot.mul(thigh_world, rot.inv(world_r[active, thigh])), ankle - knee)
    calf_world_pre = rot.mul(thigh_world, rot.mul(rot.inv(world_r[active, thigh]), world_r[active, calf]))
    calf_world = rot.mul(rot.between(moved_ankle - new_knee, new_ankle - new_knee), calf_world_pre)

    thigh_parent = world_r[active, skel.parents[thigh]]
    local_r[active, thigh] = rot.normalize(rot.mul(rot.inv(thigh_parent), thigh_world))
    local_r[active, calf] = rot.normalize(rot.mul(rot.inv(thigh_world), calf_world))
    local_r[active, foot] = rot.normalize(rot.mul(rot.inv(calf_world), world_r[active, foot]))


def _runs(mask):
    runs = []
    start = None
    for t, value in enumerate(mask):
        if value and start is None:
            start = t
        elif not value and start is not None:
            runs.append((start, t))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


PLANT_MAX_HEIGHT = 0.08
PLANT_SPEED_LIMIT = 0.35


def plant_feet(skel, local_r, root_t, fps):
    """Put a nearly still foot that hovers a few centimetres up down onto the ground (two-bone IK, the
    foot keeps its orientation). The planted root only seats the lowest sole: in a stance the other foot
    could float 3-4 cm for the whole clip, which hand corrections at one frame could not fix."""
    soles = ground.sole_points(skel, local_r, root_t)
    lowest = soles[..., 2].min(axis=2) - ground.GROUND_Z
    centre = soles.mean(axis=2)
    velocity = np.zeros_like(centre)
    velocity[1:] = (centre[1:] - centre[:-1]) * fps
    velocity[0] = velocity[1] if len(velocity) > 1 else 0.0
    speed = np.linalg.norm(velocity[..., :2], axis=-1)
    contact = ground._debounce((lowest < PLANT_MAX_HEIGHT) & (speed < PLANT_SPEED_LIMIT), 3)

    local_t = np.broadcast_to(skel.bind_t, local_r.shape[:-1] + (3,)).copy()
    local_t[:, skel.index("SKEL_ROOT")] = root_t
    out = local_r.copy()
    for s, side in enumerate(("L", "R")):
        weight = gaussian_filter1d(contact[:, s].astype(np.float64), 1.5, mode="nearest") if len(contact) > 2 else contact[:, s] * 1.0
        active = (weight > 1e-3) & (lowest[:, s] > 1e-4)
        if not active.any():
            continue
        thigh, calf, foot = (skel.index(f"SKEL_{side}_{b}") for b in ("Thigh", "Calf", "Foot"))
        world_r, world_p = skel.fk(out, local_t)
        goal = world_p[:, foot].copy()
        goal[:, 2] -= np.clip(lowest[:, s], 0.0, None) * weight
        two_bone_ik(skel, out, world_r, world_p, thigh, calf, foot, goal, active)
    return out
