"""Import-only placeholder: GVHMR imports pytorch3d rendering at module level for training/visualisation code that inference never runs."""


class _Unavailable:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("pytorch3d rendering is not available in anim-extract")


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    return _Unavailable
