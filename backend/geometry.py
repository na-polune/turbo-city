"""Tiny 2D geometry helpers for edit validation (world coordinates, meters)."""
import math

EPS = 1e-9


def point_in_poly(px, py, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _orient(a, b, c):
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return 0 if abs(v) < EPS else (1 if v > 0 else -1)


def _on_seg(a, b, p):
    return (min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS and
            min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS)


def segs_intersect(a, b, c, d):
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_seg(a, b, c):
        return True
    if o2 == 0 and _on_seg(a, b, d):
        return True
    if o3 == 0 and _on_seg(c, d, a):
        return True
    return o4 == 0 and _on_seg(c, d, b)


def seg_point_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 < EPS else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(p[0] - (a[0] + dx * t), p[1] - (a[1] + dy * t))


def seg_poly_gap(a, b, poly):
    """Distance from segment ab to a polygon; 0 if it touches, crosses or lies inside."""
    if point_in_poly(a[0], a[1], poly) or point_in_poly(b[0], b[1], poly):
        return 0.0
    best = math.inf
    n = len(poly)
    for i in range(n):
        c, d = poly[i], poly[(i + 1) % n]
        if segs_intersect(a, b, c, d):
            return 0.0
        best = min(best,
                   seg_point_dist(a, c, d), seg_point_dist(b, c, d),
                   seg_point_dist(c, a, b), seg_point_dist(d, a, b))
    return best


def polys_overlap(A, B):
    """True if two simple polygons share any area (vertex containment or edge crossing)."""
    if any(point_in_poly(x, y, B) for x, y in A):
        return True
    if any(point_in_poly(x, y, A) for x, y in B):
        return True
    nA, nB = len(A), len(B)
    for i in range(nA):
        a, b = A[i], A[(i + 1) % nA]
        for j in range(nB):
            if segs_intersect(a, b, B[j], B[(j + 1) % nB]):
                return True
    return False
