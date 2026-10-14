"""Suggest cut points where the motion changes character (Foote novelty on a pose self-similarity matrix)."""
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from . import rot

FEATURE_BONES = [
    "SKEL_ROOT", "SKEL_Spine2", "SKEL_Head",
    "SKEL_L_UpperArm", "SKEL_L_Forearm", "SKEL_R_UpperArm", "SKEL_R_Forearm",
    "SKEL_L_Thigh", "SKEL_L_Calf", "SKEL_R_Thigh", "SKEL_R_Calf",
]


def _features(skel, local_r, fps):
    indices = [skel.index(b) for b in FEATURE_BONES if skel.has(b)]
    q = local_r[:, indices]
    root = skel.index("SKEL_ROOT")
    # The root's heading says where the performer faces, not what they do: keep only its tilt.
    q[:, 0] = rot.mul(rot.inv(rot.yaw_only(local_r[:, root])), local_r[:, root])
    m = rot.to_matrix(q)[..., :2, :].reshape(len(q), -1)
    speed = np.zeros(len(q))
    speed[1:] = np.linalg.norm(np.diff(m, axis=0), axis=1) * fps
    # Pose says what the body looks like, speed says how much it moves (idle vs jog look alike frozen).
    window = max(1.0, fps * 0.25)
    pose = gaussian_filter1d(m, window, axis=0)
    energy = gaussian_filter1d(speed, fps * 0.5)[:, None]
    pose = (pose - pose.mean(0)) / (pose.std(0) + 1e-6)
    energy = (energy - energy.mean()) / (energy.std() + 1e-6)
    return np.hstack((pose, energy * np.sqrt(pose.shape[1]) * 0.5))


def _novelty(features, half):
    """Checkerboard kernel slid along the diagonal of the self-similarity matrix."""
    frames = len(features)
    norms = np.sum(features ** 2, axis=1)
    distance = np.sqrt(np.maximum(norms[:, None] + norms[None, :] - 2 * features @ features.T, 0))
    similarity = np.exp(-distance / (np.median(distance) + 1e-6))

    taper = np.exp(-0.5 * (np.linspace(-1, 1, 2 * half) / 0.5) ** 2)
    sign = np.ones((2 * half, 2 * half))
    sign[:half, half:] = -1
    sign[half:, :half] = -1
    kernel = sign * np.outer(taper, taper)

    padded = np.pad(similarity, half, mode="edge")
    novelty = np.zeros(frames)
    for t in range(frames):
        block = padded[t:t + 2 * half, t:t + 2 * half]
        novelty[t] = np.sum(block * kernel)
    novelty -= novelty.min()
    return novelty / (novelty.max() + 1e-9)


def cut_candidates(skel, local_r, fps, window_seconds=1.5):
    """Every plausible cut with a 0..1 score; the editor thresholds them live.
    A 1.5 s window ignores within-animation cycles (strides, arm swings) and keeps style changes."""
    frames = len(local_r)
    half = int(max(4, fps * window_seconds))
    if frames < 3 * half:
        return []
    novelty = _novelty(_features(skel, local_r, fps), half)
    peaks, props = find_peaks(novelty, distance=int(fps), prominence=0.02)
    margin = int(fps * 0.5)
    return [
        {"frame": int(p), "score": round(float(score), 3)}
        for p, score in zip(peaks, props["prominences"])
        if margin <= p <= frames - 1 - margin
    ]
