"""Build-time geometry for small SVG drawings: projection, Douglas-Peucker simplification, path data.

stdlib only. Used for the constituency silhouettes on the index and the static map of Greece.
Module order: config <- geo <- matching/web. GeoJSON coordinates are (lng, lat).
"""
import math


def _dist(p, a, b):
    """Distance from point p to the segment a-b."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if not (dx or dy):
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def simplify(pts, tol):
    """Douglas-Peucker on an open polyline: the points that stay more than `tol` from the straight line."""
    if len(pts) < 3:
        return list(pts)
    keep, stack = {0, len(pts) - 1}, [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        far, at = 0, None
        for k in range(i + 1, j):
            d = _dist(pts[k], pts[i], pts[j])
            if d > far:
                far, at = d, k
        if at is not None and far > tol:
            keep.add(at)
            stack += [(i, at), (at, j)]
    return [pts[k] for k in sorted(keep)]


def simplify_ring(ring, tol):
    """A closed ring: split at the point farthest from the start, simplify both halves."""
    pts = ring[:-1] if ring[0] == ring[-1] else list(ring)
    if len(pts) < 4:
        return pts
    far = max(range(len(pts)), key=lambda k: math.hypot(pts[k][0] - pts[0][0], pts[k][1] - pts[0][1]))
    a, b = simplify(pts[:far + 1], tol), simplify(pts[far:] + [pts[0]], tol)
    return a[:-1] + b[:-1]


def area(ring):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))) / 2


def exteriors(geometry):
    """Outer rings of a GeoJSON Polygon or MultiPolygon (holes do not matter at this size)."""
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return [poly[0] for poly in polys]


def boundary(geometries):
    """Outline of the union of neighbouring polygons: an edge that two of them share, once in each direction,
    cancels, and the edges left are chained into closed rings (holes come out with the opposite direction)."""
    edges = {(tuple(a), tuple(b)) for g in geometries for r in exteriors(g) for a, b in zip(r, r[1:])}
    nxt = {}
    for a, b in edges:
        if (b, a) not in edges:
            nxt.setdefault(a, []).append(b)
    rings = []
    while nxt:
        start = cur = next(iter(nxt))
        ring = [start]
        while cur in nxt:
            b = nxt[cur].pop()
            if not nxt[cur]:
                del nxt[cur]
            ring.append(b)
            cur = b
            if b == start:
                break
        if len(ring) > 3:
            rings.append(ring)
    return rings


def frame(geometries, size):
    """Equirectangular projection fitted to `size` units on the longer side: (to_xy, width, height)."""
    pts = [p for g in geometries for r in exteriors(g) for p in r]
    lo_x, hi_x = min(p[0] for p in pts), max(p[0] for p in pts)
    lo_y, hi_y = min(p[1] for p in pts), max(p[1] for p in pts)
    k = math.cos(math.radians((lo_y + hi_y) / 2))
    scale = size / max((hi_x - lo_x) * k, hi_y - lo_y)

    def to_xy(p):
        return ((p[0] - lo_x) * k * scale, (hi_y - p[1]) * scale)
    return to_xy, math.ceil((hi_x - lo_x) * k * scale), math.ceil((hi_y - lo_y) * scale)


def path(rings, to_xy, tol, min_area):
    """SVG path data (relative, whole numbers) for rings: simplified, specks under `min_area` dropped."""
    out = []
    for ring in rings:
        xy = [to_xy(p) for p in ring]
        if area(xy) < min_area:
            continue
        pts = [(round(x), round(y)) for x, y in simplify_ring(xy, tol)]
        pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
        if len(pts) < 3:
            continue
        out.append(f"M{pts[0][0]} {pts[0][1]}l" + " ".join(f"{x1 - x0} {y1 - y0}" for (x0, y0), (x1, y1) in zip(pts, pts[1:])) + "z")
    return "".join(out)


def silhouette(geometries, size=100):
    """Inline SVG outline of one constituency (decorative: aria-hidden, drawn in the text colour)."""
    to_xy, w, h = frame(geometries, size)
    d = path(boundary(geometries), to_xy, tol=0.8, min_area=1.5)
    return f'<svg class="sil" viewBox="0 0 {w} {h}" aria-hidden="true"><path d="{d}"/></svg>' if d else ""
