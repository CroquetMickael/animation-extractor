"""Movement styles (movement clipsets): idle / walk / run / sprint that GTA chains on its own.

Modelled on Rockstar's styles (move_m@hipster@a, move_m@tough_guy@): the dictionary provides idle, walk,
run and sprint, plus turn clips derived from each loop (see turn_clip) and starts, stops and gait changes
(see transitions); slopes still come from a fallback clipset (the freemode default, move_m@multiplayer or
move_f@multiplayer). Locomotion clips carry the same foot tags as Rockstar's (heel strikes, flagged
right/left, plus a window from each right strike to the next left one) so the game can phase-match
transitions between gaits.
"""
import dataclasses
import json
import shutil
from dataclasses import dataclass

import numpy as np

from . import cleanup, gait, ground, pipeline, project as projects, root_motion, rot, skeleton, transitions, ycd
from .paths import PROJECTS

SLOTS = ("idle", "walk", "run", "sprint")
# Rockstar's own ground speeds (move_m@generic): keeping them keeps the ped's gameplay speed vanilla.
DEFAULT_SPEEDS = {"walk": 1.71, "run": 5.11, "sprint": 6.85}
FALLBACKS = {"mp_m_freemode_01": "move_m@multiplayer", "mp_f_freemode_01": "move_f@multiplayer"}

# Tag layout copied from move_m@hipster@a/walk.
TAG_FOOT = "hash_B82E430B"
TAG_FOOT_RIGHT_UNK = "hash_4F473F6A"
TAG_FOOT_LEFT_UNK = "hash_7E0050C6"
ATTR_HEEL = "hash_2BC03824"
TAG_WINDOW = "hash_7EA9DFC4"
TAG_WINDOW_UNK = "hash_6025BA94"
TAG_WINDOW_VALUE = "hash_08F7E474"

FOOT_TOUCH = 0.03
FOOT_LIFT = 0.06
LOOP_BLEND_FRAMES = 4

# Turn clips GTA looks for in a style's own dictionary. Without them the ped pivots stiffly as a block
# (move_f@injured ships walk_turn_l3/l4/r3/r4 next to its walk for that reason). Measured on
# move_m@generic: (name with {} for l/r, left turn rate deg/s, speed as a fraction of the straight clip,
# pelvis lean deg, share of that lean the spine takes back). The spine shares are tuned so the
# pelvis -> neck line leans like Rockstar's (~12 deg running or sprinting, ~2 deg walking). The right
# turns mirror the left ones.
TURNS = {
    "walk": (("walk_turn_{}3", 100.0, 1.0, 1.5, 0.0), ("walk_turn_{}4", 145.0, 0.66, 2.5, 0.0)),
    "run": (("run_turn_{}2", 120.0, 0.75, 20.0, 0.85), ("run_turn_{}3", 405.0, 0.49, 19.0, 0.85)),
    "sprint": (("sprint_turn_{}", 200.0, 0.72, 10.5, 0.0),),
}


@dataclass
class SlotResult:
    slot: str
    clip: ycd.ClipData
    strides: int
    speed: float
    aligned: bool = True
    turns: list = None  # ycd.ClipData turn clips derived from the straight loop


def suggest(project):
    """Each clip's likely slot from its gait."""
    out = []
    skel = skeleton.load(project.settings["ped"])
    for clip in project.clips():
        motion = pipeline.clip_motion(project, {**clip, "motion": "inplace", "loop": False, "speed": 1.0})
        analysis = gait.analyze(skel, motion.local_r, motion.fps)
        slot = "idle"
        if analysis:
            slot = {"marche": "walk", "jogging": "run", "course": "run", "sprint": "sprint"}[analysis["gait"]]
        out.append({"clip": clip["id"], "name": clip["name"], "slot": slot, "analysis": analysis})
    return out


def heel_strikes(skel, local_r, root_t):
    """Frames where each heel lands: (side, frame) with side "R"/"L", in time order."""
    soles = ground.sole_points(skel, local_r, root_t)
    strikes = []
    for s, side in enumerate(("L", "R")):
        # Lowest of heel and toe: runners land on the forefoot. Separate touch/lift thresholds ignore jitter.
        height = soles[:, s, :, 2].min(axis=1) - ground.GROUND_Z
        planted = height[0] < FOOT_TOUCH
        for t in range(1, len(height)):
            if not planted and height[t] < FOOT_TOUCH:
                planted = True
                strikes.append((side, t))
            elif planted and height[t] > FOOT_LIFT:
                planted = False
    return sorted(strikes, key=lambda strike: strike[1])


def _whole_strides(strikes):
    """Loop bounds on right heel strikes inside the longest run of strictly alternating feet.

    Rockstar's loops always alternate right/left. A clip that ends on a deceleration has the feet
    stop alternating (two rights in a row, a foot left planted); the game crashed on such a loop."""
    best, current = [], []
    for strike in strikes:
        current = current + [strike] if current and current[-1][0] != strike[0] else [strike]
        rights = [t for side, t in current if side == "R"]
        if len(rights) > len([t for side, t in best if side == "R"]):
            best = current
    rights = [t for side, t in best if side == "R"]
    if len(rights) < 2:
        return None
    return rights[0], rights[-1], len(rights) - 1


def _foot_tags(strikes, start, end):
    """Phases in [0, 1): the closing strike is the opening one seen again by the loop.

    No tags at all unless the feet strictly alternate: two strikes of the same foot in a row crashed the
    game when the clip played as a style (Rockstar ships tagless loops too, e.g. move_m@hurry@a)."""
    span = max(end - start, 1)
    inside = [(side, (t - start) / span) for side, t in strikes if start <= t < end]
    if any(a[0] == b[0] for a, b in zip(inside, inside[1:])):
        return []
    tags = []
    for i, (side, phase) in enumerate(inside):
        tags.append({"name": TAG_FOOT, "unk": TAG_FOOT_RIGHT_UNK if side == "R" else TAG_FOOT_LEFT_UNK,
                     "attrs": [(ATTR_HEEL, "Bool", "1"), ("right", "Bool", "1" if side == "R" else "0")],
                     "start": phase, "end": phase})
        if side == "R":
            following = next((p for s2, p in inside[i + 1:] if s2 == "L"), None)
            if following is not None:
                tags.append({"name": TAG_WINDOW, "unk": TAG_WINDOW_UNK, "attrs": [(TAG_WINDOW, "HashString", TAG_WINDOW_VALUE)],
                             "start": phase, "end": max(phase, following - 0.01)})
    return sorted(tags, key=lambda tag: tag["start"])


def build_slot(project, clip, slot, speed):
    skel = skeleton.load(project.settings["ped"])
    if slot == "idle":
        motion = pipeline.clip_motion(project, {**clip, "motion": "inplace", "loop": True, "loop_blend": max(8, clip.get("loop_blend", 8))})
        # Every Rockstar idle carries a mover track, still (move_m@generic, hipster): ours had none and the
        # game crashed once the ped started running from it.
        frames = motion.local_r.shape[0]
        data = ycd.ClipData(slot, motion.fps, motion.local_r, motion.root_t, ycd.default_bone_indices(skel, motion.local_r),
                            looped=True, translation_indices=ycd.helper_translation_indices(skel),
                            mover_t=np.tile([0.0, 0.0, root_motion.MOVER_Z], (frames, 1)), mover_r=np.tile(rot.IDENTITY, (frames, 1)))
        return SlotResult(slot, data, 0, 0.0)

    # Straight-ahead mover at the slot speed: the engine steers the ped, the clip only has to move it forward.
    motion = pipeline.clip_motion(project, {**clip, "motion": "mover", "travel": float(speed), "lateral": "none", "loop": False})
    strikes = heel_strikes(skel, motion.local_r, motion.root_t)
    bounds = _whole_strides(strikes)
    aligned = bounds is not None
    # Without two right-foot strikes the loop can't be cut on a stride: keep the whole clip and cross-fade it.
    start, end, strides = bounds if aligned else (0, len(motion.local_r) - 1, 0)
    local_r = motion.local_r[start:end + 1].copy()
    root_t = motion.root_t[start:end + 1].copy()
    mover_t = motion.mover_t[start:end + 1].copy()
    mover_r = motion.mover_r[start:end + 1].copy()
    mover_t[:, :2] -= mover_t[0, :2]
    local_r, root_t = cleanup.make_loop(local_r, root_t, LOOP_BLEND_FRAMES if aligned else max(8, len(local_r) // 6))
    data = ycd.ClipData(slot, motion.fps, local_r, root_t, ycd.default_bone_indices(skel, local_r), looped=True,
                        mover_t=mover_t, mover_r=mover_r, translation_indices=ycd.helper_translation_indices(skel),
                        tags=_foot_tags(strikes, start, end))
    turns = [turn_clip(skel, data, name.format(side), sign * rate, speed * share, sign * lean, spine_share)
             for name, rate, share, lean, spine_share in TURNS.get(slot, ())
             for side, sign in (("l", 1.0), ("r", -1.0))]
    return SlotResult(slot, data, strides, float(speed), aligned, turns)


def turn_clip(skel, straight, name, rate, speed, lean, spine_share):
    """The straight loop bent into a constant-rate turn: the mover yaws at `rate` deg/s (+ = left) while
    moving at `speed` m/s, the whole body leans `lean` degrees into the turn around the ground under the
    pelvis, and the spine gives back `spine_share` of it so the chest stays more upright (Rockstar's
    run_turn clips: pelvis ~20 deg, chest ~9 deg). Same frames and foot tags as the straight loop, so the
    game can phase-match the two."""
    frames = straight.local_r.shape[0]
    t = np.arange(frames) / straight.fps
    heading = np.radians(rate) * t
    zeros = np.zeros(frames)
    mover_r = rot.from_axis_angle(np.stack((zeros, zeros, heading), axis=-1))
    forward = np.stack((-np.sin(heading), np.cos(heading)), axis=-1)
    step = forward * (speed / straight.fps)
    step[0] = 0.0
    mover_t = np.concatenate((np.cumsum(step, axis=0), np.full((frames, 1), straight.mover_t[0, 2])), axis=1)

    # Positive roll about +Y tips the top towards +X (the right): a left turn (rate > 0) leans left.
    roll = np.radians(-lean)
    tilt = rot.from_axis_angle(np.array([0.0, roll, 0.0]))
    root = skel.index("SKEL_ROOT")
    local_r = straight.local_r.copy()
    local_r[:, root] = rot.normalize(rot.mul(tilt, local_r[:, root]))
    root_t = straight.root_t.copy()
    height = root_t[:, 2] - ground.GROUND_Z
    root_t[:, 0] += height * np.sin(roll)
    root_t[:, 2] = ground.GROUND_Z + height * np.cos(roll)

    if spine_share and skel.has("SKEL_Spine1"):
        spine = skel.index("SKEL_Spine1")
        world_r, _ = skel.fk(local_r)
        parent = world_r[:, skel.parents[spine]]
        back = rot.from_axis_angle(np.array([0.0, -roll * spine_share, 0.0]))
        local_r[:, spine] = rot.normalize(rot.mul(rot.inv(parent), rot.mul(back, rot.mul(parent, local_r[:, spine]))))

    # Keep each frame's foot clearance: the lean lifts one foot and sinks the other a little.
    before = ground.sole_points(skel, straight.local_r, straight.root_t)[..., 2].min(axis=(1, 2))
    after = ground.sole_points(skel, local_r, root_t)[..., 2].min(axis=(1, 2))
    root_t[:, 2] += before - after

    return dataclasses.replace(straight, name=name, local_r=local_r, root_t=root_t, mover_t=mover_t, mover_r=mover_r)


PREVIEW_SECONDS = 4.0


def _assigned(project, moveset):
    """{slot: project clip} for the slots this style fills."""
    out = {}
    for slot in SLOTS:
        clip_id = (moveset.get("slots") or {}).get(slot)
        clip = project.clip(clip_id) if clip_id else None
        if clip is not None:
            out[slot] = clip
    return out


def build_style(project, moveset, report=lambda *a, **k: None):
    """Every clip of the style: (slot results with their turns, transition clips)."""
    speeds = {**DEFAULT_SPEEDS, **{k: float(v) for k, v in (moveset.get("speeds") or {}).items() if v}}
    results = []
    for slot, clip in _assigned(project, moveset).items():
        report(len(results) / len(SLOTS), f"préparation de « {slot} »")
        results.append(build_slot(project, clip, slot, speeds.get(slot, 0.0)))
    loops = {r.slot: r.clip for r in results if r.slot != "idle"}
    idle = next((r.clip for r in results if r.slot == "idle"), None)
    return results, transitions.build(loops, idle)


def preview_names(project, moveset):
    """Clips the game would get from this style: each assigned slot with its turns, then the transitions."""
    slots = list(_assigned(project, moveset))
    names = []
    for slot in slots:
        names.append(slot)
        names += [name.format(side) for name, *_ in TURNS.get(slot, ()) for side in "lr"]
    names += transitions.names(slots, "idle" in slots)
    return [DEMO] + names if names else names


DEMO = "parcours"
# The tour the demo preview chains, as in game: (clip, seconds; None plays a transition once).
# Steps whose clip the style lacks are skipped.
DEMO_STEPS = (("idle", 1.0), ("wstart_l_0", None), ("walk", 1.5), ("walktorun_left", None), ("run", 1.5),
              ("run_turn_l2", 1.5), ("run", 0.7), ("sprint", 1.5), ("sprint_turn_r", 1.2), ("sprint", 0.7),
              ("run", 1.0), ("runtowalk_left", None), ("walk", 1.0), ("wstop_l_0", None), ("idle", 1.0))
JOIN_SECONDS = 0.15


def preview(project, moveset, name):
    """A style clip as the game plays it, or DEMO: the style's clips chained like a short walk around.
    Loops repeat (PREVIEW_SECONDS alone), transitions play once, and the mover carries on from one
    cycle or clip to the next, so a turn draws its circle instead of snapping back."""
    results, extra = build_style(project, moveset)
    clips = {c.name: c for r in results for c in [r.clip] + (r.turns or [])}
    clips.update({c.name: c for c in extra})
    if name == DEMO:
        steps = [(clips[step], seconds) for step, seconds in DEMO_STEPS if step in clips]
    elif name in clips:
        steps = [(clips[name], PREVIEW_SECONDS if clips[name].looped else None)]
    else:
        raise ValueError(f"« {name} » n'est pas dans ce style")
    if not steps:
        raise ValueError("ce style n'a aucun clip à enchaîner")
    return _play(steps)


def _play(steps):
    """Chain (clip, seconds) steps into one motion: poses cross-fade over JOIN_SECONDS at each join,
    the mover is integrated step by step in the entity's own frame."""
    fps = steps[0][0].fps
    poses, roots, deltas_t, deltas_r = [], [], [], []
    for clip, seconds in steps:
        frames = clip.local_r.shape[0]
        if clip.looped:
            # The last frame of a loop is its first one again: a cycle is frames - 1 long.
            count = max(1, int(round(seconds * fps)))
            index = np.arange(count) % max(frames - 1, 1)
        else:
            index = np.arange(frames)
        if clip.mover_t is not None:
            # Step into each frame from the one before it; a wrap steps from frames - 2 into frames - 1.
            following = np.where(index + 1 < frames, index + 1, frames - 1)
            previous = following - 1
            back = rot.inv(clip.mover_r[previous])
            deltas_t.append(rot.apply(back, clip.mover_t[following] - clip.mover_t[previous]))
            deltas_r.append(rot.mul(back, clip.mover_r[following]))
        else:
            deltas_t.append(np.zeros((len(index), 3)))
            deltas_r.append(np.tile(rot.IDENTITY, (len(index), 1)))
        r, t = clip.local_r[index].copy(), clip.root_t[index].copy()
        if poses:
            join = min(len(index), int(round(JOIN_SECONDS * fps)))
            w = ((np.arange(join) + 1) / (join + 1))[:, None]
            r[:join] = rot.slerp(np.broadcast_to(poses[-1][-1], r[:join].shape), r[:join], np.broadcast_to(w, r[:join].shape[:-1]))
            t[:join] = roots[-1][-1] * (1 - w) + t[:join] * w
        poses.append(r)
        roots.append(t)

    local_r, root_t = np.concatenate(poses), np.concatenate(roots)
    step_t, step_r = np.concatenate(deltas_t), np.concatenate(deltas_r)
    mover_t = np.zeros((len(local_r), 3))
    mover_r = np.tile(rot.IDENTITY, (len(local_r), 1))
    for i in range(1, len(local_r)):
        mover_t[i] = mover_t[i - 1] + rot.apply(mover_r[i - 1], step_t[i])
        mover_r[i] = rot.normalize(rot.mul(mover_r[i - 1], step_r[i]))
    mover_t[:, 2] = next((c.mover_t[0, 2] for c, _ in steps if c.mover_t is not None), 0.0)
    return fps, local_r, root_t, mover_t, mover_r


def export(project, moveset, report=lambda *a, **k: None):
    """moveset: {name, dict, slots: {slot: clip_id}, speeds: {slot: m/s}}. Writes a ready-to-ensure resource."""
    skel = skeleton.load(project.settings["ped"])
    name = projects.slugify(moveset.get("name") or "gtaw_moveset", "gtaw_moveset")
    dict_name = projects.slugify(moveset.get("dict") or f"{name}@move", f"{name}@move")
    results, extra = build_style(project, moveset, report)
    if not results:
        raise ValueError("aucun clip n'est attribué à ce style")

    folder = project.folder / "out" / "movesets" / name
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "stream").mkdir(parents=True)
    xml_path = folder / f"{dict_name}.ycd.xml"
    clips = [r.clip for r in results] + [turn for r in results for turn in r.turns or []] + extra
    xml_path.write_text(ycd.build_xml(skel, clips), encoding="utf-8")
    report_text = ycd.compile_ycd(xml_path, folder / "stream" / f"{dict_name}.ycd")
    xml_path.unlink()

    fallback = FALLBACKS.get(project.settings["ped"], "move_m@multiplayer")
    (folder / "clip_sets.meta").write_text(_clip_sets_meta(name, dict_name, fallback), encoding="utf-8")
    (folder / "fxmanifest.lua").write_text(_fxmanifest(name), encoding="utf-8")
    (folder / "client.lua").write_text(_client_lua(name), encoding="utf-8")

    manifest = {
        "clipset": name,
        "dict": dict_name,
        "fallback": fallback,
        "folder": str(folder),
        "transitions": [clip.name for clip in extra],
        "bridge": report_text,
        "slots": [{"slot": r.slot, "frames": int(r.clip.local_r.shape[0]), "duration": (r.clip.local_r.shape[0] - 1) / r.clip.fps,
                   "strides": r.strides, "speed": r.speed, "tags": len(r.clip.tags or []), "aligned": r.aligned,
                   "turns": [turn.name for turn in r.turns or []]} for r in results],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _clip_sets_meta(name, dict_name, fallback):
    # Same shape as Rockstar's DLC clip_sets.xml entries for movement styles (move_m@bag, move_m@tool_belt).
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<fwClipSetManager>
  <clipSets>
    <Item type="fwClipSet" key="{name}">
      <fallbackId>{fallback}</fallbackId>
      <clipDictionaryName>{dict_name}</clipDictionaryName>
      <clipItems />
      <moveNetworkFlags />
    </Item>
  </clipSets>
  <clipDictionaryMetadatas>
    <Item key="{dict_name}">
      <streamingPolicy>SP_STREAMING</streamingPolicy>
      <memoryGroup>MG_PlayerMovement</memoryGroup>
      <streamingPriority>SP_Medium</streamingPriority>
    </Item>
  </clipDictionaryMetadatas>
</fwClipSetManager>
"""


def _fxmanifest(name):
    return f"""fx_version 'cerulean'
game 'gta5'
lua54 'yes'

description 'Style de déplacement {name} (anim-extract)'

files {{ 'clip_sets.meta' }}
data_file 'CLIP_SETS_FILE' 'clip_sets.meta'

client_script 'client.lua'
"""


def _client_lua(name):
    return f"""-- /{name} applique le style, /{name} off revient au style par défaut.
-- Dans ton gamemode : RequestAnimSet puis SetPedMovementClipset(ped, '{name}', 0.25).
RegisterCommand('{name}', function(_, args)
    local ped = PlayerPedId()
    if args[1] == 'off' then
        ResetPedMovementClipset(ped, 0.25)
        return
    end
    RequestAnimSet('{name}')
    local deadline = GetGameTimer() + 5000
    while not HasAnimSetLoaded('{name}') and GetGameTimer() < deadline do Wait(0) end
    if not HasAnimSetLoaded('{name}') then
        print('^1{name} : style introuvable (la ressource est-elle démarrée ?)^7')
        return
    end
    SetPedMovementClipset(ped, '{name}', 0.25)
end, false)
"""
