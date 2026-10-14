"""Body + hand landmarks per frame with MediaPipe Tasks (Apache-2.0 models, no account needed)."""
import os
from pathlib import Path

import cv2
import numpy as np

from ..paths import MODELS

POSE_MODEL = MODELS / "pose_landmarker_heavy.task"
HAND_MODEL = MODELS / "hand_landmarker.task"
POSE_POINTS = 33
HAND_POINTS = 21


def _landmarker_options(vision, base, model, **kwargs):
    return dict(base_options=base(model_asset_path=str(model)), running_mode=vision.RunningMode.VIDEO, **kwargs)


def run(video_path, out_path, with_hands=True, progress=None):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    capture = cv2.VideoCapture(str(video_path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    pose_options = vision.PoseLandmarkerOptions(
        **_landmarker_options(vision, BaseOptions, POSE_MODEL, num_poses=1,
                              min_pose_detection_confidence=0.4, min_tracking_confidence=0.4)
    )
    hand_options = vision.HandLandmarkerOptions(
        **_landmarker_options(vision, BaseOptions, HAND_MODEL, num_hands=2,
                              min_hand_detection_confidence=0.4, min_tracking_confidence=0.4)
    )

    pose_world, pose_image = [], []
    hands_world, hands_image, hands_valid = [], [], []

    with vision.PoseLandmarker.create_from_options(pose_options) as pose_landmarker, \
            (vision.HandLandmarker.create_from_options(hand_options) if with_hands else _NullContext()) as hand_landmarker:
        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = int(round(frame_index * 1000.0 / fps))
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

            pose = pose_landmarker.detect_for_video(image, timestamp)
            pose_world.append(_pose_world(pose))
            pose_image.append(_pose_image(pose))

            if hand_landmarker is not None:
                world, img, valid = _hands(hand_landmarker.detect_for_video(image, timestamp))
            else:
                world, img, valid = _empty_hands()
            hands_world.append(world)
            hands_image.append(img)
            hands_valid.append(valid)

            frame_index += 1
            if progress and frame_index % 10 == 0:
                progress(frame_index, total)

    capture.release()
    out_path = Path(out_path)
    partial = out_path.with_name(out_path.stem + ".partial.npz")
    np.savez_compressed(
        partial,
        fps=fps,
        size=np.array([width, height]),
        pose_world=np.array(pose_world, dtype=np.float32),
        pose_image=np.array(pose_image, dtype=np.float32),
        hands_world=np.array(hands_world, dtype=np.float32),
        hands_image=np.array(hands_image, dtype=np.float32),
        hands_valid=np.array(hands_valid, dtype=bool),
    )
    os.replace(partial, out_path)
    return frame_index


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def _pose_world(result):
    out = np.full((POSE_POINTS, 4), np.nan, dtype=np.float32)
    if not result.pose_world_landmarks:
        return out
    for i, lm in enumerate(result.pose_world_landmarks[0]):
        out[i] = (lm.x, lm.y, lm.z, lm.visibility or 0.0)
    return out


def _pose_image(result):
    out = np.full((POSE_POINTS, 3), np.nan, dtype=np.float32)
    if not result.pose_landmarks:
        return out
    for i, lm in enumerate(result.pose_landmarks[0]):
        out[i] = (lm.x, lm.y, lm.visibility or 0.0)
    return out


def _empty_hands():
    return (np.full((2, HAND_POINTS, 3), np.nan, dtype=np.float32),
            np.full((2, HAND_POINTS, 2), np.nan, dtype=np.float32),
            np.zeros(2, dtype=bool))


def _hands(result):
    world, image, valid = _empty_hands()
    for h, handedness in enumerate(result.handedness or []):
        # MediaPipe labels handedness as seen in a mirrored selfie; "Left" is the subject's right hand.
        side = 1 if handedness[0].category_name == "Left" else 0
        world[side] = [(lm.x, lm.y, lm.z) for lm in result.hand_world_landmarks[h]]
        image[side] = [(lm.x, lm.y) for lm in result.hand_landmarks[h]]
        valid[side] = True
    return world, image, valid
