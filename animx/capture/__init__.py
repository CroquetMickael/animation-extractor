"""Capture engines. Each writes the project's capture_<engine>.npz."""
import os
import subprocess
import sys

from ..paths import GVHMR, ROOT, SHIMS


def run_capture(project, engine, report):
    if engine == "mediapipe":
        from . import mediapipe_capture

        def progress(i, total):
            report(i / max(total, 1), f"image {i}/{total}")

        report(0.0, "analyse du corps image par image")
        mediapipe_capture.run(project.video, project.capture_path("mediapipe"), progress=progress)
        return
    if engine == "gvhmr":
        _run_gvhmr(project, report)
        return
    raise ValueError(f"unknown engine {engine}")


def _run_gvhmr(project, report):
    from .. import system

    missing = system.gvhmr_missing()
    if missing:
        raise RuntimeError("GVHMR indisponible : " + "; ".join(missing))

    # MediaPipe also runs: the editor's video overlay and the hand pose come from it.
    if not project.has_capture("mediapipe"):
        from . import mediapipe_capture

        def pre_progress(i, total):
            report(0.2 * i / max(total, 1), f"pré-analyse MediaPipe : image {i}/{total}")

        report(0.0, "pré-analyse MediaPipe")
        mediapipe_capture.run(project.video, project.capture_path("mediapipe"), with_hands=True, progress=pre_progress)

    def scaled(value, message):
        report(0.2 + 0.8 * value, message)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SHIMS), str(GVHMR), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    command = [
        sys.executable, "-u", str(ROOT / "animx" / "capture" / "gvhmr_runner.py"),
        "--video", str(project.video),
        "--out", str(project.capture_path("gvhmr")),
        "--workdir", str(project.folder / "gvhmr_work"),
        "--fps", str(project.data.get("fps", 30.0)),
    ]
    if project.settings.get("static_camera", True):
        command.append("--static-cam")

    process = subprocess.Popen(command, cwd=GVHMR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    tail = []
    for line in process.stdout:
        line = line.rstrip()
        if line.startswith("PROGRESS "):
            _, value, *message = line.split(" ")
            scaled(float(value), " ".join(message))
        else:
            tail = (tail + [line])[-40:]
    if process.wait() != 0:
        raise RuntimeError("GVHMR a échoué :\n" + "\n".join(tail))
