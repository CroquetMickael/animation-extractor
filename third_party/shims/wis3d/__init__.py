"""No-op stand-in for wis3d (GVHMR's training-time 3D debug viewer); inference never calls it."""


class Wis3D:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        def noop(*args, **kwargs):
            return None

        return noop
