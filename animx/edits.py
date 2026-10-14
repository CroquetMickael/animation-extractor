"""Manual corrections drawn in the editor.

Calibration: one local offset per bone, applied to every frame of every clip (fixes systematic retarget error).
Keys: {bone, frame, q, radius} local offsets that fade out over `radius` frames around `frame`
(radius < 0 = whole clip). Applied as L' = L * offset, so the editor can store Lbase^-1 * Ledited.
"""
import numpy as np

from . import rot


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
        if not skel.has(name):
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
        if key.get("bone") != "__root_offset__":
            continue
        w = key_weights(frames, int(key.get("frame", 0)), key.get("radius", 10))
        out += np.asarray(key["t"], dtype=np.float64)[None, :] * w[:, None]
    return out
