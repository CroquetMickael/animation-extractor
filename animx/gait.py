"""Gait analysis: cadence from the legs' oscillation, expected travel speed from Rockstar's own clips.

Monocular capture is weakest along the camera axis, so a performer running toward the camera (or a
game animation played in place) under-reports how far the feet slide. Cadence, on the other hand, is
read from the legs' rhythm and is reliable; speed then follows from how Rockstar's locomotion relates
cadence to speed (measured in move_m@generic: walk 1.71 m/s at 1.87 steps/s, run plateau 5.11 m/s,
sprint 6.85 m/s at 3.64 steps/s).
"""
import numpy as np

# (steps per second, metres per second), interpolated linearly, clamped at the ends.
CADENCE_TO_SPEED = (
    (1.4, 1.1),
    (1.87, 1.71),
    (2.4, 3.3),
    (2.9, 5.11),
    (3.64, 6.85),
    (4.2, 8.0),
)
GAITS = ((2.15, "marche"), (2.6, "jogging"), (3.3, "course"), (99.0, "sprint"))
MIN_PERIODICITY = 0.35
STRIDE_SECONDS = (0.45, 1.6)


def _leg_signals(skel, local_r):
    """Signals that swing once per stride. Several, because a performer facing the camera hides the
    fore-aft foot separation in the depth axis, while foot height and knee bend stay well observed."""
    from . import rot
    _, world_p = skel.fk(local_r)
    pelvis = world_p[:, skel.index("SKEL_Pelvis")]
    foot = {s_: world_p[:, skel.index(f"SKEL_{s_}_Foot")] - pelvis for s_ in "LR"}
    forward = rot.apply(local_r[:, skel.index("SKEL_ROOT")], np.array([0.0, 1.0, 0.0]))

    def knee(side):
        hip, knee_, ankle = (world_p[:, skel.index(f"SKEL_{side}_{b}")] for b in ("Thigh", "Calf", "Foot"))
        u, v = knee_ - hip, ankle - knee_
        cos = np.sum(u * v, axis=-1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1) + 1e-9)
        return np.arccos(np.clip(cos, -1.0, 1.0))

    return (
        np.sum((foot["L"] - foot["R"]) * forward, axis=-1),
        foot["L"][:, 2] - foot["R"][:, 2],
        knee("L") - knee("R"),
    )


def _stride_period(signal, fps):
    signal = signal - signal.mean()
    frames = len(signal)
    lo, hi = int(fps * STRIDE_SECONDS[0]), min(int(fps * STRIDE_SECONDS[1]), frames - 1)
    if hi <= lo or np.std(signal) < 1e-3:
        return None, 0.0
    corr = np.correlate(signal, signal, mode="full")[frames - 1:]
    corr /= corr[0] + 1e-9
    lag = lo + int(np.argmax(corr[lo:hi]))
    return lag, float(corr[lag])


def analyze(skel, local_r, fps):
    """Returns {cadence, gait, expected_speed, periodicity} or None when the clip isn't periodic locomotion."""
    best_lag, best = None, 0.0
    for signal in _leg_signals(skel, local_r):
        lag, periodicity = _stride_period(signal, fps)
        if lag is not None and periodicity > best:
            best_lag, best = lag, periodicity
    if best_lag is None or best < MIN_PERIODICITY:
        return None

    cadence = 2.0 * fps / best_lag
    speed = np.interp(cadence, [c for c, _ in CADENCE_TO_SPEED], [v for _, v in CADENCE_TO_SPEED])
    gait = next(name for limit, name in GAITS if cadence < limit)
    return {"cadence": round(cadence, 2), "gait": gait, "expected_speed": round(float(speed), 2), "periodicity": round(best, 2)}
