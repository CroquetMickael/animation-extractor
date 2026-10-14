from collections import namedtuple

import torch

_KNN = namedtuple("KNN", "dists idx knn")


def knn_points(p1, p2, lengths1=None, lengths2=None, norm=2, K=1, version=-1, return_nn=False, return_sorted=True):
    """Brute-force squared-distance KNN; inputs are (N, P, D) batches."""
    dists = torch.cdist(p1, p2, p=2) ** 2
    values, idx = torch.topk(dists, k=K, dim=-1, largest=False, sorted=return_sorted)
    nn = None
    if return_nn:
        batch = torch.arange(p2.shape[0], device=p2.device)[:, None, None]
        nn = p2[batch, idx]
    return _KNN(dists=values, idx=idx, knn=nn)
