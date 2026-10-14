"""anim-extract command line.

  python -m animx ui [--port 8765]                 open the editor
  python -m animx doctor                           check the installation
  python -m animx peds                             (re)extract freemode peds from GTA V
  python -m animx handposes                        (re)build finger poses from Rockstar clips
  python -m animx extract VIDEO --dict NAME [--clip NAME] [--engine mediapipe|gvhmr] [--loop] [--root-motion]
  python -m animx export PROJECT_ID                rebuild a project's .ycd
"""
import argparse
import json
import subprocess
import sys
import webbrowser
from pathlib import Path

from .paths import BRIDGE, PEDS, load_config


def cmd_ui(args):
    import uvicorn
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        webbrowser.open(url)
    print(f"anim-extract editor: {url}")
    uvicorn.run("animx.server:app", host="127.0.0.1", port=args.port, log_level="warning")


def cmd_doctor(_args):
    from . import system
    print(json.dumps(system.status(), indent=2, ensure_ascii=False))


def cmd_peds(_args):
    gta = load_config()["gta_folder"]
    for ped in ("mp_m_freemode_01", "mp_f_freemode_01"):
        subprocess.run([str(BRIDGE), "export-ped", "--gta", gta, "--ped", ped, "--out", str(PEDS)], check=True)


def cmd_handposes(_args):
    from . import handposes
    print({pose: len(bones) for pose, bones in handposes.build().items()})


def cmd_extract(args):
    from . import pipeline, project
    from .capture import run_capture

    p = project.create(Path(args.video), args.dict)
    clip = p.clips()[0]
    clip.update({"name": args.clip or args.dict, "loop": args.loop, "motion": "mover" if args.root_motion else "inplace"})
    settings = {**p.settings, "engine": args.engine, "ped": args.ped}
    p.update({"clips": [clip], "settings": settings, "dict_name": args.dict})

    def report(progress=None, message=None):
        if message:
            print(f"[{(progress or 0) * 100:5.1f}%] {message}", flush=True)

    run_capture(p, args.engine, report)
    manifest = pipeline.export(p)
    print(json.dumps(manifest, indent=2))
    print(f"projet {p.id} — rouvrable dans l'éditeur")


def cmd_export(args):
    from . import pipeline, project
    p = project.load(args.project)
    if p is None:
        sys.exit(f"projet inconnu: {args.project}")
    print(json.dumps(pipeline.export(p), indent=2))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="animx")
    sub = parser.add_subparsers(dest="command", required=True)

    ui = sub.add_parser("ui")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true")
    ui.set_defaults(fn=cmd_ui)

    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sub.add_parser("peds").set_defaults(fn=cmd_peds)
    sub.add_parser("handposes").set_defaults(fn=cmd_handposes)

    extract = sub.add_parser("extract")
    extract.add_argument("video")
    extract.add_argument("--dict", required=True)
    extract.add_argument("--clip")
    extract.add_argument("--engine", choices=["mediapipe", "gvhmr"], default="mediapipe")
    extract.add_argument("--ped", default="mp_m_freemode_01")
    extract.add_argument("--loop", action="store_true")
    extract.add_argument("--root-motion", action="store_true")
    extract.set_defaults(fn=cmd_extract)

    export = sub.add_parser("export")
    export.add_argument("project")
    export.set_defaults(fn=cmd_export)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
