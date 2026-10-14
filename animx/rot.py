"""Vectorised quaternion helpers. Quaternions are (x, y, z, w), Hamilton product — same as GTA/SharpDX/three.js."""
import numpy as np

IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])


def normalize(q):
    q = np.asarray(q, dtype=np.float64)
    return q / np.linalg.norm(q, axis=-1, keepdims=True).clip(1e-12)


def mul(a, b):
    ax, ay, az, aw = np.moveaxis(np.asarray(a, dtype=np.float64), -1, 0)
    bx, by, bz, bw = np.moveaxis(np.asarray(b, dtype=np.float64), -1, 0)
    return np.stack(
        (
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        ),
        axis=-1,
    )


def inv(q):
    q = np.asarray(q, dtype=np.float64)
    return q * np.array([-1.0, -1.0, -1.0, 1.0])


def apply(q, v):
    q = np.asarray(q, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    u = q[..., :3]
    w = q[..., 3:4]
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def from_matrix(m):
    m = np.asarray(m, dtype=np.float64)
    m00, m01, m02 = m[..., 0, 0], m[..., 0, 1], m[..., 0, 2]
    m10, m11, m12 = m[..., 1, 0], m[..., 1, 1], m[..., 1, 2]
    m20, m21, m22 = m[..., 2, 0], m[..., 2, 1], m[..., 2, 2]
    candidates = np.stack(
        (
            np.stack((m21 - m12, m02 - m20, m10 - m01, 1.0 + m00 + m11 + m22), -1),
            np.stack((1.0 + m00 - m11 - m22, m01 + m10, m02 + m20, m21 - m12), -1),
            np.stack((m01 + m10, 1.0 - m00 + m11 - m22, m12 + m21, m02 - m20), -1),
            np.stack((m02 + m20, m12 + m21, 1.0 - m00 - m11 + m22, m10 - m01), -1),
        ),
        axis=-2,
    )
    traces = np.stack((m00 + m11 + m22, m00, m11, m22), -1)
    best = np.argmax(traces, axis=-1)
    q = np.take_along_axis(candidates, best[..., None, None], axis=-2)[..., 0, :]
    return normalize(q)


def to_matrix(q):
    x, y, z, w = np.moveaxis(normalize(q), -1, 0)
    return np.stack(
        (
            np.stack((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)), -1),
            np.stack((2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)), -1),
            np.stack((2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)), -1),
        ),
        axis=-2,
    )


def from_axis_angle(axis_angle):
    axis_angle = np.asarray(axis_angle, dtype=np.float64)
    angle = np.linalg.norm(axis_angle, axis=-1, keepdims=True)
    half = angle * 0.5
    scale = np.where(angle < 1e-8, 0.5 - angle * angle / 48.0, np.sin(half) / np.where(angle < 1e-8, 1.0, angle))
    return np.concatenate((axis_angle * scale, np.cos(half)), axis=-1)


def to_axis_angle(q):
    q = canonical(normalize(q))
    sin_half = np.linalg.norm(q[..., :3], axis=-1, keepdims=True)
    angle = 2.0 * np.arctan2(sin_half, q[..., 3:4])
    scale = np.where(sin_half < 1e-8, 2.0, angle / np.where(sin_half < 1e-8, 1.0, sin_half))
    return q[..., :3] * scale


def between(u, v):
    """Shortest rotation taking direction u onto direction v."""
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    u = u / np.linalg.norm(u, axis=-1, keepdims=True).clip(1e-12)
    v = v / np.linalg.norm(v, axis=-1, keepdims=True).clip(1e-12)
    d = np.sum(u * v, axis=-1, keepdims=True)
    c = np.cross(u, v)
    q = np.concatenate((c, 1.0 + d), axis=-1)

    opposite = (d[..., 0] < -0.999999)
    if np.any(opposite):
        fallback = np.cross(u, np.array([1.0, 0.0, 0.0]))
        small = np.linalg.norm(fallback, axis=-1) < 1e-6
        fallback[small] = np.cross(u[small] if u.ndim > 1 else u, np.array([0.0, 1.0, 0.0]))
        fallback = fallback / np.linalg.norm(fallback, axis=-1, keepdims=True)
        q[opposite] = np.concatenate((fallback, np.zeros(fallback.shape[:-1] + (1,))), axis=-1)[opposite]
    return normalize(q)


def canonical(q):
    """Hemisphere with w >= 0."""
    q = np.asarray(q, dtype=np.float64)
    return np.where(q[..., 3:4] < 0, -q, q)


def make_continuous(q, axis=0):
    """Flip signs along time so consecutive quaternions stay in the same hemisphere."""
    q = np.array(q, dtype=np.float64, copy=True)
    q = np.moveaxis(q, axis, 0)
    for t in range(1, q.shape[0]):
        flip = np.sum(q[t] * q[t - 1], axis=-1) < 0
        q[t][flip] *= -1
    return np.moveaxis(q, 0, axis)


def slerp(a, b, t):
    a = normalize(a)
    b = normalize(b)
    t = np.asarray(t, dtype=np.float64)
    if t.ndim < a.ndim:
        t = t[..., None]
    d = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(d < 0, -b, b)
    d = np.abs(d)
    theta = np.arccos(np.clip(d, -1.0, 1.0))
    sin_theta = np.sin(theta)
    linear = sin_theta < 1e-6
    wa = np.where(linear, 1.0 - t, np.sin((1.0 - t) * theta) / np.where(linear, 1.0, sin_theta))
    wb = np.where(linear, t, np.sin(t * theta) / np.where(linear, 1.0, sin_theta))
    return normalize(wa * a + wb * b)


def from_frame(forward, up):
    """Rotation whose local +Y maps to `forward` and +Z to `up` (orthonormalised, forward wins)."""
    f = np.asarray(forward, dtype=np.float64)
    f = f / np.linalg.norm(f, axis=-1, keepdims=True).clip(1e-12)
    u = np.asarray(up, dtype=np.float64)
    r = np.cross(f, u)
    r = r / np.linalg.norm(r, axis=-1, keepdims=True).clip(1e-12)
    u = np.cross(r, f)
    m = np.stack((r, f, u), axis=-1)
    return from_matrix(m)


def twist_angle(q, axis):
    """Signed twist of rotation q around a unit axis (swing-twist decomposition)."""
    axis = np.asarray(axis, dtype=np.float64)
    proj = np.sum(q[..., :3] * axis, axis=-1)
    return 2.0 * np.arctan2(proj, q[..., 3])


def yaw_only(q):
    """Keep only the rotation about world Z."""
    forward = apply(q, np.array([0.0, 1.0, 0.0]))
    heading = np.arctan2(-forward[..., 0], forward[..., 1])
    return from_axis_angle(np.stack((np.zeros_like(heading), np.zeros_like(heading), heading), -1))
