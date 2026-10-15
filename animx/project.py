"""On-disk project: a source video, its captures, clip ranges, settings and manual edits."""
import json
import re
import shutil
import time
import uuid
from pathlib import Path

import cv2

from .paths import PROJECTS

CLIP_DEFAULTS = {
    "loop": False,
    "loop_blend": 8,
    "motion": "inplace",
    "foot_driven": True,
    "travel": "auto",
    "lateral": "measured",
    "reverse": False,
    "mirror": False,
    "lock_heading": False,
    "foot_lock": True,
    "plant_feet": False,
    "speed": 1.0,
    "hand_left": "relaxed",
    "hand_right": "relaxed",
    "ground": None,
}

SETTINGS_DEFAULTS = {
    "engine": "mediapipe",
    "ped": "mp_m_freemode_01",
    "smoothing": 1.0,
    "root_smoothing": 1.5,
    "head_pitch": 12.0,
    "ground": "planted",
    "upright": True,
    # GVHMR estimates gravity itself; forcing the median spine vertical tilted short leaning clips by ~25°.
    "upright_gvhmr": False,
    "hand_placement": True,
}


def slugify(text, fallback="clip"):
    slug = re.sub(r"[^a-z0-9_@]+", "_", text.lower()).strip("_")
    return slug or fallback


def _unique(name, taken):
    """Clip names are the in-game lookup keys of the dictionary, so they must never collide."""
    if name not in taken:
        return name
    n = 2
    while f"{name}_{n}" in taken:
        n += 1
    return f"{name}_{n}"


class Project:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.data = json.loads((self.folder / "project.json").read_text(encoding="utf-8"))

    @property
    def id(self):
        return self.data["id"]

    @property
    def video(self):
        return self.folder / self.data["video"]

    @property
    def settings(self):
        return {**SETTINGS_DEFAULTS, **self.data.get("settings", {})}

    def capture_path(self, engine=None):
        return self.folder / f"capture_{engine or self.settings['engine']}.npz"

    def has_capture(self, engine=None):
        return self.capture_path(engine).exists()

    def clips(self):
        return [{**CLIP_DEFAULTS, **clip} for clip in self.data.get("clips", [])]

    def clip(self, clip_id):
        for clip in self.clips():
            if clip["id"] == clip_id:
                return clip
        return None

    def edits(self):
        path = self.folder / "edits.json"
        if not path.exists():
            return {"calibration": {}, "keys": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_edits(self, edits):
        (self.folder / "edits.json").write_text(json.dumps(edits, indent=1), encoding="utf-8")

    def save(self):
        self.data["updated"] = time.time()
        (self.folder / "project.json").write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def update(self, patch):
        allowed = {"name", "dict_name", "settings", "clips", "movesets"}
        for key, value in patch.items():
            if key in allowed:
                self.data[key] = value
        taken = set()
        for clip in self.data.get("clips", []):
            if not clip.get("id"):
                clip["id"] = uuid.uuid4().hex[:8]
            clip["name"] = _unique(slugify(clip.get("name", ""), "clip"), taken)
            taken.add(clip["name"])
        self.data["dict_name"] = slugify(self.data.get("dict_name", ""), "anim_dict")
        for moveset in self.data.get("movesets", []):
            if not moveset.get("id"):
                moveset["id"] = uuid.uuid4().hex[:8]
            moveset["name"] = slugify(moveset.get("name", ""), "gtaw_moveset")
        self.save()

    def split_clip(self, clip_id, source_frame):
        """Cut a clip at an absolute video frame; manual keys follow the half they fall in."""
        clips = self.data.get("clips", [])
        index = next((i for i, c in enumerate(clips) if c["id"] == clip_id), None)
        if index is None:
            raise KeyError(clip_id)
        first = {**CLIP_DEFAULTS, **clips[index]}
        cut = int(source_frame)
        if not first["start"] + 2 <= cut <= first["end"] - 2:
            raise ValueError("le point de coupe doit être à l'intérieur du clip")

        second = {**first, "id": uuid.uuid4().hex[:8], "name": f"{first['name']}_b", "start": cut}
        first["end"] = cut
        clips[index] = first
        clips.insert(index + 1, second)

        edits = self.edits()
        speed = float(first.get("speed", 1.0))
        keep, move = [], []
        for key in edits.get("keys", {}).get(clip_id, []):
            source = first["start"] + key["frame"] * speed
            if source < cut:
                keep.append(key)
            else:
                move.append({**key, "frame": int(round((source - cut) / speed))})
        edits.setdefault("keys", {})[clip_id] = keep
        edits["keys"][second["id"]] = move
        self.save_edits(edits)
        self.update({"clips": clips})
        return second["id"]

    def merge_with_next(self, clip_id):
        clips = sorted(self.data.get("clips", []), key=lambda c: c["start"])
        index = next((i for i, c in enumerate(clips) if c["id"] == clip_id), None)
        if index is None or index + 1 >= len(clips):
            raise ValueError("aucun clip suivant à fusionner")
        first = {**CLIP_DEFAULTS, **clips[index]}
        second = {**CLIP_DEFAULTS, **clips[index + 1]}

        edits = self.edits()
        keys = edits.get("keys", {})
        speed_a, speed_b = float(first["speed"]), float(second["speed"])
        moved = [{**k, "frame": int(round((second["start"] + k["frame"] * speed_b - first["start"]) / speed_a))}
                 for k in keys.pop(second["id"], [])]
        keys[clip_id] = keys.get(clip_id, []) + moved
        edits["keys"] = keys
        self.save_edits(edits)

        first["end"] = max(first["end"], second["end"])
        clips[index] = first
        del clips[index + 1]
        self.update({"clips": clips})

    def summary(self):
        return {
            **self.data,
            "settings": self.settings,
            "clips": self.clips(),
            "captures": {e: self.has_capture(e) for e in ("mediapipe", "gvhmr")},
            "movesets": self.data.get("movesets", []),
        }


def create(video_source, name):
    project_id = uuid.uuid4().hex[:10]
    folder = PROJECTS / project_id
    folder.mkdir(parents=True)
    suffix = Path(video_source).suffix.lower() or ".mp4"
    target = folder / f"source{suffix}"
    shutil.copyfile(video_source, target)

    capture = cv2.VideoCapture(str(target))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()

    data = {
        "id": project_id,
        "name": name,
        "dict_name": slugify(name, "anim_dict"),
        "video": target.name,
        "fps": fps,
        "frames": frames,
        "size": [width, height],
        "created": time.time(),
        "settings": dict(SETTINGS_DEFAULTS),
        "clips": [{"id": uuid.uuid4().hex[:8], "name": "clip_01", "start": 0, "end": max(frames - 1, 0), **CLIP_DEFAULTS}],
    }
    (folder / "project.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return Project(folder)


def load(project_id):
    folder = PROJECTS / project_id
    if not (folder / "project.json").exists():
        return None
    return Project(folder)


def list_all():
    if not PROJECTS.exists():
        return []
    out = []
    for folder in PROJECTS.iterdir():
        if (folder / "project.json").exists():
            out.append(Project(folder).summary())
    return sorted(out, key=lambda p: p.get("updated", p.get("created", 0)), reverse=True)


def delete(project_id):
    folder = PROJECTS / project_id
    if not folder.exists() or folder.parent != PROJECTS:
        return
    # Dropping project.json first hides the project even if Windows still holds the video open
    # (a browser <video> streaming it); sweep_orphans() finishes the job on the next start.
    (folder / "project.json").unlink(missing_ok=True)
    shutil.rmtree(folder, ignore_errors=True)


def sweep_orphans():
    if not PROJECTS.exists():
        return
    for folder in PROJECTS.iterdir():
        if folder.is_dir() and not (folder / "project.json").exists():
            shutil.rmtree(folder, ignore_errors=True)
