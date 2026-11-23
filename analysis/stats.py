"""Weighted statistics shared by the analysis scripts: one definition each, no side effects on import.

wls, wcorr and moran are the formulas the nikh_* scripts carry as private copies. The copies
move here under a cmp check of their .txt (see CONTEXT.md); new scripts import from here only.
"""
import numpy as np


def wls(y, cols, w):
    """beta, se, r2 for y on [1, *cols], weights w. shortcut: plain WLS SE ignore spatial correlation."""
    X = np.column_stack([np.ones(len(y)), *cols])
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    res = y - X @ beta
    r2 = 1 - np.sum(w * res ** 2) / np.sum(w * (y - np.average(y, weights=w)) ** 2)
    se = np.sqrt(np.diag(np.sum(w * res ** 2) / (len(y) - X.shape[1]) * np.linalg.inv((X * w[:, None]).T @ X)))
    return beta, se, r2


def wcorr(a, b, w):
    """Weighted Pearson correlation of a and b with weights w."""
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    return np.average((a - ma) * (b - mb), weights=w) / np.sqrt(
        np.average((a - ma) ** 2, weights=w) * np.average((b - mb) ** 2, weights=w))


def moran(x, ia, ja, w):
    """Moran's I with weights w on pairs (ia, ja); row-standardised, so sum(w) = n."""
    z = x - x.mean()
    return (w * z[ia] * z[ja]).sum() / (z * z).sum()


def ranks(x):
    """Average ranks (ties share the mean rank), 1-based."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    r[order] = np.arange(1, len(x) + 1)
    for v, n in zip(*np.unique(x, return_counts=True)):
        if n > 1:
            m = x == v
            r[m] = r[m].mean()
    return r


def spearman(a, b):
    """Spearman rank correlation (Pearson on average ranks), unweighted."""
    return wcorr(ranks(a), ranks(b), np.ones(len(a)))


def pcorr(a, b, c):
    """Partial correlation of a and b controlling for c, unweighted."""
    w = np.ones(len(a))
    ab, ac, bc = wcorr(a, b, w), wcorr(a, c, w), wcorr(b, c, w)
    return (ab - ac * bc) / np.sqrt((1 - ac ** 2) * (1 - bc ** 2))


# self-checks, as the copies had them: exact line, perfect correlation, chain 0-1-2-3 with I = 0.4 by hand
_b, _, _r2 = wls(np.array([1., 3, 5, 7]), [np.array([0., 1, 2, 3])], np.ones(4))
assert np.allclose(_b, [1, 2]) and _r2 > 0.999
assert abs(wcorr(np.array([1., 2, 3]), np.array([2., 4, 6]), np.ones(3)) - 1) < 1e-12
assert np.allclose(ranks([10, 20, 20, 30]), [1, 2.5, 2.5, 4])
assert abs(spearman([1, 2, 3, 4], [1, 4, 9, 16]) - 1) < 1e-12  # monotone, not linear
_c = np.array([1., 2, 3, 4])  # a and b share only the trend c, so the partial correlation is exactly 0
assert abs(pcorr(_c + [1, -1, -1, 1], _c + [1, -3, 3, -1], _c)) < 1e-12
_I, _J = np.array([0, 1, 1, 2, 2, 3]), np.array([1, 0, 2, 1, 3, 2])
assert abs(moran(np.array([1., 2, 3, 4]), _I, _J, np.array([1, .5, .5, .5, .5, 1])) - 0.4) < 1e-9
