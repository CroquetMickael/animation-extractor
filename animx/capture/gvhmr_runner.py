"""Runs GVHMR inference without its renderer (which needs a CUDA pytorch3d build).

Executed as a subprocess with cwd = third_party/GVHMR and PYTHONPATH = shims + GVHMR, so its heavy
imports stay out of the editor process. Prints `PROGRESS <0..1> <message>` lines for the job runner.
"""
import argparse
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import torch


def progress(value, message):
    print(f"PROGRESS {value:.3f} {message}", flush=True)


@contextmanager
def full_unpickling():
    """Ultralytics checkpoints pickle model classes, which torch>=2.6 refuses by default.
    Scoped to the YOLO load only (official ultralytics/assets release); every other
    checkpoint keeps the safe weights-only loader."""
    original = torch.load

    def load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original(*args, **kwargs)

    torch.load = load
    try:
        yield
    finally:
        torch.load = original


def build_cfg(video, workdir, static_cam):
    from hydra import compose, initialize_config_module
    from hmr4d.configs import register_store_gvhmr
    import hmr4d.model.gvhmr.gvhmr_pl_demo  # noqa: F401 — registers model/gvhmr/gvhmr_pl_demo in the config store

    with initialize_config_module(version_base="1.3", config_module="hmr4d.configs"):
        register_store_gvhmr()
        return compose(config_name="demo", overrides=[
            f"video_name={Path(video).stem}",
            f"static_cam={static_cam}",
            "verbose=False",
            "use_dpvo=False",
            f"output_root={Path(workdir).as_posix()}",
        ])


def copy_video(source, target):
    from hmr4d.utils.video_io_utils import get_video_lwh, get_video_reader, get_writer

    if Path(target).exists() and get_video_lwh(source)[0] == get_video_lwh(target)[0]:
        return
    reader = get_video_reader(source)
    writer = get_writer(target, fps=30, crf=17)
    for image in reader:
        writer.write_frame(image)
    writer.close()
    reader.close()


@torch.no_grad()
def preprocess(cfg):
    from hmr4d.utils.geo.hmr_cam import get_bbx_xys_from_xyxy
    from hmr4d.utils.preproc import Extractor, SimpleVO, Tracker, VitPoseExtractor

    paths = cfg.paths
    if not Path(paths.bbx).exists():
        progress(0.10, "suivi de la personne (YOLO)")
        with full_unpickling():
            tracker = Tracker()
        bbx_xyxy = tracker.get_one_track(cfg.video_path).float()
        bbx_xys = get_bbx_xys_from_xyxy(bbx_xyxy, base_enlarge=1.2).float()
        torch.save({"bbx_xyxy": bbx_xyxy, "bbx_xys": bbx_xys}, paths.bbx)
        del tracker
    bbx_xys = torch.load(paths.bbx)["bbx_xys"]

    if not Path(paths.vitpose).exists():
        progress(0.30, "points clés 2D (ViTPose)")
        extractor = VitPoseExtractor()
        torch.save(extractor.extract(cfg.video_path, bbx_xys), paths.vitpose)
        del extractor

    if not Path(paths.vit_features).exists():
        progress(0.55, "caractéristiques visuelles (HMR2)")
        extractor = Extractor()
        torch.save(extractor.extract_video_features(cfg.video_path, bbx_xys), paths.vit_features)
        del extractor

    if not cfg.static_cam and not Path(paths.slam).exists():
        progress(0.70, "mouvement de caméra")
        vo = SimpleVO(cfg.video_path, scale=0.5, step=8, method="sift", f_mm=cfg.f_mm)
        torch.save(vo.compute(), paths.slam)


def load_data(cfg):
    from hmr4d.utils.geo.hmr_cam import estimate_K
    from hmr4d.utils.geo_transform import compute_cam_angvel
    from hmr4d.utils.video_io_utils import get_video_lwh

    length, width, height = get_video_lwh(cfg.video_path)
    if cfg.static_cam:
        r_w2c = torch.eye(3).repeat(length, 1, 1)
    else:
        r_w2c = torch.from_numpy(torch.load(cfg.paths.slam)[:, :3, :3])
    return {
        "length": torch.tensor(length),
        "bbx_xys": torch.load(cfg.paths.bbx)["bbx_xys"],
        "kp2d": torch.load(cfg.paths.vitpose),
        "K_fullimg": estimate_K(width, height).repeat(length, 1, 1),
        "cam_angvel": compute_cam_angvel(r_w2c),
        "f_imgseq": torch.load(cfg.paths.vit_features),
    }


@torch.no_grad()
def predict(cfg, data):
    import hydra
    from hmr4d.utils.net_utils import detach_to_cpu

    progress(0.80, "reconstruction 3D (GVHMR)")
    model = hydra.utils.instantiate(cfg.model, _recursive_=False)
    model.load_pretrained_model(cfg.ckpt_path)
    model = model.eval().cuda()
    return detach_to_cpu(model.predict(data, static_cam=cfg.static_cam))


@torch.no_grad()
def camera_joints(pred):
    """Body joints in the camera frame (OpenCV: x right, y down, z forward) + intrinsics,
    for the editor's 2D overlay and its "video camera" 3D view."""
    from hmr4d.utils.smplx_utils import make_smplx

    model = make_smplx("supermotion")
    out = model(**{k: v.float() for k, v in pred["smpl_params_incam"].items()})
    joints = out.joints if hasattr(out, "joints") else out[1]
    return joints[:, :22].numpy(), pred["K_fullimg"][0].numpy()


@torch.no_grad()
def body_joints(params):
    from hmr4d.utils.smplx_utils import make_smplx

    model = make_smplx("supermotion")
    out = model(**{k: v.float() for k, v in params.items()})
    joints = out.joints if hasattr(out, "joints") else out[1]
    rest = model(
        global_orient=torch.zeros(1, 3),
        body_pose=torch.zeros(1, 63),
        transl=torch.zeros(1, 3),
        betas=params["betas"][:1].float(),
    )
    rest_joints = rest.joints if hasattr(rest, "joints") else rest[1]
    return joints[:, :22].numpy(), rest_joints[0, :22].numpy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--static-cam", action="store_true")
    args = parser.parse_args()

    cfg = build_cfg(args.video, args.workdir, args.static_cam)
    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.preprocess_dir).mkdir(parents=True, exist_ok=True)
    progress(0.02, "préparation de la vidéo")
    copy_video(args.video, cfg.video_path)

    preprocess(cfg)
    pred = predict(cfg, load_data(cfg))

    progress(0.95, "articulations SMPL-X")
    params = pred["smpl_params_global"]
    joints, rest_joints = body_joints(params)
    cam_joints, intrinsics = camera_joints(pred)
    np.savez_compressed(
        args.out,
        fps=args.fps,
        global_orient=params["global_orient"].numpy(),
        body_pose=params["body_pose"].numpy(),
        transl=params["transl"].numpy(),
        betas=params["betas"].numpy(),
        joints=joints,
        rest_joints=rest_joints,
        cam_joints=cam_joints,
        K=intrinsics,
    )
    progress(1.0, "terminé")
    return 0


if __name__ == "__main__":
    sys.exit(main())
