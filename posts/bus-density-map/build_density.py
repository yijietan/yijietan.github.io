"""Build the bus service density map data from BusRouter SG route shapes.

Usage:
    python build_density.py <busrouter_dir> <output.json>

<busrouter_dir> must contain services.min.json and routes.min.json from
https://data.busrouter.sg/v1/ . The output is a compact JSON file read by
the interactive map in index.qmd. Line coordinates are delta-encoded
integers in units of 1e-5 degrees: [lat0, lon0, dlat1, dlon1, ...].

Method: every route shape is resampled every few metres. Points are merged
into shared road nodes about NODE_M metres apart, so both directions of a road
(and services drawn a few metres apart) share the same nodes. Consecutive nodes
on a route form road links; each link records the distinct services using it.
Links are then joined into continuous lines wherever the set of services stays
the same, and each line is coloured by its number of services.
"""
import json
import math
import re
import sys
from collections import defaultdict

NODE_M = 12        # points closer than this to an existing node join it, metres
STEP_M = 5         # resampling step along each route, metres
LAT0, LON0 = 1.35, 103.82
M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT0))


def included(svc: str) -> bool:
    """Trunk, feeder, express and short-trip services with normal operating hours."""
    num = re.match(r"\d+", svc)
    if not num:
        return False                      # e.g. SWA/SWB
    n = int(num.group())
    if 600 <= n <= 699 and len(num.group()) == 3:
        return False                      # City Direct and other premium services
    if svc in {"502", "502A", "506", "518", "518A"}:
        return False                      # peak-hour-only express
    if svc in {"401", "405"}:
        return False                      # weekend / seasonal services
    return True


def decode_polyline(s):
    coords, i, lat, lon = [], 0, 0, 0
    while i < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += d
            else:
                lon += d
        coords.append((lat / 1e5, lon / 1e5))
    return coords


def to_xy(lat, lon):
    return ((lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT)


def to_latlon(x, y):
    return (LAT0 + y / M_PER_DEG_LAT, LON0 + x / M_PER_DEG_LON)


def resample(coords):
    pts = [to_xy(*c) for c in coords]
    out = [pts[0]]
    carry = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg == 0:
            continue
        d = STEP_M - carry
        while d <= seg:
            t = d / seg
            out.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
            d += STEP_M
        carry = seg - (d - STEP_M)
    out.append(pts[-1])
    return out


class Nodes:
    """Road nodes with a spatial hash for nearest-node lookup."""

    def __init__(self):
        self.pos = []            # [x, y, n] running mean of assigned points
        self.grid = defaultdict(list)

    def key(self, x, y):
        return (int(math.floor(x / NODE_M)), int(math.floor(y / NODE_M)))

    def assign(self, p):
        kx, ky = self.key(*p)
        best, best_d = None, NODE_M
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self.grid.get((kx + dx, ky + dy), ()):
                    x, y, _ = self.pos[i]
                    d = math.hypot(p[0] - x, p[1] - y)
                    if d < best_d:
                        best, best_d = i, d
        if best is None:
            best = len(self.pos)
            self.pos.append([p[0], p[1], 1])
            self.grid[(kx, ky)].append(best)
        else:
            node = self.pos[best]
            node[2] += 1
            node[0] += (p[0] - node[0]) / node[2]
            node[1] += (p[1] - node[1]) / node[2]
        return best


def main(src, dst):
    services = json.load(open(f"{src}/services.min.json", encoding="utf-8"))
    routes = json.load(open(f"{src}/routes.min.json", encoding="utf-8"))

    svc_list = sorted((s for s in routes if included(s)), key=lambda s: (len(s), s))
    nodes = Nodes()
    edge_svcs = defaultdict(set)     # (node a, node b) with a < b -> service indices
    for si, svc in enumerate(svc_list):
        for poly in routes[svc]:
            if not poly:
                continue
            prev = None
            for p in resample(decode_polyline(poly)):
                n = nodes.assign(p)
                if prev is not None and n != prev:
                    edge_svcs[(min(n, prev), max(n, prev))].add(si)
                prev = n

    adj = defaultdict(list)
    for e in edge_svcs:
        adj[e[0]].append(e)
        adj[e[1]].append(e)

    def other(e, n):
        return e[1] if e[0] == n else e[0]

    def extend(chain_nodes, e, n, svcs, used):
        """Walk from node n away from edge e while the next edge has the same services."""
        while len(adj[n]) == 2:
            nxt = adj[n][0] if adj[n][1] == e else adj[n][1]
            if nxt in used or edge_svcs[nxt] != svcs:
                break
            used.add(nxt)
            n = other(nxt, n)
            chain_nodes.append(n)
            e = nxt

    used, lines = set(), []
    length_by_bucket = defaultdict(float)
    for e, svcs in edge_svcs.items():
        x0, y0, _ = nodes.pos[e[0]]
        x1, y1, _ = nodes.pos[e[1]]
        length_by_bucket[min(len(svcs), 10)] += math.hypot(x1 - x0, y1 - y0)
        if e in used:
            continue
        used.add(e)
        fwd, back = [e[1]], [e[0]]
        extend(fwd, e, e[1], svcs, used)
        extend(back, e, e[0], svcs, used)
        chain = back[::-1] + fwd
        pts = [tuple(nodes.pos[n][:2]) for n in chain]
        lines.append([min(len(svcs), 10), sorted(svcs), pts])

    # Simplify, then delta-encode coordinates as integers (1e-5 degrees, about 1 m).
    # Identical service lists are stored once and referenced by index.
    set_ids, sets, out_lines = {}, [], []
    for bucket, near, pts in lines:
        key = tuple(near)
        if key not in set_ids:
            set_ids[key] = len(sets)
            sets.append(near)
        flat, pla, plo = [], 0, 0
        for p in pts:
            la, lo = to_latlon(*p)
            ila, ilo = round(la * 1e5), round(lo * 1e5)
            flat += [ila - pla, ilo - plo]
            pla, plo = ila, ilo
        out_lines.append([bucket, set_ids[key], flat])

    total = sum(length_by_bucket.values())
    histogram = {str(b): round(100 * length_by_bucket[b] / total, 1) for b in sorted(length_by_bucket)}
    out = {
        "generated_from": "https://data.busrouter.sg/v1/ (services.min.json, routes.min.json)",
        "node_m": NODE_M,
        "services": svc_list,
        "names": {s: services[s]["name"] for s in svc_list},
        "histogram_pct_by_length": histogram,
        "road_km": round(total / 1000, 1),
        "sets": sets,
        "lines": out_lines,
    }
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(svc_list)} services, {len(out_lines)} lines, {total/1000:.0f} km of road")
    print("histogram %:", histogram)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
