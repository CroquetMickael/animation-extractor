"""Local editor backend: `python -m animx ui` serves the React app and this API on 127.0.0.1."""
import base64
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import jobs, moveset, pipeline, project as projects, segment, skeleton, system
from .paths import PEDS, ROOT

app = FastAPI(title="anim-extract")
UI_DIST = ROOT / "ui" / "dist"
projects.sweep_orphans()


def _project_or_404(project_id):
    p = projects.load(project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p


def _b64(array):
    return base64.b64encode(np.ascontiguousarray(array, dtype=np.float32).tobytes()).decode("ascii")


@app.get("/api/system")
def get_system():
    return system.status()


@app.get("/api/projects")
def list_projects():
    return projects.list_all()


@app.post("/api/projects")
async def create_project(video: UploadFile = File(...), name: str = Form(...)):
    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(video.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        created = projects.create(tmp_path, name)
    finally:
        tmp_path.unlink(missing_ok=True)
    return created.summary()


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    p = _project_or_404(project_id)
    summary = p.summary()
    summary["jobs"] = jobs.for_project(project_id)
    return summary


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, patch: dict):
    p = _project_or_404(project_id)
    p.update(patch)
    return p.summary()


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    _project_or_404(project_id)
    projects.delete(project_id)
    return {"ok": True}


@app.get("/api/projects/{project_id}/video")
def get_video(project_id: str):
    p = _project_or_404(project_id)
    return FileResponse(p.video)


@app.post("/api/projects/{project_id}/capture")
def start_capture(project_id: str, engine: str = "mediapipe"):
    p = _project_or_404(project_id)
    if engine not in ("mediapipe", "gvhmr"):
        raise HTTPException(400, "unknown engine")

    def work(report):
        from .capture import run_capture
        run_capture(p, engine, report)
        settings = p.settings
        settings["engine"] = engine
        p.update({"settings": settings})
        return {"engine": engine}

    return jobs.start(f"capture:{engine}", project_id, work)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


MEDIAPIPE_LINKS = [
    [11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24],
    [23, 25], [25, 27], [24, 26], [26, 28], [27, 29], [29, 31], [27, 31], [28, 30], [30, 32], [28, 32],
    [15, 19], [16, 20], [0, 7], [0, 8],
]
MEDIAPIPE_LEFT = [11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 7]


@app.get("/api/projects/{project_id}/overlay")
def get_overlay(project_id: str):
    """2D skeleton of what the active engine understood, drawn over the source video."""
    p = _project_or_404(project_id)
    gvhmr = p.capture_path("gvhmr")
    if p.settings["engine"] == "gvhmr" and gvhmr.exists():
        data = np.load(gvhmr)
        if "cam_joints" in data.files:
            return _gvhmr_overlay(p, data)
    path = p.capture_path("mediapipe")
    if not path.exists():
        return {"available": False}
    image = np.load(path)["pose_image"]
    return {"available": True, "source": "mediapipe", "frames": int(image.shape[0]), "points": int(image.shape[1]),
            "links": MEDIAPIPE_LINKS, "left": MEDIAPIPE_LEFT, "data": _b64(image)}


def _gvhmr_overlay(p, data):
    from .solve import smpl
    joints = data["cam_joints"].astype(np.float64)
    k = data["K"].astype(np.float64)
    width, height = p.data["size"]
    uv = joints @ k.T
    uv = uv[..., :2] / uv[..., 2:3]
    image = np.concatenate((uv[..., :1] / width, uv[..., 1:2] / height, np.ones(uv.shape[:-1] + (1,))), axis=-1)
    links = [[j, parent] for j, parent in enumerate(smpl.PARENTS) if parent >= 0]
    left = [smpl.L_HIP, smpl.L_KNEE, smpl.L_ANKLE, smpl.L_FOOT, smpl.L_COLLAR, smpl.L_SHOULDER, smpl.L_ELBOW, smpl.L_WRIST]
    return {"available": True, "source": "gvhmr", "frames": int(image.shape[0]), "points": int(image.shape[1]),
            "links": links, "left": left, "data": _b64(image)}


FULL_VIDEO = "__full__"


@app.get("/api/projects/{project_id}/motion")
def get_motion(project_id: str, clip: str, edits: bool = True):
    p = _project_or_404(project_id)
    if clip == FULL_VIDEO:
        # Whole-video preview for cutting: raw motion, no per-clip processing or keys.
        c = {"id": FULL_VIDEO, "start": 0, "end": p.data["frames"] - 1, "motion": "inplace", "foot_lock": False,
             "loop": False, "lock_heading": False, "speed": 1.0}
        edits = False
    else:
        c = p.clip(clip)
    if c is None:
        raise HTTPException(404, "clip not found")
    try:
        motion = pipeline.clip_motion(p, c, apply_edits=edits)
    except FileNotFoundError as ex:
        raise HTTPException(409, str(ex))
    skel = skeleton.load(p.settings["ped"])
    return {
        "fps": motion.fps,
        "frames": int(motion.local_r.shape[0]),
        "bones": skel.names,
        "rotations": _b64(motion.local_r),
        "root": _b64(motion.root_t),
        "mover": None if motion.mover_t is None else {"translation": _b64(motion.mover_t), "rotation": _b64(motion.mover_r)},
        "travel": motion.travel,
        "camera": None if motion.camera is None else {
            "offset": _b64(motion.camera["offset"]),
            "forward": _b64(motion.camera["forward"]),
            "up": _b64(motion.camera["up"]),
            "fov": motion.camera["fov"],
        },
    }


@app.post("/api/projects/{project_id}/clips/{clip_id}/split")
def split_clip(project_id: str, clip_id: str, at: int):
    p = _project_or_404(project_id)
    try:
        new_id = p.split_clip(clip_id, at)
    except KeyError:
        raise HTTPException(404, "clip not found")
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    return {"project": p.summary(), "new_clip": new_id}


@app.post("/api/projects/{project_id}/clips/{clip_id}/merge-next")
def merge_clip(project_id: str, clip_id: str):
    p = _project_or_404(project_id)
    try:
        p.merge_with_next(clip_id)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    return {"project": p.summary()}


@app.get("/api/projects/{project_id}/moveset/suggest")
def suggest_moveset(project_id: str):
    p = _project_or_404(project_id)
    try:
        return {"suggestions": moveset.suggest(p), "defaults": moveset.DEFAULT_SPEEDS,
                "fallback": moveset.FALLBACKS.get(p.settings["ped"], "move_m@multiplayer")}
    except FileNotFoundError as ex:
        raise HTTPException(409, str(ex))


def _moveset_or_404(p, moveset_id):
    target = next((m for m in p.data.get("movesets", []) if m.get("id") == moveset_id), None)
    if target is None:
        raise HTTPException(404, "moveset not found")
    return target


@app.get("/api/projects/{project_id}/movesets/{moveset_id}/preview-clips")
def moveset_preview_clips(project_id: str, moveset_id: str):
    p = _project_or_404(project_id)
    return {"clips": moveset.preview_names(p, _moveset_or_404(p, moveset_id))}


@app.get("/api/projects/{project_id}/movesets/{moveset_id}/preview")
def moveset_preview(project_id: str, moveset_id: str, clip: str):
    """Same payload as /motion, for a style clip as the game will play it (turns included)."""
    p = _project_or_404(project_id)
    target = _moveset_or_404(p, moveset_id)
    try:
        fps, local_r, root_t, mover_t, mover_r = moveset.preview(p, target, clip)
    except ValueError as ex:
        raise HTTPException(404, str(ex))
    except FileNotFoundError as ex:
        raise HTTPException(409, str(ex))
    skel = skeleton.load(p.settings["ped"])
    return {
        "fps": fps,
        "frames": int(local_r.shape[0]),
        "bones": skel.names,
        "rotations": _b64(local_r),
        "root": _b64(root_t),
        "mover": None if mover_t is None else {"translation": _b64(mover_t), "rotation": _b64(mover_r)},
        "travel": None,
        "camera": None,
    }


@app.post("/api/projects/{project_id}/movesets/{moveset_id}/export")
def export_moveset(project_id: str, moveset_id: str):
    p = _project_or_404(project_id)
    target = next((m for m in p.data.get("movesets", []) if m.get("id") == moveset_id), None)
    if target is None:
        raise HTTPException(404, "moveset not found")

    def work(report):
        return moveset.export(p, target, report)

    return jobs.start("moveset", project_id, work)


def _moveset_folder(project_id, moveset_id):
    """The generated resource folder of a moveset, 404 until it has been generated."""
    p = _project_or_404(project_id)
    target = next((m for m in p.data.get("movesets", []) if m.get("id") == moveset_id), None)
    if target is None:
        raise HTTPException(404, "moveset not found")
    name = projects.slugify(target.get("name") or "gtaw_moveset", "gtaw_moveset")
    source = p.folder / "out" / "movesets" / name
    if not source.exists():
        raise HTTPException(404, "not exported yet")
    return name, source


@app.post("/api/projects/{project_id}/movesets/{moveset_id}/install")
def install_moveset(project_id: str, moveset_id: str, body: dict):
    """Copy the generated resource folder into a server's resources directory."""
    name, source = _moveset_folder(project_id, moveset_id)
    destination_root = Path(body.get("resources_dir", ""))
    if not destination_root.is_dir():
        raise HTTPException(400, "resources folder does not exist")
    destination = destination_root / name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return {"ok": True, "path": str(destination)}


@app.get("/api/projects/{project_id}/movesets/{moveset_id}/download")
def download_moveset(project_id: str, moveset_id: str):
    """The generated resource as a zip holding one folder, ready to drop into resources/."""
    name, source = _moveset_folder(project_id, moveset_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, f"{name}/{path.relative_to(source).as_posix()}")
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


@app.get("/api/projects/{project_id}/cut-candidates")
def get_cut_candidates(project_id: str):
    p = _project_or_404(project_id)
    try:
        motion = pipeline.solve_project(p)
    except FileNotFoundError as ex:
        raise HTTPException(409, str(ex))
    skel = skeleton.load(p.settings["ped"])
    return {"fps": motion.fps, "candidates": segment.cut_candidates(skel, motion.local_r, motion.fps)}


@app.get("/api/projects/{project_id}/edits")
def get_edits(project_id: str):
    return _project_or_404(project_id).edits()


@app.put("/api/projects/{project_id}/edits")
def put_edits(project_id: str, body: dict):
    p = _project_or_404(project_id)
    p.save_edits({"calibration": body.get("calibration", {}), "keys": body.get("keys", {})})
    return {"ok": True}


@app.post("/api/projects/{project_id}/export")
def export_project(project_id: str):
    p = _project_or_404(project_id)

    def work(report):
        report(0.1, "construction des clips")
        return pipeline.export(p)

    return jobs.start("export", project_id, work)


@app.get("/api/projects/{project_id}/download")
def download(project_id: str):
    p = _project_or_404(project_id)
    path = p.folder / "out" / f"{p.data['dict_name']}.ycd"
    if not path.exists():
        raise HTTPException(404, "not exported yet")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.post("/api/projects/{project_id}/install")
def install_to_resource(project_id: str, body: dict):
    """Copy the exported .ycd into a FiveM resource's stream folder."""
    p = _project_or_404(project_id)
    source = p.folder / "out" / f"{p.data['dict_name']}.ycd"
    if not source.exists():
        raise HTTPException(404, "not exported yet")
    target_dir = Path(body.get("stream_dir", ""))
    if not target_dir.is_dir():
        raise HTTPException(400, "stream folder does not exist")
    shutil.copyfile(source, target_dir / source.name)
    return {"ok": True, "path": str(target_dir / source.name)}


@app.get("/api/peds/{ped}.glb")
def ped_glb(ped: str):
    path = PEDS / f"{ped}.glb"
    if not path.exists():
        raise HTTPException(404, "ped not exported")
    return FileResponse(path, media_type="model/gltf-binary")


@app.get("/api/peds/{ped}/skeleton")
def ped_skeleton(ped: str):
    path = PEDS / f"{ped}.skeleton.json"
    if not path.exists():
        raise HTTPException(404, "ped not exported")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
