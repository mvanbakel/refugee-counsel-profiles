"""Build app/data/world.json: a world outline and one map point per claimant country.

Input: data/raw/countries-110m.json, Natural Earth 1:110m country outlines (public domain)
as TopoJSON from the world-atlas package (https://github.com/topojson/world-atlas, v2.0.2).

The outline is projected once here with the Equal Earth projection and saved as an SVG path,
so the app only has to draw it. Each country's point is the centre of its largest land area.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATLAS = ROOT / "data/raw/countries-110m.json"
PROFILES = ROOT / "app/data/profiles.json"
OUT = ROOT / "app/data/world.json"
WIDTH = 960

# Our country names -> Natural Earth names, where they differ.
ALIASES = {
    "Bosnia and Herzegovina": "Bosnia and Herz.",
    "Czech Republic": "Czechia",
    "DR Congo": "Dem. Rep. Congo",
    "Republic of the Congo": "Congo",
    "Dominican Republic": "Dominican Rep.",
    "Eswatini": "eSwatini",
    "United States": "United States of America",
}
# Places too small for the 1:110m outlines, or not separate countries in them: (lat, lon).
FIXED = {
    "Antigua and Barbuda": (17.07, -61.80),
    "Barbados": (13.17, -59.55),
    "Dominica": (15.42, -61.35),
    "Grenada": (12.12, -61.68),
    "Saint Lucia": (13.90, -60.98),
    "Saint Vincent and the Grenadines": (13.25, -61.20),
    "Tibet": (31.50, 88.00),
    "Serbia and Montenegro": (43.30, 20.30),
}

A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = math.sqrt(3) / 2


def equal_earth(lon, lat):
    lam, phi = math.radians(lon), math.radians(lat)
    t = math.asin(M * math.sin(phi))
    t2 = t * t
    t6 = t2 ** 3
    x = lam * math.cos(t) / (M * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2)))
    y = t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))
    return x, -y


def decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def ring(arcs, idxs):
    pts = []
    for i in idxs:
        a = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(a if not pts else a[1:])
    return pts


def split_antimeridian(pts):
    """Russia and Fiji wrap from 180° to -180°. Draw such a ring twice, once clamped to each edge."""
    if max(abs(a[0] - b[0]) for a, b in zip(pts, pts[1:])) <= 180:
        return [pts]
    east = [(lon + 360 if lon < 0 else lon, lat) for lon, lat in pts]
    out = [[(min(lon, 180), lat) for lon, lat in east]]
    if any(lon - 360 > -180 for lon, _ in east):
        out.append([(max(lon - 360, -180), lat) for lon, lat in east])
    return out


def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["arcs"]]
    if geom["type"] == "MultiPolygon":
        return geom["arcs"]
    return []


def area_centroid(pts):
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        f = x0 * y1 - x1 * y0
        a += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(a) < 1e-12:
        return 0.0, pts[0]
    return abs(a) / 2, (cx / (3 * a), cy / (3 * a))


def main():
    topo = json.loads(ATLAS.read_text())
    arcs = decode_arcs(topo)
    shapes = {}  # name -> list of projected outer+inner rings per polygon
    for g in topo["objects"]["countries"]["geometries"]:
        name = g["properties"]["name"]
        if name == "Antarctica":
            continue
        shapes[name] = [
            [[equal_earth(*p) for p in part] for r in poly for part in split_antimeridian(ring(arcs, r))]
            for poly in polygons(g)
        ]

    xs = [x for s in shapes.values() for poly in s for r in poly for x, _ in r]
    ys = [y for s in shapes.values() for poly in s for r in poly for _, y in r]
    x0, y0 = min(xs), min(ys)
    k = WIDTH / (max(xs) - x0)
    height = round((max(ys) - y0) * k)

    def sx(p):
        return round((p[0] - x0) * k, 1), round((p[1] - y0) * k, 1)

    parts = []
    for s in shapes.values():
        for poly in s:
            for r in poly:
                q = [sx(p) for p in r]
                d = "M" + "L".join(f"{x:g},{y:g}" for x, y in q) + "Z"
                parts.append(d)

    points, missing = {}, []
    for c in json.loads(PROFILES.read_text())["countries"]:
        name = c["name"]
        if name in FIXED:
            lat, lon = FIXED[name]
            points[name] = sx(equal_earth(lon, lat))
            continue
        s = shapes.get(ALIASES.get(name, name))
        if not s:
            missing.append(name)
            continue
        best = max((area_centroid(poly[0]) for poly in s), key=lambda t: t[0])
        points[name] = sx(best[1])

    OUT.write_text(json.dumps({"width": WIDTH, "height": height, "path": "".join(parts), "points": points},
                              separators=(",", ":")))
    print(f"{len(points)} countries placed, {OUT.stat().st_size / 1024:.0f} KB")
    if missing:
        print("No location for:", ", ".join(missing))


if __name__ == "__main__":
    main()
