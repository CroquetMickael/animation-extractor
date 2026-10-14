"""Landmark positions (MediaPipe) -> GTA bone world rotations.

Every driven bone gets a frame (segment direction + a twist hint). The rotation that carries the
canonical T-pose frame onto the observed frame is applied on top of the bone's T-pose world rotation.
"""
import numpy as np
from scipy.signal import savgol_filter

from .. import rig, rot

NOSE, L_EAR, R_EAR = 0, 7, 8
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = 11, 12, 13, 14, 15, 16
L_PINKY, R_PINKY, L_INDEX, R_INDEX = 17, 18, 19, 20
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANKLE, R_ANKLE = 23, 24, 25, 26, 27, 28
L_HEEL, R_HEEL, L_FOOT, R_FOOT = 29, 30, 31, 32

# MediaPipe world (x right, y down, z away from camera) -> GTA (facing +Y, up +Z), turned to face away.
MP_TO_GTA = np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, -1.0, 0.0]])

SPINE_BLEND = {"SKEL_Spine0": 0.2, "SKEL_Spine1": 0.45, "SKEL_Spine2": 0.75}


def load_positions(capture, smooth_window=9, upright=True):
    raw = np.asarray(capture["pose_world"], dtype=np.float64)
    points = raw[..., :3]
    points = _fill_gaps(points)
    if smooth_window and points.shape[0] > smooth_window:
        points = savgol_filter(points, smooth_window, 2, axis=0)
    points = points @ MP_TO_GTA.T
    if not upright:
        return points
    return points @ rot.to_matrix(gravity_alignment(points)).T


MEDIAPIPE_CAMERA_DISTANCE = 3.0
MEDIAPIPE_CAMERA_FOV = 40.0


def camera_track(capture, upright=True):
    """MediaPipe world landmarks are hip-centred in camera axes, so the camera sits straight ahead of
    the hips along -z; its distance and lens are unknown, hence fixed defaults."""
    frames = np.asarray(capture["pose_world"]).shape[0]
    offset = np.tile(np.array([0.0, 0.0, -MEDIAPIPE_CAMERA_DISTANCE]) @ MP_TO_GTA.T, (frames, 1))
    forward = np.tile(np.array([0.0, 0.0, 1.0]) @ MP_TO_GTA.T, (frames, 1))
    up = np.tile(np.array([0.0, -1.0, 0.0]) @ MP_TO_GTA.T, (frames, 1))
    if upright:
        points = _fill_gaps(np.asarray(capture["pose_world"], dtype=np.float64)[..., :3]) @ MP_TO_GTA.T
        align = gravity_alignment(points)
        offset, forward, up = (rot.apply(align, v) for v in (offset, forward, up))
    return {"offset": offset, "forward": forward, "up": up, "fov": MEDIAPIPE_CAMERA_FOV}


def gravity_alignment(points):
    """MediaPipe world axes follow the camera, so a tilted camera tilts the whole body.
    Assume the performer is upright on average and rotate that average up-axis onto +Z."""
    shoulders = (points[:, L_SHOULDER] + points[:, R_SHOULDER]) * 0.5
    ankles = (points[:, L_ANKLE] + points[:, R_ANKLE]) * 0.5
    up = _norm(shoulders - ankles)
    median_up = _norm(np.median(up, axis=0))
    return rot.between(median_up, rig.UP)


def _fill_gaps(points):
    frames = points.shape[0]
    valid = ~np.isnan(points[:, 0, 0])
    if not valid.any():
        raise ValueError("no person detected in the video")
    t = np.arange(frames)
    filled = np.empty_like(points)
    for j in range(points.shape[1]):
        for c in range(3):
            filled[:, j, c] = np.interp(t, t[valid], points[valid, j, c])
    return filled


def _norm(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True).clip(1e-9)


def _perp(v, axis):
    axis = _norm(axis)
    return v - np.sum(v * axis, axis=-1, keepdims=True) * axis


def _limb(direction, hint, t_direction, t_hint):
    current = rot.from_frame(direction, _perp(hint, direction))
    reference = rot.from_frame(np.broadcast_to(t_direction, direction.shape), np.broadcast_to(t_hint, direction.shape))
    return rot.mul(current, rot.inv(reference))


def _upper_arm_hint(shoulder, elbow, wrist, thumb_side):
    upper = elbow - shoulder
    lower = wrist - elbow
    bend = _perp(lower, upper)
    bend_amount = np.linalg.norm(bend, axis=-1, keepdims=True) / np.linalg.norm(lower, axis=-1, keepdims=True).clip(1e-9)
    weight = np.clip((bend_amount - 0.15) / 0.35, 0.0, 1.0)
    return _norm(bend) * weight + _norm(_perp(thumb_side, upper)) * (1.0 - weight)


def solve(skel, reference_local, positions, head_pitch_deg=12.0):
    """positions: (T, 33, 3) in GTA space. Returns {bone: (T, 4) world rotation}."""
    p = positions
    ref_world = rig.reference_world(skel, reference_local)

    def ref(name):
        return ref_world[skel.index(name)]

    mid_hip = (p[:, L_HIP] + p[:, R_HIP]) * 0.5
    mid_shoulder = (p[:, L_SHOULDER] + p[:, R_SHOULDER]) * 0.5
    torso_up = mid_shoulder - mid_hip

    pelvis = _torso_frame(p[:, R_HIP] - p[:, L_HIP], torso_up)
    chest = _torso_frame(p[:, R_SHOULDER] - p[:, L_SHOULDER], torso_up)

    ear_mid = (p[:, L_EAR] + p[:, R_EAR]) * 0.5
    head_right = p[:, R_EAR] - p[:, L_EAR]
    head_forward = _perp(p[:, NOSE] - ear_mid, head_right)
    head = rot.from_frame(head_forward, np.cross(head_right, head_forward))
    head = rot.mul(head, rot.from_axis_angle(np.array([np.radians(head_pitch_deg), 0.0, 0.0])))

    driven = {"SKEL_ROOT": pelvis}
    for bone, blend in SPINE_BLEND.items():
        driven[bone] = rot.mul(rot.slerp(pelvis, chest, blend), ref(bone))
    driven["SKEL_Spine3"] = rot.mul(chest, ref("SKEL_Spine3"))
    driven["SKEL_Neck_1"] = rot.mul(rot.slerp(chest, head, 0.5), ref("SKEL_Neck_1"))
    driven["SKEL_Head"] = rot.mul(head, ref("SKEL_Head"))

    for side, sign, idx in (("L", -1.0, (L_SHOULDER, L_ELBOW, L_WRIST, L_INDEX, L_PINKY)),
                            ("R", 1.0, (R_SHOULDER, R_ELBOW, R_WRIST, R_INDEX, R_PINKY))):
        shoulder, elbow, wrist, index, pinky = (p[:, i] for i in idx)
        thumb_side = index - pinky
        arm_axis = rig.RIGHT * sign
        upper_hint = _upper_arm_hint(shoulder, elbow, wrist, thumb_side)
        driven[f"SKEL_{side}_UpperArm"] = rot.mul(_limb(elbow - shoulder, upper_hint, arm_axis, rig.FORWARD), ref(f"SKEL_{side}_UpperArm"))
        driven[f"SKEL_{side}_Forearm"] = rot.mul(_limb(wrist - elbow, thumb_side, arm_axis, rig.FORWARD), ref(f"SKEL_{side}_Forearm"))
        hand_dir = (index + pinky) * 0.5 - wrist
        driven[f"SKEL_{side}_Hand"] = rot.mul(_limb(hand_dir, thumb_side, arm_axis, rig.FORWARD), ref(f"SKEL_{side}_Hand"))

    foot_ref_dir = _reference_foot_direction(skel, reference_local)
    for side, idx in (("L", (L_HIP, L_KNEE, L_ANKLE, L_HEEL, L_FOOT)), ("R", (R_HIP, R_KNEE, R_ANKLE, R_HEEL, R_FOOT))):
        hip, knee, ankle, heel, toe = (p[:, i] for i in idx)
        foot_forward = toe - heel
        driven[f"SKEL_{side}_Thigh"] = rot.mul(_limb(knee - hip, foot_forward, -rig.UP, rig.FORWARD), ref(f"SKEL_{side}_Thigh"))
        driven[f"SKEL_{side}_Calf"] = rot.mul(_limb(ankle - knee, foot_forward, -rig.UP, rig.FORWARD), ref(f"SKEL_{side}_Calf"))
        driven[f"SKEL_{side}_Foot"] = rot.mul(_limb(toe - ankle, knee - ankle, foot_ref_dir[side], rig.UP), ref(f"SKEL_{side}_Foot"))

    return driven


def _torso_frame(right, up):
    forward = np.cross(up, right)
    return rot.from_frame(forward, up)


def _reference_foot_direction(skel, reference_local):
    _, world_p = skel.fk(reference_local)
    out = {}
    for side in ("L", "R"):
        d = world_p[skel.index(f"SKEL_{side}_Toe0")] - world_p[skel.index(f"SKEL_{side}_Foot")]
        out[side] = d / np.linalg.norm(d)
    return out


def heading_correction(driven, frames=15):
    """Yaw that turns the performer's initial facing onto +Y."""
    root = driven["SKEL_ROOT"][:frames]
    forward = rot.apply(root, rig.FORWARD).mean(axis=0)
    yaw = np.arctan2(forward[0], forward[1])
    return rot.from_axis_angle(np.array([0.0, 0.0, yaw]))
