"""Whole-clip transforms: play backwards, mirror left <-> right."""
import numpy as np

from . import rot


def partner_indices(skel):
    """Each bone's mirror counterpart (_L_ <-> _R_, e.g. SKEL_L_Hand <-> SKEL_R_Hand, FB_L_Lip <-> FB_R_Lip)."""
    out = np.arange(skel.count)
    for i, name in enumerate(skel.names):
        for a, b in (("_L_", "_R_"), ("_R_", "_L_")):
            if a in name:
                other = name.replace(a, b, 1)
                if skel.has(other):
                    out[i] = skel.index(other)
                break
    return out


def _reflect(q):
    """Reflection of a rotation through the sagittal plane (x = 0): axis (x, y, z) -> (x, -y, -z)."""
    return q * np.array([1.0, -1.0, -1.0, 1.0])


def mirror(skel, local_r, root_t):
    """Mirror a clip left <-> right. Works on each bone's change from its rest pose in world space,
    so it doesn't depend on how Rockstar oriented the left and right bone frames."""
    rest_world, _ = skel.fk(skel.anim_rest_rotations())
    world, _ = skel.fk(local_r)
    partner = partner_indices(skel)

    delta = rot.mul(world, rot.inv(rest_world)[None])
    mirrored_world = rot.mul(_reflect(delta[:, partner]), rest_world[None])
    mirrored_local = skel.locals_from_world(mirrored_world)

    mirrored_t = root_t.copy()
    mirrored_t[:, 0] *= -1.0
    return mirrored_local, mirrored_t


def mirror_vectors(v):
    out = np.array(v, copy=True)
    out[..., 0] *= -1.0
    return out
