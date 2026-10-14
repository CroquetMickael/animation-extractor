"""Environment checks shown in the editor and by `animx doctor`."""
from pathlib import Path

from .paths import BRIDGE, GVHMR, MODELS, PEDS, SMPLX_DIR, load_config

GVHMR_CHECKPOINTS = [
    "gvhmr/gvhmr_siga24_release.ckpt",
    "hmr2/epoch=10-step=25000.ckpt",
    "vitpose/vitpose-h-multi-coco.pth",
    "yolo/yolov8x.pt",
]


def gvhmr_missing():
    missing = []
    for rel in GVHMR_CHECKPOINTS:
        if not (GVHMR / "inputs" / "checkpoints" / rel).exists():
            missing.append(f"poids manquant : {rel}")
    if not (SMPLX_DIR / "SMPLX_NEUTRAL.npz").exists():
        missing.append(f"modèle SMPL-X manquant : déposer SMPLX_NEUTRAL.npz dans {SMPLX_DIR}")
    return missing


def status():
    config = load_config()
    try:
        import torch
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:
        gpu = None
    peds = sorted(p.name[:-4] for p in PEDS.glob("*.glb")) if PEDS.exists() else []
    return {
        "gta_folder": config["gta_folder"],
        "gta_ok": Path(config["gta_folder"], "GTA5.exe").exists(),
        "bridge_ok": BRIDGE.exists(),
        "peds": peds,
        "gpu": gpu,
        "engines": {
            "mediapipe": {"ok": (MODELS / "pose_landmarker_heavy.task").exists(), "missing": []},
            "gvhmr": {"ok": not gvhmr_missing(), "missing": gvhmr_missing()},
        },
    }
