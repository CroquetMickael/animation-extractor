"""Capture -> GTA motion -> per-clip processing -> .ycd."""
import json
from dataclasses import dataclass

import numpy as np

from . import cleanup, edits, gait, ground, handposes, rig, root_motion, rot, skeleton, transform, ycd
from .solve import landmarks


@dataclass
class Motion:
    fps: float
    local_r: np.ndarray   # (T, B, 4)
    root_t: np.ndarray    # (T, 3)
    tracked_z: np.ndarray = None  # (T,) engine pelvis height when it has one (GVHMR)
    jump_z: np.ndarray = None     # (T,) flight height of real jumps, see ground.jump_heights
    camera: dict = None           # video camera relative to the pelvis: offset/forward/up (T, 3) + fov
    mover_t: np.ndarray = None    # (T, 3) entity path when the clip carries a mover track
    mover_r: np.ndarray = None    # (T, 4) entity heading
    travel: dict = None           # gait analysis + measured/applied speed for mover clips


_cache = {}


def reference_pose(ped, engine, capture=None):
    skel = skeleton.load(ped)
    if engine == "gvhmr" and capture is not None:
        from .solve import smpl
        return rig.build_reference_pose(skel, smpl.reference_directions(capture))
    return rig.build_reference_pose(skel, rig.CANONICAL_DIRECTIONS)


def solve_project(project):
    """Whole-video motion for the project's active engine (cached until capture/settings change)."""
    settings = project.settings
    engine = settings["engine"]
    path = project.capture_path(engine)
    if not path.exists():
        raise FileNotFoundError(f"no {engine} capture yet")

    key = (project.id, engine, path.stat().st_mtime, settings["ped"], settings["head_pitch"], settings["upright"], settings["upright_gvhmr"], settings["hand_placement"])
    if key in _cache:
        return _cache[key]

    skel = skeleton.load(settings["ped"])
    capture = dict(np.load(path, allow_pickle=False))
    reference = reference_pose(settings["ped"], engine, capture)

    if engine == "gvhmr":
        from .solve import smpl
        driven, root_world, camera, source_joints = smpl.solve(skel, reference, capture, upright=settings["upright_gvhmr"])
    else:
        positions = landmarks.load_positions(capture, upright=settings["upright"])
        driven = landmarks.solve(skel, reference, positions, head_pitch_deg=settings["head_pitch"])
        camera = landmarks.camera_track(capture, upright=settings["upright"])
        root_world = None
        source_joints = None

    yaw = landmarks.heading_correction(driven)
    driven = {name: rot.mul(yaw, q) for name, q in driven.items()}
    if camera is not None:
        camera = {**camera, **{k: rot.apply(yaw, camera[k]) for k in ("offset", "forward", "up")}}
    local_r = rig.drive(skel, reference, driven)
    if source_joints is not None and settings["hand_placement"]:
        from .solve import arms
        local_r = arms.place_hands(skel, local_r, rot.apply(yaw, source_joints))

    frames = local_r.shape[0]
    root_t = np.zeros((frames, 3))
    tracked_z = jump_z = None
    fps = float(capture["fps"])
    if root_world is not None:
        root_t = rot.apply(yaw, root_world)
        tracked_z = root_t[:, 2].copy()
        jump_z = ground.jump_heights(skel, local_r, root_t, fps)
    # Provisional height for whole-video views; each clip re-grounds after its own processing.
    root_t[:, 2] = ground.root_heights(skel, local_r, root_t[:, :2], settings["ground"], tracked_z, jump_z)

    motion = Motion(fps, local_r, root_t, tracked_z, jump_z, camera)
    _cache.clear()
    _cache[key] = motion
    return motion


def clip_motion(project, clip, apply_edits=True):
    settings = project.settings
    skel = skeleton.load(settings["ped"])
    motion = solve_project(project)

    start = int(np.clip(clip["start"], 0, len(motion.local_r) - 1))
    end = int(np.clip(clip["end"], start + 1, len(motion.local_r) - 1))
    local_r = motion.local_r[start:end + 1].copy()
    root_t = motion.root_t[start:end + 1].copy()
    tracked_z = None if motion.tracked_z is None else motion.tracked_z[start:end + 1].copy()
    jump_z = None if motion.jump_z is None else motion.jump_z[start:end + 1].copy()
    root = skel.index("SKEL_ROOT")
    speed = float(clip.get("speed", 1.0))

    ground_mode = clip.get("ground") or settings["ground"]

    def regrounded(rotations, translations, tracked, jump):
        out = translations.copy()
        out[:, 2] = ground.root_heights(skel, rotations, out[:, :2], ground_mode, tracked, jump)
        return out
    body = [i for i, n in enumerate(skel.names) if n.startswith("SKEL_")]

    camera = None
    if motion.camera is not None:
        camera = {k: np.asarray(motion.camera[k])[start:end + 1].copy() for k in ("offset", "forward", "up")}

    # Mirroring comes before anything reads the feet, so grounding, pinning and the mover follow it.
    if clip.get("mirror"):
        local_r, root_t = transform.mirror(skel, local_r, root_t)
        if camera is not None:
            camera = {k: transform.mirror_vectors(v) for k, v in camera.items()}

    if clip.get("lock_heading"):
        turn = rot.inv(rot.yaw_only(local_r[:, root]))
        local_r = cleanup.lock_heading(local_r, root)
    else:
        turn = np.broadcast_to(rot.inv(rot.yaw_only(local_r[0, root])), (len(local_r), 4))
        local_r[:, root] = rot.mul(turn, local_r[:, root])
        root_t = rot.apply(turn, root_t)
    if camera is not None:
        camera = {k: rot.apply(turn, v) for k, v in camera.items()}

    displacement = clip.get("motion", "inplace")
    if displacement == "inplace":
        root_t[:, :2] = 0.0
    else:
        root_t[:, :2] -= root_t[0, :2]

    local_r = cleanup.smooth_rotations(local_r, settings["smoothing"], body)
    root_t = cleanup.smooth_vectors(root_t, settings["root_smoothing"])
    if tracked_z is not None:
        tracked_z = cleanup.smooth_vectors(tracked_z[:, None], settings["root_smoothing"])[:, 0]
    # Smoothing bends the legs differently, so the feet must be re-seated before locking them.
    root_t = regrounded(local_r, root_t, tracked_z, jump_z)
    if displacement != "inplace" and clip.get("foot_driven", True):
        root_t = root_motion.pin_to_feet(skel, local_r, root_t, motion.fps)

    if clip.get("foot_lock", True):
        local_r = cleanup.lock_feet(skel, local_r, root_t, motion.fps)

    # Keys are placed on the frames the editor shows, i.e. after the speed change.
    local_r, root_t = cleanup.resample(local_r, root_t, speed)
    if tracked_z is not None:
        tracked_z = cleanup.resample_scalar(tracked_z, speed)
        jump_z = cleanup.resample_scalar(jump_z, speed)
    # Reversed only once the travel is known: foot pinning carries momentum forward in time, so
    # running it on a reversed clip would yield a different path instead of the same path backwards.
    if clip.get("reverse"):
        local_r, root_t = local_r[::-1].copy(), root_t[::-1].copy()
        if tracked_z is not None:
            tracked_z, jump_z = tracked_z[::-1].copy(), jump_z[::-1].copy()
        if camera is not None:
            camera = {k: v[::-1].copy() for k, v in camera.items()}
    # Neither engine tracks fingers reliably; a pose per hand beats the model's splayed bind pose.
    local_r = handposes.apply(skel, local_r, clip.get("hand_left", "relaxed"), clip.get("hand_right", "relaxed"))

    clip_keys = []
    if apply_edits:
        project_edits = project.edits()
        local_r = edits.apply_calibration(skel, local_r, project_edits.get("calibration"))
        clip_keys = project_edits.get("keys", {}).get(clip["id"], [])
        local_r = edits.apply_keys(skel, local_r, clip_keys)

    mover_t = mover_r = travel = None
    if displacement in ("mover", "mover_turn"):
        mirrored = bool(clip.get("mirror"))
        travel = _travel_plan(skel, local_r, root_t, motion.fps, clip.get("travel", "auto"), mirrored)
        lateral_scale, lateral_distance = _lateral_setting(clip.get("lateral", "measured"))
        # The custom distance is set on the source clip; the mirror flips it like everything else.
        if mirrored and lateral_distance is not None:
            lateral_distance = -lateral_distance
        local_r, root_t, mover_t, mover_r = root_motion.extract(local_r, root_t, root, motion.fps, displacement == "mover_turn",
                                                                travel["applied_speed"] if travel["retimed"] else None,
                                                                lateral_scale, lateral_distance)

    # The body is entity-relative by now, so a loop blends the pose without dragging the path back.
    if clip.get("loop"):
        local_r, root_t = cleanup.make_loop(local_r, root_t, clip.get("loop_blend", 8))

    # Last word on height: every step above (IK, edits, loop blend) moves the feet a little.
    root_t = regrounded(local_r, root_t, tracked_z, jump_z)
    if clip.get("plant_feet"):
        local_r = cleanup.plant_feet(skel, local_r, root_t, motion.fps)
    root_t = edits.apply_root_keys(root_t, clip_keys)
    local_r = edits.apply_move_keys(skel, local_r, root_t, clip_keys)
    if camera is not None:
        camera = {k: np.stack([cleanup.resample_scalar(v[:, c], speed) for c in range(3)], axis=1) for k, v in camera.items()}
        camera["fov"] = motion.camera["fov"]
    return Motion(motion.fps, local_r, root_t, camera=camera, mover_t=mover_t, mover_r=mover_r, travel=travel)


def _travel_plan(skel, local_r, root_t, fps, travel, mirrored=False):
    """How fast the mover should go: "feet" keeps what the feet measured, a number forces that speed,
    "auto" lifts it to the gait's expected speed when the feet clearly under-report (in-place source,
    running toward the camera)."""
    analysis = gait.analyze(skel, local_r, fps)
    measured = root_motion.measured_speed(root_t, fps)
    lateral = root_motion.lateral_offset(root_t, local_r[:, skel.index("SKEL_ROOT")], fps)
    # Reported in the source clip's orientation, the frame the custom distance is expressed in.
    if mirrored:
        lateral = -lateral
    plan = {"analysis": analysis, "measured_speed": round(measured, 2), "applied_speed": round(measured, 2), "retimed": False,
            "mode": travel, "measured_lateral": round(lateral, 2)}
    if isinstance(travel, (int, float)) and travel > 0:
        plan.update(applied_speed=float(travel), retimed=True)
    elif travel == "auto" and analysis and measured < analysis["expected_speed"] * 0.8:
        plan.update(applied_speed=analysis["expected_speed"], retimed=True)
    return plan


def _lateral_setting(lateral):
    """Clip "lateral": "measured" | "none" | {"scale": k} | {"distance": metres}. Returns (scale, distance)."""
    if lateral == "none":
        return 0.0, None
    if isinstance(lateral, dict) and "distance" in lateral:
        return 1.0, float(lateral["distance"])
    if isinstance(lateral, dict) and "scale" in lateral:
        return float(lateral["scale"]), None
    return 1.0, None


def export(project, out_dir=None):
    settings = project.settings
    skel = skeleton.load(settings["ped"])
    out_dir = out_dir or (project.folder / "out")
    out_dir.mkdir(parents=True, exist_ok=True)

    clips = []
    for clip in project.clips():
        motion = clip_motion(project, clip)
        bones = ycd.default_bone_indices(skel, motion.local_r)
        clips.append(ycd.ClipData(clip["name"], motion.fps, motion.local_r, motion.root_t, bones, looped=clip.get("loop", False),
                                  mover_t=motion.mover_t, mover_r=motion.mover_r,
                                  translation_indices=ycd.helper_translation_indices(skel)))

    dict_name = project.data["dict_name"]
    xml_path = out_dir / f"{dict_name}.ycd.xml"
    ycd_path = out_dir / f"{dict_name}.ycd"
    xml_path.write_text(ycd.build_xml(skel, clips), encoding="utf-8")
    report = ycd.compile_ycd(xml_path, ycd_path)
    manifest = {
        "dict": dict_name,
        "ycd": str(ycd_path),
        "clips": [{"name": c.name, "frames": int(c.local_r.shape[0]), "duration": (c.local_r.shape[0] - 1) / c.fps, "loop": c.looped,
                   "mover": c.mover_t is not None,
                   "distance": 0.0 if c.mover_t is None else float(np.linalg.norm(c.mover_t[-1, :2] - c.mover_t[0, :2]))} for c in clips],
        "bridge": report,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
