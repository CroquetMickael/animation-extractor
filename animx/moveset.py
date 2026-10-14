"""Movement styles (movement clipsets): idle / walk / run / sprint that GTA chains on its own.

Modelled on Rockstar's move_m@hipster@a: the dictionary only provides idle, walk, run and sprint; starts,
stops, turns and slopes come from a fallback clipset (the freemode default, move_m@multiplayer or
move_f@multiplayer). Locomotion clips carry the same foot tags as Rockstar's (heel strikes, flagged
right/left, plus a window from each right strike to the next left one) so the game can phase-match
transitions between gaits.
"""
import json
import shutil
from dataclasses import dataclass

import numpy as np

from . import cleanup, gait, ground, pipeline, project as projects, skeleton, ycd
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


@dataclass
class SlotResult:
    slot: str
    clip: ycd.ClipData
    strides: int
    speed: float
    aligned: bool = True


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
    """First and last right heel strike, so the loop spans whole strides and starts/ends on the same foot."""
    rights = [t for side, t in strikes if side == "R"]
    if len(rights) < 2:
        return None
    return rights[0], rights[-1], len(rights) - 1


def _foot_tags(strikes, start, end):
    span = max(end - start, 1)
    inside = [(side, (t - start) / span) for side, t in strikes if start <= t <= end]
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
        data = ycd.ClipData(slot, motion.fps, motion.local_r, motion.root_t, ycd.default_bone_indices(skel, motion.local_r),
                            looped=True, translation_indices=ycd.helper_translation_indices(skel))
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
    return SlotResult(slot, data, strides, float(speed), aligned)


def export(project, moveset, report=lambda *a, **k: None):
    """moveset: {name, dict, slots: {slot: clip_id}, speeds: {slot: m/s}}. Writes a ready-to-ensure resource."""
    skel = skeleton.load(project.settings["ped"])
    name = projects.slugify(moveset.get("name") or "gtaw_moveset", "gtaw_moveset")
    dict_name = projects.slugify(moveset.get("dict") or f"{name}@move", f"{name}@move")
    speeds = {**DEFAULT_SPEEDS, **{k: float(v) for k, v in (moveset.get("speeds") or {}).items() if v}}

    results = []
    for slot in SLOTS:
        clip_id = (moveset.get("slots") or {}).get(slot)
        if not clip_id:
            continue
        clip = project.clip(clip_id)
        if clip is None:
            continue
        report(len(results) / len(SLOTS), f"préparation de « {slot} »")
        results.append(build_slot(project, clip, slot, speeds.get(slot, 0.0)))
    if not results:
        raise ValueError("aucun clip n'est attribué à ce style")

    folder = project.folder / "out" / "movesets" / name
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "stream").mkdir(parents=True)
    xml_path = folder / f"{dict_name}.ycd.xml"
    xml_path.write_text(ycd.build_xml(skel, [r.clip for r in results]), encoding="utf-8")
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
        "bridge": report_text,
        "slots": [{"slot": r.slot, "frames": int(r.clip.local_r.shape[0]), "duration": (r.clip.local_r.shape[0] - 1) / r.clip.fps,
                   "strides": r.strides, "speed": r.speed, "tags": len(r.clip.tags or []), "aligned": r.aligned} for r in results],
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
