"""Start, stop and gait-change clips for a movement style, built from the style's own loops.

GTA looks for these next to idle/walk/run in the style's dictionary (move_m@tough_guy@ ships its own
wstart/wstop). Each one is the loops replayed on a stride clock: a start speeds the stride up from the
idle pose, a stop slows it down into the idle, a gait change cross-fades two loops kept in step. Timings
and the move events come from move_m@generic's clips; "_l" / "_left" start with the right foot planted
(the left one steps first), "_r" / "_right" the other way round, as in Rockstar's foot tags.
"""
import dataclasses

import numpy as np

from . import rot, ycd

MOVE_EVENT = "hash_7EA9DFC4"
# Rockstar's move events on move_m@generic, phases unchanged: (unk hash, event, start, end).
EVENTS = {
    "wstart_l_0": (("hash_AB8749DB", "hash_7E1C8464", 0.0, 1.0), ("hash_48F997B0", "hash_47A803B7", 0.354, 1.0), ("hash_9BD0774C", "hash_6A82789F", 0.545, 1.0)),
    "wstart_r_0": (("hash_AB8749DB", "hash_7E1C8464", 0.0, 1.0), ("hash_48F997B0", "hash_47A803B7", 0.354, 1.0), ("hash_9BD0774C", "hash_6A82789F", 0.545, 1.0)),
    "wstop_l_0": (("hash_AB8749DB", "hash_7E1C8464", 0.0, 1.0), ("hash_48F997B0", "hash_47A803B7", 0.167, 1.0), ("hash_6EE18AEA", "hash_FC86B701", 0.8, 1.0)),
    "wstop_r_0": (("hash_AB8749DB", "hash_7E1C8464", 0.0, 1.0), ("hash_48F997B0", "hash_47A803B7", 0.162, 1.0), ("hash_6EE18AEA", "hash_FC86B701", 0.8, 1.0)),
    "rstart_l_0": (("hash_AB8749DB", "hash_7E1C8464", 0.152, 1.0), ("hash_48F997B0", "hash_47A803B7", 0.311, 1.0), ("hash_9BD0774C", "hash_6A82789F", 0.599, 1.0)),
    "rstart_r_0": (("hash_AB8749DB", "hash_7E1C8464", 0.151, 1.0), ("hash_48F997B0", "hash_47A803B7", 0.311, 1.0), ("hash_9BD0774C", "hash_6A82789F", 0.625, 1.0)),
    "rstop_l": (("hash_7EC56529", "hash_0EF310EB", 0.0, 0.126), ("hash_48F997B0", "hash_47A803B7", 0.188, 1.0), ("hash_AB8749DB", "hash_7E1C8464", 0.212, 1.0), ("hash_6EE18AEA", "hash_FC86B701", 0.8, 1.0)),
    "rstop_r": (("hash_7EC56529", "hash_0EF310EB", 0.0, 0.121), ("hash_48F997B0", "hash_47A803B7", 0.179, 1.0), ("hash_AB8749DB", "hash_7E1C8464", 0.247, 1.0), ("hash_6EE18AEA", "hash_FC86B701", 0.8, 1.0)),
    "walktorun_left": (("hash_4F2FFA27", "hash_56A84EF6", 0.0, 0.085), ("hash_286C1768", "hash_68AB84B5", 0.261, 0.261), ("hash_2FCCF0C6", "hash_59DA8702", 0.261, 1.0), ("hash_DA19AA85", "hash_1B29D114", 0.444, 1.0)),
    "walktorun_right": (("hash_4F2FFA27", "hash_56A84EF6", 0.0, 0.085), ("hash_286C1768", "hash_68AB84B5", 0.261, 0.261), ("hash_2FCCF0C6", "hash_59DA8702", 0.261, 1.0), ("hash_DA19AA85", "hash_1B29D114", 0.458, 1.0)),
    "runtowalk_left": (("hash_CADA7674", "hash_5B638EFA", 0.0, 0.152), ("hash_FD18F0F6", "hash_36EFDB93", 0.221, 0.221), ("hash_CF3C38B7", "hash_6C1856F5", 0.221, 1.0), ("hash_39EA44A7", "hash_E3439045", 0.519, 1.0)),
    "runtowalk_right": (("hash_CADA7674", "hash_5B638EFA", 0.0, 0.152), ("hash_FD18F0F6", "hash_36EFDB93", 0.221, 0.221), ("hash_CF3C38B7", "hash_6C1856F5", 0.221, 1.0), ("hash_39EA44A7", "hash_E3439045", 0.475, 1.0)),
}
# (clip name with {} for the side, total seconds, seconds to reach the loop / to come to rest).
# Measured on move_m@generic: walk starts reach speed in ~0.9 s, run starts in ~1.1 s, stops are still
# after ~1.0 s (walk) / ~1.3 s (run) and then stand in the idle until the clip ends.
STARTS = {"walk": ("wstart_{}_0", 2.0, 0.9), "run": ("rstart_{}_0", 1.8, 1.1)}
STOPS = {"walk": ("wstop_{}_0", 3.6, 1.0), "run": ("rstop_{}", 3.7, 1.3)}
# (clip name, from, to, total seconds, seconds of cross-fade).
GAIT_CHANGES = (("walktorun_{}", "walk", "run", 1.65, 0.7), ("runtowalk_{}", "run", "walk", 2.27, 1.0))
SIDES = (("l", "left", 0), ("r", "right", 1))  # suffix, long suffix, foot planted first: 0 = right
START_STRIDE_RATE = 0.4  # share of the loop's cadence the first step starts at


def build(loops, idle):
    """loops: {slot: straight ycd.ClipData}, idle: ycd.ClipData or None. Returns the transition clips."""
    out = []
    for slot in ("walk", "run"):
        loop = loops.get(slot)
        if loop is None or idle is None:
            continue
        name, seconds, ramp = STARTS[slot]
        stop_name, stop_seconds, settle = STOPS[slot]
        for short, _, foot in SIDES:
            out.append(_start(name.format(short), loop, idle, seconds, ramp, foot))
            out.append(_stop(stop_name.format(short), loop, idle, stop_seconds, settle, foot))
    for name, source, target, seconds, fade in GAIT_CHANGES:
        if source in loops and target in loops:
            for _, long, foot in SIDES:
                out.append(_gait_change(name.format(long), loops[source], loops[target], seconds, fade, foot))
    return out


def names(slots, has_idle):
    """Transition clip names build() makes for these assigned slots."""
    out = []
    for slot in ("walk", "run"):
        if slot in slots and has_idle:
            for short, _, _ in SIDES:
                out += [STARTS[slot][0].format(short), STOPS[slot][0].format(short)]
    for name, source, target, *_ in GAIT_CHANGES:
        if source in slots and target in slots:
            out += [name.format(long) for _, long, _ in SIDES]
    return out


@dataclasses.dataclass
class _Loop:
    """A straight loop on a stride clock: stride phase s (0 = right strike, the loop's first frame)."""
    clip: ycd.ClipData
    strides: int
    left_phase: float  # stride phase of the left strike
    rate: float  # strides per second
    speed: float  # metres per second

    @classmethod
    def of(cls, clip):
        rights = [t["start"] for t in clip.tags or [] if _foot_side(t) == "R"]
        lefts = [t["start"] for t in clip.tags or [] if _foot_side(t) == "L"]
        strides = max(1, len(rights))
        cycle = (clip.local_r.shape[0] - 1) / clip.fps
        left = (lefts[0] * strides) % 1.0 if lefts else 0.5
        distance = np.linalg.norm(clip.mover_t[-1, :2] - clip.mover_t[0, :2]) if clip.mover_t is not None else 0.0
        return cls(clip, strides, left, strides / cycle, distance / cycle)

    def pose(self, stride_phase):
        """Rotations (T, B, 4) and root translation (T, 3) at the given stride phases."""
        frames = self.clip.local_r.shape[0]
        position = ((np.asarray(stride_phase) / self.strides) % 1.0) * (frames - 1)
        i0 = np.floor(position).astype(int).clip(0, frames - 2)
        alpha = position - i0
        q = rot.make_continuous(self.clip.local_r)
        r = rot.slerp(q[i0], q[i0 + 1], np.broadcast_to(alpha[:, None], q[i0].shape[:-1]))
        t = self.clip.root_t[i0] * (1 - alpha[:, None]) + self.clip.root_t[i0 + 1] * alpha[:, None]
        return r, t


def _foot_side(tag):
    from .moveset import TAG_FOOT
    if tag["name"] != TAG_FOOT:
        return None
    right = next((value for name, _, value in tag["attrs"] if name == "right"), "0")
    return "R" if right == "1" else "L"


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def _idle_pose(idle, seconds):
    frames = idle.local_r.shape[0]
    index = np.round(np.asarray(seconds) * idle.fps).astype(int) % max(frames - 1, 1)
    return idle.local_r[index], idle.root_t[index]


def _blend(rot_a, t_a, rot_b, t_b, weight):
    r = rot.slerp(rot_a, rot_b, np.broadcast_to(weight[:, None], rot_a.shape[:-1]))
    return r, t_a * (1 - weight[:, None]) + t_b * weight[:, None]


def _strikes(stride_phase, left_phase, active):
    """(side, frame) each time the stride clock passes a foot strike while the loop drives the legs."""
    out = []
    for frame in range(1, len(stride_phase)):
        for side, offset in (("R", 0.0), ("L", left_phase)):
            if np.floor(stride_phase[frame] - offset) > np.floor(stride_phase[frame - 1] - offset) and active[frame]:
                out.append((side, frame))
    return out


def _clip(name, loop, local_r, root_t, speed, strikes):
    from .moveset import _foot_tags
    frames = len(local_r)
    step = np.zeros((frames, 2))
    step[1:, 1] = speed[1:] / loop.fps
    mover_t = np.concatenate((np.cumsum(step, axis=0), np.full((frames, 1), loop.mover_t[0, 2])), axis=1)
    mover_r = np.tile(rot.IDENTITY, (frames, 1))
    tags = _foot_tags(sorted(strikes, key=lambda s: s[1]), 0, frames - 1)
    tags += [{"name": MOVE_EVENT, "unk": unk, "attrs": [(MOVE_EVENT, "HashString", event)], "start": start, "end": end}
             for unk, event, start, end in EVENTS[name]]
    tags.sort(key=lambda tag: tag["start"])
    return dataclasses.replace(loop, name=name, local_r=rot.normalize(local_r), root_t=root_t, looped=False,
                               mover_t=mover_t, mover_r=mover_r, tags=tags)


def _start(name, clip, idle, seconds, ramp, foot):
    loop = _Loop.of(clip)
    t = np.arange(int(round(seconds * clip.fps)) + 1) / clip.fps
    progress = _smooth(t / ramp)
    rate = loop.rate * (START_STRIDE_RATE + (1 - START_STRIDE_RATE) * progress)
    stride = (loop.left_phase if foot else 0.0) + np.concatenate(([0.0], np.cumsum(rate[1:]) / clip.fps))
    weight = _smooth(t / (0.7 * ramp))
    walk_r, walk_t = loop.pose(stride)
    idle_r, idle_t = _idle_pose(idle, np.zeros_like(t))
    local_r, root_t = _blend(idle_r, idle_t, walk_r, walk_t, weight)
    strikes = [("L" if foot else "R", 0)] + _strikes(stride, loop.left_phase, weight > 0.3)
    return _clip(name, clip, local_r, root_t, loop.speed * progress, strikes)


def _stop(name, clip, idle, seconds, settle, foot):
    loop = _Loop.of(clip)
    t = np.arange(int(round(seconds * clip.fps)) + 1) / clip.fps
    slowing = _smooth(t / settle)
    rate = loop.rate * (1 - (1 - START_STRIDE_RATE) * slowing)
    stride = (loop.left_phase if foot else 0.0) + np.concatenate(([0.0], np.cumsum(rate[1:]) / clip.fps))
    weight = _smooth((t - 0.3 * settle) / (0.7 * settle))
    walk_r, walk_t = loop.pose(stride)
    idle_r, idle_t = _idle_pose(idle, np.maximum(t - 0.3 * settle, 0.0))
    local_r, root_t = _blend(walk_r, walk_t, idle_r, idle_t, weight)
    strikes = [("L" if foot else "R", 0)] + _strikes(stride, loop.left_phase, weight < 0.7)
    return _clip(name, clip, local_r, root_t, loop.speed * (1 - slowing), strikes)


def _gait_change(name, source_clip, target_clip, seconds, fade, foot):
    source, target = _Loop.of(source_clip), _Loop.of(target_clip)
    t = np.arange(int(round(seconds * target_clip.fps)) + 1) / target_clip.fps
    weight = _smooth(t / fade)
    rate = source.rate * (1 - weight) + target.rate * weight
    start = source.left_phase if foot else 0.0
    stride = start + np.concatenate(([0.0], np.cumsum(rate[1:]) / target_clip.fps))
    # Both loops start on a right strike: the same stride phase puts the feet in the same place.
    target_stride = stride - start + (target.left_phase if foot else 0.0)
    a_r, a_t = source.pose(stride)
    b_r, b_t = target.pose(target_stride)
    local_r, root_t = _blend(a_r, a_t, b_r, b_t, weight)
    strikes = [("L" if foot else "R", 0)] + _strikes(stride, source.left_phase, np.ones(len(t), dtype=bool))
    return _clip(name, target_clip, local_r, root_t, source.speed * (1 - weight) + target.speed * weight, strikes)
