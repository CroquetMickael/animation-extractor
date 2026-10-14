import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PEDS = ASSETS / "peds"
MODELS = ASSETS / "models"
PROJECTS = ROOT / "projects"
BRIDGE = ROOT / "bridge" / "bin" / "Release" / "net8.0" / "gtabridge.exe"
GVHMR = ROOT / "third_party" / "GVHMR"
SHIMS = ROOT / "third_party" / "shims"
SMPLX_DIR = GVHMR / "inputs" / "checkpoints" / "body_models" / "smplx"
CONFIG = ROOT / "config.json"

DEFAULT_CONFIG = {
    "gta_folder": "D:\\GTAV",
    "default_ped": "mp_m_freemode_01",
}


def load_config():
    if not CONFIG.exists():
        return dict(DEFAULT_CONFIG)
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    return {**DEFAULT_CONFIG, **data}


def save_config(config):
    CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")
