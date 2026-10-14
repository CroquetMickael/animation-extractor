"""Minimal replacement for pytorch3d.transforms (no prebuilt Windows wheel exists).

Conventions match pytorch3d: quaternions are (w, x, y, z) real-first, matrices act on column vectors,
6D rotation = first two ROWS of the matrix (Zhou et al.), euler conventions given as e.g. "XYZ".
"""
import torch
import torch.nn.functional as F


def _sqrt_positive_part(x):
    ret = torch.zeros_like(x)
    positive = x > 0
    ret[positive] = torch.sqrt(x[positive])
    return ret


def standardize_quaternion(quaternions):
    return torch.where(quaternions[..., 0:1] < 0, -quaternions, quaternions)


def quaternion_to_matrix(quaternions):
    r, i, j, k = torch.unbind(quaternions, -1)
    two_s = 2.0 / (quaternions * quaternions).sum(-1)
    o = torch.stack(
        (
            1 - two_s * (j * j + k * k),
            two_s * (i * j - k * r),
            two_s * (i * k + j * r),
            two_s * (i * j + k * r),
            1 - two_s * (i * i + k * k),
            two_s * (j * k - i * r),
            two_s * (i * k - j * r),
            two_s * (j * k + i * r),
            1 - two_s * (i * i + j * j),
        ),
        -1,
    )
    return o.reshape(quaternions.shape[:-1] + (3, 3))


def matrix_to_quaternion(matrix):
    if matrix.size(-1) != 3 or matrix.size(-2) != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")

    batch_dim = matrix.shape[:-2]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = torch.unbind(matrix.reshape(batch_dim + (9,)), dim=-1)

    q_abs = _sqrt_positive_part(
        torch.stack(
            [
                1.0 + m00 + m11 + m22,
                1.0 + m00 - m11 - m22,
                1.0 - m00 + m11 - m22,
                1.0 - m00 - m11 + m22,
            ],
            dim=-1,
        )
    )

    quat_by_rijk = torch.stack(
        [
            torch.stack([q_abs[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01], dim=-1),
            torch.stack([m21 - m12, q_abs[..., 1] ** 2, m10 + m01, m02 + m20], dim=-1),
            torch.stack([m02 - m20, m10 + m01, q_abs[..., 2] ** 2, m12 + m21], dim=-1),
            torch.stack([m10 - m01, m20 + m02, m21 + m12, q_abs[..., 3] ** 2], dim=-1),
        ],
        dim=-2,
    )

    floor = torch.tensor(0.1).to(dtype=q_abs.dtype, device=q_abs.device)
    quat_candidates = quat_by_rijk / (2.0 * q_abs[..., None].max(floor))

    best = F.one_hot(q_abs.argmax(dim=-1), num_classes=4) > 0.5
    out = quat_candidates[best, :].reshape(batch_dim + (4,))
    return standardize_quaternion(out)


def axis_angle_to_quaternion(axis_angle):
    angles = torch.norm(axis_angle, p=2, dim=-1, keepdim=True)
    sin_half_over_angle = torch.where(
        angles.abs() < 1e-6,
        0.5 - (angles * angles) / 48,
        torch.sin(angles * 0.5) / torch.where(angles.abs() < 1e-6, torch.ones_like(angles), angles),
    )
    return torch.cat([torch.cos(angles * 0.5), axis_angle * sin_half_over_angle], dim=-1)


def quaternion_to_axis_angle(quaternions):
    norms = torch.norm(quaternions[..., 1:], p=2, dim=-1, keepdim=True)
    half_angles = torch.atan2(norms, quaternions[..., :1])
    angles = 2 * half_angles
    small = angles.abs() < 1e-6
    sin_half_over_angle = torch.where(
        small,
        0.5 - (angles * angles) / 48,
        torch.sin(half_angles) / torch.where(small, torch.ones_like(angles), angles),
    )
    return quaternions[..., 1:] / sin_half_over_angle


def axis_angle_to_matrix(axis_angle):
    return quaternion_to_matrix(axis_angle_to_quaternion(axis_angle))


def matrix_to_axis_angle(matrix):
    return quaternion_to_axis_angle(matrix_to_quaternion(matrix))


def rotation_6d_to_matrix(d6):
    a1, a2 = d6[..., :3], d6[..., 3:]
    b1 = F.normalize(a1, dim=-1)
    b2 = a2 - (b1 * a2).sum(-1, keepdim=True) * b1
    b2 = F.normalize(b2, dim=-1)
    b3 = torch.cross(b1, b2, dim=-1)
    return torch.stack((b1, b2, b3), dim=-2)


def matrix_to_rotation_6d(matrix):
    batch_dim = matrix.size()[:-2]
    return matrix[..., :2, :].clone().reshape(batch_dim + (6,))


def _axis_angle_rotation(axis, angle):
    cos = torch.cos(angle)
    sin = torch.sin(angle)
    one = torch.ones_like(angle)
    zero = torch.zeros_like(angle)

    if axis == "X":
        flat = (one, zero, zero, zero, cos, -sin, zero, sin, cos)
    elif axis == "Y":
        flat = (cos, zero, sin, zero, one, zero, -sin, zero, cos)
    elif axis == "Z":
        flat = (cos, -sin, zero, sin, cos, zero, zero, zero, one)
    else:
        raise ValueError("letter must be either X, Y or Z.")

    return torch.stack(flat, -1).reshape(angle.shape + (3, 3))


def euler_angles_to_matrix(euler_angles, convention):
    if euler_angles.dim() == 0 or euler_angles.shape[-1] != 3:
        raise ValueError("Invalid input euler angles.")
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    matrices = [_axis_angle_rotation(c, e) for c, e in zip(convention, torch.unbind(euler_angles, -1))]
    return torch.matmul(torch.matmul(matrices[0], matrices[1]), matrices[2])


def quaternion_raw_multiply(a, b):
    aw, ax, ay, az = torch.unbind(a, -1)
    bw, bx, by, bz = torch.unbind(b, -1)
    ow = aw * bw - ax * bx - ay * by - az * bz
    ox = aw * bx + ax * bw + ay * bz - az * by
    oy = aw * by - ax * bz + ay * bw + az * bx
    oz = aw * bz + ax * by - ay * bx + az * bw
    return torch.stack((ow, ox, oy, oz), -1)


def quaternion_multiply(a, b):
    return standardize_quaternion(quaternion_raw_multiply(a, b))


def quaternion_invert(quaternion):
    scaling = torch.tensor([1, -1, -1, -1], device=quaternion.device, dtype=quaternion.dtype)
    return quaternion * scaling


def quaternion_apply(quaternion, point):
    real_parts = point.new_zeros(point.shape[:-1] + (1,))
    point_as_quaternion = torch.cat((real_parts, point), -1)
    out = quaternion_raw_multiply(
        quaternion_raw_multiply(quaternion, point_as_quaternion),
        quaternion_invert(quaternion),
    )
    return out[..., 1:]


def so3_exp_map(log_rot, eps=0.0001):
    return axis_angle_to_matrix(log_rot)


def so3_log_map(R, eps=0.0001, cos_bound=1e-4):
    return matrix_to_axis_angle(R)


def so3_relative_angle(R1, R2, cos_angle=False, eps=1e-4):
    R12 = torch.bmm(R1, R2.permute(0, 2, 1))
    trace = R12[:, 0, 0] + R12[:, 1, 1] + R12[:, 2, 2]
    phi_cos = ((trace - 1.0) * 0.5).clamp(-1.0 + eps, 1.0 - eps)
    return phi_cos if cos_angle else torch.acos(phi_cos)
