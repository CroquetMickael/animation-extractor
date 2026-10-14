"""Finger poses sampled from Rockstar clips (GVHMR has no fingers; MediaPipe rarely sees gloved hands).

Poses are stored as finger-bone local rotations so they slot straight into a clip:
  relaxed — move_m@generic/idle (median frame)
  fist    — melee@unarmed@streamed_core/ground_attack_0 (tightest frame per hand)
  open    — the model's bind pose
  loose   — halfway between relaxed and fist, computed on the fly
"""
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import rot, skeleton
from .paths import ASSETS, BRIDGE, load_config

POSES_FILE = ASSETS / "hand_poses.json"
SOURCES = {
    "relaxed": ("move_m@generic", "idle", "median"),
    "fist": ("melee@unarmed@streamed_core", "ground_attack_0", "max"),
}
CHOICES = ("relaxed", "loose", "fist", "open")
TRACK_ROTATION = 1


def finger_bones(skel, side):
    return [i for i, n in enumerate(skel.names) if n.startswith(f"SKEL_{side}_Finger")]


def build(ped="mp_m_freemode_01"):
    skel = skeleton.load(ped)
    gta = load_config()["gta_folder"]
    poses = {}
    for pose, (dictionary, clip, pick) in SOURCES.items():
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip.json"
            subprocess.run([str(BRIDGE), "dump-clip", "--gta", gta, "--dict", dictionary, "--clip", clip, "--out", str(out)],
                           check=True, capture_output=True)
            data = json.loads(out.read_text(encoding="utf-8"))
        poses[pose] = _sample(skel, data, pick)
    POSES_FILE.write_text(json.dumps(poses, indent=1), encoding="utf-8")
    return poses


def _sample(skel, data, pick):
    by_tag = {int(t): i for i, t in enumerate(skel.tags)}
    pose = {}
    for side in ("L", "R"):
        wanted = set(finger_bones(skel, side))
        tracks = {}
        for animation in data["animations"]:
            for track in animation["tracks"]:
                i = by_tag.get(track["bone"])
                if track["track"] == TRACK_ROTATION and i in wanted:
                    tracks[i] = np.asarray(track["values"], dtype=np.float64)
        if not tracks:
            continue
        frames = min(len(v) for v in tracks.values())
        curl = sum(_angle(tracks[i][:frames], skel.bind_r[i]) for i in tracks)
        frame = int(np.argmax(curl)) if pick == "max" else int(np.argsort(curl)[frames // 2])
        for i, values in tracks.items():
            pose[skel.names[i]] = [float(v) for v in rot.normalize(values[frame])]
    return pose


def _angle(q, reference):
    return 2.0 * np.arccos(np.clip(np.abs(np.sum(q * reference, axis=-1)), 0.0, 1.0))


def load():
    if not POSES_FILE.exists():
        return {}
    return json.loads(POSES_FILE.read_text(encoding="utf-8"))


def apply(skel, local_r, left, right):
    """Overwrite finger rotations with the chosen pose per hand."""
    poses = load()
    out = local_r.copy()
    for side, choice in (("L", left), ("R", right)):
        if choice not in CHOICES:
            continue
        for i in finger_bones(skel, side):
            out[:, i] = _pose_rotation(skel, poses, choice, skel.names[i], i)
    return out


def _pose_rotation(skel, poses, choice, name, index):
    bind = skel.bind_r[index]
    if choice == "open":
        return bind
    relaxed = np.asarray(poses.get("relaxed", {}).get(name, bind))
    fist = np.asarray(poses.get("fist", {}).get(name, bind))
    if choice == "relaxed":
        return relaxed
    if choice == "fist":
        return fist
    return rot.slerp(relaxed, fist, 0.5)
