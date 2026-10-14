"""Ground contact on the GTA ped: sole points, planted root height, foot contact detection."""
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import argrelmin

from . import rot

# Ped entity origin sits 1 m above the ground (GTA convention, matches the freemode feet mesh).
GROUND_Z = -1.0
SOLE_BONES = {
    "L": ("SKEL_L_Foot", "SKEL_L_Toe0"),
    "R": ("SKEL_R_Foot", "SKEL_R_Toe0"),
}


def sole_offsets(skel):
    """Heel and toe contact points expressed in their bone's local frame, measured on the bind pose."""
    bind_world_r, bind_world_p = skel.fk(skel.bind_r)
    ground = _bind_ground(skel, bind_world_p)
    offsets = {}
    for side, bones in SOLE_BONES.items():
        offsets[side] = []
        for name in bones:
            i = skel.index(name)
            point = bind_world_p[i].copy()
            point[2] = ground
            local = rot.apply(rot.inv(bind_world_r[i]), point - bind_world_p[i])
            offsets[side].append((i, local))
    return offsets


def _bind_ground(skel, bind_world_p):
    # Bind pose stands with flat feet: the toe bone sits ~4.5 cm above the sole.
    toe = min(bind_world_p[skel.index("SKEL_L_Toe0")][2], bind_world_p[skel.index("SKEL_R_Toe0")][2])
    return toe - 0.045


def sole_points(skel, local_r, root_t):
    """World positions (T, 2 sides, 2 points, 3) of heel/toe contacts."""
    local_t = np.broadcast_to(skel.bind_t, local_r.shape[:-1] + (3,)).copy()
    local_t[:, skel.index("SKEL_ROOT")] = root_t
    world_r, world_p = skel.fk(local_r, local_t)
    offsets = sole_offsets(skel)
    out = np.empty((local_r.shape[0], 2, 2, 3))
    for s, side in enumerate(("L", "R")):
        for k, (i, local) in enumerate(offsets[side]):
            out[:, s, k] = world_p[:, i] + rot.apply(world_r[:, i], local)
    return out


def planted_root_height(skel, local_r, root_xy=None):
    """Root Z per frame so that the lowest sole point rests on the ground."""
    frames = local_r.shape[0]
    root_t = np.zeros((frames, 3))
    if root_xy is not None:
        root_t[:, :2] = root_xy
    soles = sole_points(skel, local_r, root_t)
    lowest = soles[..., 2].reshape(frames, -1).min(axis=1)
    return GROUND_Z - lowest


JUMP_MIN_HEIGHT = 0.05
JUMP_MIN_SECONDS = 0.12


def jump_heights(skel, local_r, root_world, fps):
    """Height to add on top of the planted root during real flight phases (GVHMR only).

    The engine's pelvis height drifts by 10-45 cm (it read as floating). Only a bump above the line
    through the stance points, at least JUMP_MIN_HEIGHT high for JUMP_MIN_SECONDS, is kept."""
    planted = planted_root_height(skel, local_r, root_world[:, :2])
    lift = gaussian_filter1d(root_world[:, 2] - planted, 1.0, mode="nearest")
    floor = _support_line(lift, fps)
    excess = lift - floor
    flight = excess > JUMP_MIN_HEIGHT
    flight = _drop_short_runs(flight, int(round(fps * JUMP_MIN_SECONDS)))
    weight = gaussian_filter1d(flight.astype(np.float64), 1.5, mode="nearest")
    return np.clip(excess, 0.0, None) * weight


def _support_line(lift, fps):
    """Line through the successive stance points (local minima of the lift).
    It follows slow drift — even a steady ramp, which GVHMR produces when it believes the performer
    runs uphill — so only a bump between two supports reads as flight."""
    order = max(2, int(round(fps * 0.15)))
    minima = argrelmin(lift, order=order, mode="clip")[0]
    anchors = np.unique(np.concatenate(([0], minima, [len(lift) - 1])))
    anchors = anchors[np.isin(anchors, minima) | (lift[anchors] <= np.percentile(lift, 50))] if len(minima) else anchors
    if len(anchors) < 2:
        return np.full_like(lift, lift.min())
    return np.minimum(np.interp(np.arange(len(lift)), anchors, lift[anchors]), lift)


def _drop_short_runs(mask, min_length):
    out = mask.copy()
    start = None
    for t, value in enumerate(np.append(mask, False)):
        if value and start is None:
            start = t
        elif not value and start is not None:
            if t - start < min_length:
                out[start:t] = False
            start = None
    return out


def root_heights(skel, local_r, root_xy, mode, tracked_z, jump_z):
    """Root Z per frame.

    planted — the lowest sole always rests on the ground (no float, no sink, no jumps).
    tracked — the engine's own pelvis height (GVHMR), shifted so the feet touch down at least once;
              its slow vertical drift makes the ped float.
    auto    — planted, plus the flight height of real jumps (see jump_heights).
    """
    planted = planted_root_height(skel, local_r, root_xy)
    if tracked_z is None or mode == "planted":
        return planted
    if mode == "tracked":
        return tracked_z - np.percentile(tracked_z - planted, 2)
    return planted + jump_z


def detect_contacts(soles, fps, height_tolerance=0.04, speed_limit=0.35):
    """Per side contact mask (T, 2): a foot is planted when it is low and nearly still."""
    lowest = soles[..., 2].min(axis=2)
    centre = soles.mean(axis=2)
    velocity = np.zeros_like(centre)
    velocity[1:] = (centre[1:] - centre[:-1]) * fps
    velocity[0] = velocity[1] if len(velocity) > 1 else 0.0
    speed = np.linalg.norm(velocity[..., :2], axis=-1)
    contacts = (lowest - GROUND_Z < height_tolerance) & (speed < speed_limit)
    return _debounce(contacts, 3)


def _debounce(mask, min_run):
    out = mask.copy()
    for s in range(mask.shape[1]):
        column = out[:, s]
        start = 0
        for t in range(1, len(column) + 1):
            if t == len(column) or column[t] != column[start]:
                if t - start < min_run:
                    column[start:t] = not column[start] if start > 0 else column[start]
                start = t
    return out
