"""SMPL(-X) body rotations (GVHMR) -> GTA bone world rotations.

SMPL rest pose has identity joint rotations (T-pose, palms down, facing +Z, Y up, subject's left +X).
Each GTA bone takes the world rotation of the SMPL joint that owns the same segment, applied on top of
the GTA reference pose built from the SMPL rest directions, so both rests coincide.
"""
import numpy as np

from .. import rig, rot

PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19]
PELVIS, L_HIP, R_HIP, SPINE1, L_KNEE, R_KNEE, SPINE2, L_ANKLE, R_ANKLE, SPINE3 = range(10)
L_FOOT, R_FOOT, NECK, L_COLLAR, R_COLLAR, HEAD, L_SHOULDER, R_SHOULDER = range(10, 18)
L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = range(18, 22)

# SMPL (Y up, facing +Z, left +X) -> GTA animation space (Z up, facing +Y, left -X).
SMPL_TO_GTA = np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
Q_SMPL_TO_GTA = rot.from_matrix(SMPL_TO_GTA)

BONE_JOINT = {
    "SKEL_ROOT": PELVIS,
    "SKEL_Spine0": SPINE1,
    "SKEL_Spine2": SPINE2,
    "SKEL_Spine3": SPINE3,
    "SKEL_Neck_1": NECK,
    "SKEL_Head": HEAD,
    "SKEL_L_Thigh": L_HIP,
    "SKEL_L_Calf": L_KNEE,
    "SKEL_L_Foot": L_ANKLE,
    "SKEL_R_Thigh": R_HIP,
    "SKEL_R_Calf": R_KNEE,
    "SKEL_R_Foot": R_ANKLE,
    "SKEL_L_Clavicle": L_COLLAR,
    "SKEL_L_UpperArm": L_SHOULDER,
    "SKEL_L_Forearm": L_ELBOW,
    "SKEL_L_Hand": L_WRIST,
    "SKEL_R_Clavicle": R_COLLAR,
    "SKEL_R_UpperArm": R_SHOULDER,
    "SKEL_R_Forearm": R_ELBOW,
    "SKEL_R_Hand": R_WRIST,
}

SEGMENTS = {
    "SKEL_L_Thigh": (L_HIP, L_KNEE),
    "SKEL_L_Calf": (L_KNEE, L_ANKLE),
    "SKEL_R_Thigh": (R_HIP, R_KNEE),
    "SKEL_R_Calf": (R_KNEE, R_ANKLE),
    "SKEL_L_Clavicle": (L_COLLAR, L_SHOULDER),
    "SKEL_L_UpperArm": (L_SHOULDER, L_ELBOW),
    "SKEL_L_Forearm": (L_ELBOW, L_WRIST),
    "SKEL_L_Hand": (L_ELBOW, L_WRIST),
    "SKEL_R_Clavicle": (R_COLLAR, R_SHOULDER),
    "SKEL_R_UpperArm": (R_SHOULDER, R_ELBOW),
    "SKEL_R_Forearm": (R_ELBOW, R_WRIST),
    "SKEL_R_Hand": (R_ELBOW, R_WRIST),
    "SKEL_Neck_1": (NECK, HEAD),
    "SKEL_L_Foot": (L_ANKLE, L_FOOT),
    "SKEL_R_Foot": (R_ANKLE, R_FOOT),
}


def to_gta(v):
    return np.asarray(v, dtype=np.float64) @ SMPL_TO_GTA.T


def reference_directions(capture):
    rest = to_gta(capture["rest_joints"])
    directions = dict(rig.CANONICAL_DIRECTIONS)
    for bone, (a, b) in SEGMENTS.items():
        d = rest[b] - rest[a]
        directions[bone] = d / np.linalg.norm(d)
    return directions


def global_rotations(capture):
    local = np.concatenate(
        (np.asarray(capture["global_orient"])[:, None], np.asarray(capture["body_pose"]).reshape(-1, 21, 3)), axis=1
    )
    local_q = rot.from_axis_angle(local)
    world = np.empty_like(local_q)
    for j, parent in enumerate(PARENTS):
        world[:, j] = local_q[:, j] if parent < 0 else rot.mul(world[:, parent], local_q[:, j])
    return rot.mul(rot.mul(Q_SMPL_TO_GTA, world), rot.inv(Q_SMPL_TO_GTA))


def upright_correction(joints):
    """GVHMR's gravity guess drifts with steep camera angles; assume the performer stands upright on
    average and rotate the median pelvis->neck axis onto +Z."""
    spine = joints[:, NECK] - joints[:, PELVIS]
    spine /= np.linalg.norm(spine, axis=-1, keepdims=True).clip(1e-9)
    median_up = np.median(spine, axis=0)
    return rot.between(median_up / np.linalg.norm(median_up), rig.UP)


def solve(skel, reference_local, capture, upright=True):
    """Returns ({bone: (T, 4) world rotation}, pelvis position (T, 3) scaled to the ped, camera track or None)."""
    world_smpl = global_rotations(capture)
    joints = to_gta(capture["joints"])
    correction = rot.IDENTITY
    if upright:
        correction = upright_correction(joints)
        world_smpl = rot.mul(correction, world_smpl)
        joints = rot.apply(correction, joints)
    ref_world = rig.reference_world(skel, reference_local)
    driven = {}
    for bone, joint in BONE_JOINT.items():
        driven[bone] = rot.mul(world_smpl[:, joint], ref_world[skel.index(bone)])
    driven["SKEL_Spine1"] = rot.mul(rot.slerp(world_smpl[:, SPINE1], world_smpl[:, SPINE2], 0.5), ref_world[skel.index("SKEL_Spine1")])

    rest = to_gta(capture["rest_joints"])
    smpl_leg = np.linalg.norm(rest[L_KNEE] - rest[L_HIP]) + np.linalg.norm(rest[L_ANKLE] - rest[L_KNEE])
    _, ref_p = skel.fk(reference_local)
    gta_leg = (np.linalg.norm(ref_p[skel.index("SKEL_L_Calf")] - ref_p[skel.index("SKEL_L_Thigh")])
               + np.linalg.norm(ref_p[skel.index("SKEL_L_Foot")] - ref_p[skel.index("SKEL_L_Calf")]))
    scale = gta_leg / smpl_leg
    pelvis = joints[:, PELVIS] * scale
    track = camera_track(capture, correction, joints, scale)
    return driven, pelvis, track, joints * scale


def camera_track(capture, correction, joints_gta, scale):
    """Where the video camera sat relative to the pelvis, per frame, in GTA space (scaled like the ped).
    The camera-frame joints and the world joints are the same body, so a rigid fit per frame
    recovers the camera pose."""
    if "cam_joints" not in capture:
        return None
    cam = np.asarray(capture["cam_joints"], dtype=np.float64)
    world = np.asarray(capture["joints"], dtype=np.float64)
    frames = min(len(cam), len(world))
    position = np.zeros((len(world), 3))
    forward = np.zeros((len(world), 3))
    up = np.zeros((len(world), 3))
    for f in range(frames):
        r, t = _rigid_fit(cam[f], world[f])
        position[f] = t
        forward[f] = r @ np.array([0.0, 0.0, 1.0])
        up[f] = r @ np.array([0.0, -1.0, 0.0])
    position[frames:] = position[frames - 1]
    forward[frames:] = forward[frames - 1]
    up[frames:] = up[frames - 1]

    to_world = lambda v: rot.apply(correction, to_gta(v))
    offset = to_world(position) * scale - joints_gta[:, PELVIS] * scale
    focal = float(capture["K"][1, 1])
    height = float(capture["K"][1, 2]) * 2.0
    return {
        "offset": offset,
        "forward": to_world(forward),
        "up": to_world(up),
        "fov": float(np.degrees(2.0 * np.arctan(height / (2.0 * focal)))),
    }


def _rigid_fit(source, target):
    """R, t minimising |R @ source + t - target| (Kabsch)."""
    cs, ct = source.mean(axis=0), target.mean(axis=0)
    h = (source - cs).T @ (target - ct)
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return r, ct - r @ cs
