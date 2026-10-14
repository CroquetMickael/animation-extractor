"""Mover track (root motion), Rockstar style.

Verified on move_m@generic: the skeleton is expressed relative to the ped entity, and the mover track
(bone 0, track 5 translation / track 6 rotation) is the entity's own path in clip space. Each frame the
game applies the mover delta, in the entity's local frame, to the ped: wstart_l_0 walks forward with the
mover going 0 -> +2.95 m on +Y at identity rotation; idle_turn_r_90 turns the mover while SKEL_ROOT's
yaw stays ~0. Rockstar keeps the mover's Z at a constant 1.0, which we copy.
"""
import numpy as np
from scipy.ndimage import gaussian_filter1d

from . import rot

MODES = ("inplace", "root", "mover", "mover_turn")
MOVER_Z = 1.0
# The entity follows a smoothed path; the pelvis sway around it stays in SKEL_ROOT.
PATH_SMOOTHING_SECONDS = 0.2
HEADING_SMOOTHING_SECONDS = 0.3


STANCE_SWITCH_MARGIN = 0.015
STANCE_MAX_HEIGHT = 0.06


def pin_to_feet(skel, local_r, root_t, fps):
    """Travel recovered from the feet: whatever the stance foot slides, the body moves the opposite way.

    Game-engine footage often plays locomotion in place, so the stance foot slides back like on a
    treadmill (2.4 m over a 1.4 s dodge while the pelvis barely moved). Pinning the stance foot turns
    that slide into forward travel; in footage that already travels the stance foot is still and the
    correction is ~0. During flight the last velocity is carried."""
    from . import ground

    soles = ground.sole_points(skel, local_r, root_t)
    lowest = soles[..., 2].min(axis=2)
    centre = soles.mean(axis=2)[..., :2]
    frames = len(root_t)

    stance = np.zeros(frames, dtype=int)
    stance[0] = int(np.argmin(lowest[0]))
    for t in range(1, frames):
        current = stance[t - 1]
        other = 1 - current
        stance[t] = other if lowest[t, other] < lowest[t, current] - STANCE_SWITCH_MARGIN else current

    correction = np.zeros((frames, 2))
    velocity = np.zeros(2)
    for t in range(1, frames):
        side = stance[t]
        planted = stance[t - 1] == side and lowest[t, side] - ground.GROUND_Z < STANCE_MAX_HEIGHT
        if planted:
            velocity = -(centre[t, side] - centre[t - 1, side])
        correction[t] = correction[t - 1] + velocity

    out = root_t.copy()
    out[:, :2] += gaussian_filter1d(correction, max(1.0, fps * 0.05), axis=0, mode="nearest")
    return out


def extract(local_r, root_t, root_index, fps, with_turn, target_speed=None, lateral_scale=1.0, lateral_distance=None):
    """Split world-space root motion into an entity path (mover) and a body relative to it.
    Returns (local_r, root_t, mover_t (T, 3), mover_r (T, 4))."""
    frames = len(root_t)
    path = gaussian_filter1d(root_t[:, :2], fps * PATH_SMOOTHING_SECONDS, axis=0, mode="nearest")
    path -= path[0]

    heading = np.zeros(frames)
    if with_turn:
        forward = rot.apply(local_r[:, root_index], np.array([0.0, 1.0, 0.0]))
        heading = np.unwrap(np.arctan2(-forward[:, 0], forward[:, 1]))
        heading = gaussian_filter1d(heading, fps * HEADING_SMOOTHING_SECONDS, mode="nearest")
        heading -= heading[0]
    mover_r = rot.from_axis_angle(np.stack((np.zeros(frames), np.zeros(frames), heading), axis=-1))
    to_entity = rot.inv(mover_r)

    out_r = local_r.copy()
    out_r[:, root_index] = rot.normalize(rot.mul(to_entity, local_r[:, root_index]))
    out_t = root_t.copy()
    offset = np.concatenate((root_t[:, :2] - path, np.zeros((frames, 1))), axis=1)
    out_t[:, :2] = rot.apply(to_entity, offset)[:, :2]

    if target_speed or lateral_scale != 1.0 or lateral_distance is not None:
        path = _shape_path(path, local_r[:, root_index], fps, target_speed, lateral_scale, lateral_distance)
    mover_t = np.concatenate((path, np.full((frames, 1), MOVER_Z)), axis=1)
    return out_r, out_t, mover_t, mover_r


def measured_speed(root_t, fps):
    duration = max((len(root_t) - 1) / fps, 1e-6)
    return float(np.linalg.norm(root_t[-1, :2] - root_t[0, :2]) / duration)


def _forward_axis(root_rotation, fps):
    forward = rot.apply(root_rotation, np.array([0.0, 1.0, 0.0]))[:, :2]
    forward = gaussian_filter1d(forward, fps * HEADING_SMOOTHING_SECONDS, axis=0, mode="nearest")
    return forward / np.linalg.norm(forward, axis=-1, keepdims=True).clip(1e-6)


def _split_steps(path, forward):
    steps = np.zeros_like(path)
    steps[1:] = np.diff(path, axis=0)
    along = np.sum(steps * forward, axis=-1, keepdims=True)
    return along * forward, steps - along * forward


def lateral_offset(root_t, root_rotation, fps):
    """Signed sideways travel over the clip in metres (+ = the body's right)."""
    path = gaussian_filter1d(root_t[:, :2], fps * PATH_SMOOTHING_SECONDS, axis=0, mode="nearest")
    forward = _forward_axis(root_rotation, fps)
    right = np.stack((forward[:, 1], -forward[:, 0]), axis=-1)
    _, sideways = _split_steps(path, forward)
    return float(np.sum(sideways * right))


def _shape_path(path, root_rotation, fps, speed, lateral_scale, lateral_distance):
    """Rebuild the entity path from two components measured differently.

    Forward (the body's facing): the requested speed, or what was measured. Monocular capture loses
    travel along the camera axis, which is the forward axis when the performer faces the camera.
    Sideways: lies in the image plane and is well measured, so it is kept, scaled, or reshaped to reach
    an exact distance (following the measured profile when there is one, else a smooth ease)."""
    forward = _forward_axis(root_rotation, fps)
    right = np.stack((forward[:, 1], -forward[:, 0]), axis=-1)
    along, sideways = _split_steps(path, forward)
    frames = len(path)

    forward_steps = forward * (speed / fps) if speed else along
    if lateral_distance is None:
        sideways = sideways * lateral_scale
    else:
        measured = float(np.sum(sideways * right))
        if abs(measured) > 0.1:
            sideways = sideways * (lateral_distance / measured)
        else:
            x = np.linspace(0.0, 1.0, frames)
            ease = x * x * (3 - 2 * x)
            sideways = right * (np.gradient(ease) * lateral_distance)[:, None]

    step = forward_steps + sideways
    step[0] = 0.0
    return np.cumsum(step, axis=0)
