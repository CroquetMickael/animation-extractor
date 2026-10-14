"""Clip dictionary XML (CodeWalker schema) + binary compile through gtabridge."""
import subprocess
from dataclasses import dataclass
from xml.sax.saxutils import escape

import numpy as np

from . import rot
from .paths import BRIDGE

TRACK_BONE_TRANSLATION = 0
TRACK_BONE_ROTATION = 1
TRACK_MOVER_TRANSLATION = 5
TRACK_MOVER_ROTATION = 6
MOVER_BONE_ID = 0
# Rockstar sets this on exactly the animations that carry mover tracks (checked on move_m@generic).
FLAG_HAS_MOVER = 16
FORMAT_VECTOR3 = 0
FORMAT_QUATERNION = 1

ROTATION_QUANTUM = 1.0e-4
TRANSLATION_QUANTUM = 1.0e-4
STATIC_EPSILON = 1.0e-6
# Same value Rockstar ships in most ped clips; the engine does not appear to read it.
ANIMATION_UNKNOWN_1C = "hash_32E47806"


@dataclass
class ClipData:
    name: str
    fps: float
    local_r: np.ndarray       # (T, B, 4)
    root_t: np.ndarray        # (T, 3)
    bone_indices: list        # skeleton indices written as rotation tracks
    looped: bool = False
    mover_t: np.ndarray = None  # (T, 3) entity path, see root_motion
    translation_indices: list = None  # non-root bones written with a constant bind-pose translation track
    tags: list = None  # [{name, unk, attrs: [(name, type, value)], start, end}] phases 0..1, see moveset
    mover_r: np.ndarray = None  # (T, 4)


def _float(v):
    return f"{float(v):.8g}"


def _channel_xml(values, quantum, indent):
    pad = " " * indent
    lo, hi = float(values.min()), float(values.max())
    if hi - lo < STATIC_EPSILON:
        return (f'{pad}<Item>\n{pad} <Type value="StaticFloat" />\n'
                f'{pad} <Value value="{_float((lo + hi) * 0.5)}" />\n{pad}</Item>\n')
    rows = []
    for start in range(0, len(values), 10):
        rows.append(f"{pad}  " + " ".join(_float(v) for v in values[start:start + 10]))
    body = "\n".join(rows)
    return (f'{pad}<Item>\n{pad} <Type value="QuantizeFloat" />\n'
            f'{pad} <Quantum value="{_float(quantum)}" />\n{pad} <Offset value="{_float(lo)}" />\n'
            f'{pad} <Values>\n{body}\n{pad} </Values>\n{pad}</Item>\n')


def _rotation_channels(q, indent):
    """Three stored components + one reconstructed (CachedQuaternion1, QuatIndex = dropped component)."""
    q = rot.make_continuous(rot.normalize(q))
    dropped = int(np.argmax(np.abs(q).mean(axis=0)))
    q = np.where(q[:, dropped:dropped + 1] < 0, -q, q)
    kept = [c for c in range(4) if c != dropped]
    pad = " " * indent
    xml = "".join(_channel_xml(q[:, c], ROTATION_QUANTUM, indent) for c in kept)
    xml += f'{pad}<Item>\n{pad} <Type value="CachedQuaternion1" />\n{pad} <QuatIndex value="{dropped}" />\n{pad}</Item>\n'
    return xml


def _translation_channels(v, indent):
    return "".join(_channel_xml(v[:, c], TRANSLATION_QUANTUM, indent) for c in range(3))


def _animation_xml(skel, clip, anim_hash):
    frames = clip.local_r.shape[0]
    duration = (frames - 1) / clip.fps
    root = skel.index("SKEL_ROOT")
    # (bone id, track, value format, per-frame data)
    tracks = [(int(skel.tags[root]), TRACK_BONE_TRANSLATION, FORMAT_VECTOR3, clip.root_t)]
    tracks += [(int(skel.tags[i]), TRACK_BONE_ROTATION, FORMAT_QUATERNION, clip.local_r[:, i]) for i in clip.bone_indices]
    frames_count = clip.local_r.shape[0]
    for i in clip.translation_indices or []:
        tracks.append((int(skel.tags[i]), TRACK_BONE_TRANSLATION, FORMAT_VECTOR3, np.broadcast_to(skel.bind_t[i], (frames_count, 3))))
    has_mover = clip.mover_t is not None
    if has_mover:
        tracks += [(MOVER_BONE_ID, TRACK_MOVER_TRANSLATION, FORMAT_VECTOR3, clip.mover_t),
                   (MOVER_BONE_ID, TRACK_MOVER_ROTATION, FORMAT_QUATERNION, clip.mover_r)]
    flags = FLAG_HAS_MOVER if has_mover else 0
    # The game looks tracks up by binary search: every Rockstar clip lists them sorted by (track, bone id).
    # Unsorted, most bones are simply not found (only the left leg played on a re-encoded Rockstar walk).
    tracks.sort(key=lambda entry: (entry[1], entry[0]))

    out = [f"  <Item>\n   <Hash>{anim_hash}</Hash>\n   <Unknown10 value=\"{flags}\" />\n",
           f"   <FrameCount value=\"{frames}\" />\n   <SequenceFrameLimit value=\"{frames}\" />\n",
           f"   <Duration value=\"{_float(duration)}\" />\n   <Unknown1C>{ANIMATION_UNKNOWN_1C}</Unknown1C>\n",
           "   <BoneIds>\n"]
    for bone_id, track, fmt, _ in tracks:
        out.append(f"    <Item>\n     <BoneId value=\"{bone_id}\" />\n     <Track value=\"{track}\" />\n"
                   f"     <Unk0 value=\"{fmt}\" />\n    </Item>\n")
    out.append("   </BoneIds>\n   <Sequences>\n    <Item>\n")
    out.append(f"     <Hash>{anim_hash}_seq0</Hash>\n     <FrameCount value=\"{frames}\" />\n     <SequenceData>\n")
    for _, _, fmt, data in tracks:
        out.append("      <Item>\n       <Channels>\n")
        if fmt == FORMAT_VECTOR3:
            out.append(_translation_channels(data, 8))
        else:
            out.append(_rotation_channels(data, 8))
        out.append("       </Channels>\n      </Item>\n")
    out.append("     </SequenceData>\n    </Item>\n   </Sequences>\n  </Item>\n")
    return "".join(out)


def _tags_xml(tags):
    if not tags:
        return "   <Tags />\n"
    out = ["   <Tags>\n"]
    for tag in tags:
        out.append(f"    <Item>\n     <NameHash>{tag['name']}</NameHash>\n     <UnkHash>{tag['unk']}</UnkHash>\n     <Attributes>\n")
        for name, kind, value in tag["attrs"]:
            body = f"       <Value>{value}</Value>\n" if kind == "HashString" else f"       <Value value=\"{value}\" />\n"
            out.append(f"      <Item>\n       <NameHash>{name}</NameHash>\n       <Type value=\"{kind}\" />\n{body}      </Item>\n")
        out.append(f"     </Attributes>\n     <StartPhase value=\"{_float(tag['start'])}\" />\n"
                   f"     <EndPhase value=\"{_float(tag['end'])}\" />\n    </Item>\n")
    out.append("   </Tags>\n")
    return "".join(out)


def _clip_xml(clip, anim_hash):
    frames = clip.local_r.shape[0]
    duration = (frames - 1) / clip.fps
    name = escape(clip.name)
    return (f"  <Item>\n   <Hash>{name}</Hash>\n   <Name>pack:/{name}.clip</Name>\n"
            f"   <Type value=\"Animation\" />\n   <Unknown30 value=\"0\" />\n{_tags_xml(clip.tags)}   <Properties />\n"
            f"   <AnimationHash>{anim_hash}</AnimationHash>\n   <StartTime value=\"0\" />\n"
            f"   <EndTime value=\"{_float(duration)}\" />\n   <Rate value=\"1\" />\n  </Item>\n")


def build_xml(skel, clips):
    anim_hashes = [f"{clip.name}_anim" for clip in clips]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<ClipDictionary>\n <Clips>\n']
    parts += [_clip_xml(clip, h) for clip, h in zip(clips, anim_hashes)]
    parts.append(" </Clips>\n <Animations>\n")
    parts += [_animation_xml(skel, clip, h) for clip, h in zip(clips, anim_hashes)]
    parts.append(" </Animations>\n</ClipDictionary>\n")
    return "".join(parts)


def compile_ycd(xml_path, ycd_path):
    result = subprocess.run([str(BRIDGE), "xml-to-ycd", "--in", str(xml_path), "--out", str(ycd_path)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gtabridge xml-to-ycd failed:\n{result.stderr or result.stdout}")
    return result.stdout.strip()


# Helper bones Rockstar writes in every body clip (checked on move_m@generic/walk), as constant bind-pose
# locals. Bones a clip leaves out are not reset by GTA: they keep the previous animation's values, so a
# clip started mid-run let the run steer the leg/hand IK targets and the result no longer matched.
IK_ROTATION_BONES = ("IK_Head", "IK_Root", "IK_L_Hand", "IK_R_Hand", "PH_L_Hand", "PH_R_Hand")
IK_TRANSLATION_BONES = ("IK_L_Foot", "IK_R_Foot", "IK_L_Hand", "IK_R_Hand", "PH_L_Hand", "PH_R_Hand")


def default_bone_indices(skel, local_r):
    """Every SKEL_ body bone (fingers and toes included, animated or not) plus the IK/PH helpers."""
    indices = [i for i, name in enumerate(skel.names) if name.startswith("SKEL_")]
    indices += [skel.index(name) for name in IK_ROTATION_BONES if skel.has(name)]
    return indices


def helper_translation_indices(skel):
    return [skel.index(name) for name in IK_TRANSLATION_BONES if skel.has(name)]
