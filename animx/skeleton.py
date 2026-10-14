"""GTA ped skeleton loaded from the bridge export, with batched forward kinematics."""
import json
from functools import lru_cache

import numpy as np

from . import rot
from .paths import PEDS

ROOT_BONE = "SKEL_ROOT"


class Skeleton:
    def __init__(self, data):
        bones = data["bones"]
        self.ped = data["ped"]
        self.names = [b["name"] for b in bones]
        self.tags = np.array([b["tag"] for b in bones], dtype=np.int64)
        self.parents = np.array([b["parent"] for b in bones], dtype=np.int64)
        self.bind_t = np.array([b["t"] for b in bones], dtype=np.float64)
        self.bind_r = rot.normalize(np.array([b["r"] for b in bones], dtype=np.float64))
        self.index_by_name = {name: i for i, name in enumerate(self.names)}
        self.order = self._topological_order()
        self.count = len(bones)

    def _topological_order(self):
        order = []
        seen = set()

        def visit(i):
            if i in seen:
                return
            p = self.parents[i]
            if p >= 0:
                visit(p)
            seen.add(i)
            order.append(i)

        for i in range(len(self.parents)):
            visit(i)
        return order

    def index(self, name):
        return self.index_by_name[name]

    def has(self, name):
        return name in self.index_by_name

    def children(self, i):
        return [c for c in range(self.count) if self.parents[c] == i]

    def anim_rest_rotations(self):
        """Bind pose as animations see it: Rockstar clips keep SKEL_ROOT at identity (ped faces +Y)."""
        r = self.bind_r.copy()
        r[self.index(ROOT_BONE)] = rot.IDENTITY
        return r

    def fk(self, local_r, local_t=None):
        """local_r: (..., B, 4); local_t: (..., B, 3) or None for bind translations.
        Returns world rotations (..., B, 4) and positions (..., B, 3)."""
        local_r = np.asarray(local_r, dtype=np.float64)
        batch = local_r.shape[:-2]
        if local_t is None:
            local_t = np.broadcast_to(self.bind_t, batch + self.bind_t.shape)
        world_r = np.empty(batch + (self.count, 4))
        world_p = np.empty(batch + (self.count, 3))
        for i in self.order:
            p = self.parents[i]
            if p < 0:
                world_r[..., i, :] = local_r[..., i, :]
                world_p[..., i, :] = local_t[..., i, :]
                continue
            world_r[..., i, :] = rot.mul(world_r[..., p, :], local_r[..., i, :])
            world_p[..., i, :] = world_p[..., p, :] + rot.apply(world_r[..., p, :], local_t[..., i, :])
        return world_r, world_p

    def locals_from_world(self, world_r):
        local = np.empty_like(world_r)
        for i in range(self.count):
            p = self.parents[i]
            local[..., i, :] = world_r[..., i, :] if p < 0 else rot.mul(rot.inv(world_r[..., p, :]), world_r[..., i, :])
        return rot.normalize(local)


@lru_cache(maxsize=4)
def load(ped):
    path = PEDS / f"{ped}.skeleton.json"
    return Skeleton(json.loads(path.read_text(encoding="utf-8")))
