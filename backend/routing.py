"""Accessibility-aware pedestrian graph and routing.

The graph accepts the GeoJSON produced by ``data-pipeline/extract_osm.py``.
Unknown or unverified accessibility data is represented as uncertainty and
never promoted to a confirmed barrier, especially for Gemini predictions.
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PROFILES = {"general", "wheelchair", "walking_difficulty"}
VERIFIED = {"verified", "confirmed", "human_verified"}
EARTH_RADIUS_M = 6_371_000


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return haversine distance for (lon, lat) points."""
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0, 1 - h)))


def point_to_segment_m(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Approximate point-to-segment distance in local metres."""
    lon0, lat0 = map(math.radians, point)
    scale = EARTH_RADIUS_M

    def xy(p: tuple[float, float]) -> tuple[float, float]:
        return ((math.radians(p[0]) - lon0) * math.cos(lat0) * scale, (math.radians(p[1]) - lat0) * scale)

    ax, ay = xy(a)
    bx, by = xy(b)
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if not length:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
    return math.hypot(ax + t * dx, ay + t * dy)


def _truth(value: object) -> str:
    return str(value or "unknown").strip().lower()


def _verified(properties: dict) -> bool:
    return _truth(properties.get("verification_status")) in VERIFIED


@dataclass(frozen=True)
class Edge:
    start: str
    end: str
    key: tuple[str, str, str, int]
    path_id: str
    coordinates: tuple[tuple[float, float], ...]
    distance_m: float
    duration_s: float
    properties: dict = field(compare=False)
    evidence: tuple[dict, ...] = field(default_factory=tuple, compare=False)


@dataclass
class Route:
    nodes: list[str]
    edges: list[Edge]
    cost: float

    @property
    def distance_m(self) -> float:
        return sum(edge.distance_m for edge in self.edges)


class PedestrianGraph:
    """In-memory directed graph with profile-aware costs."""

    def __init__(self, features: Iterable[dict], evidence: Iterable[dict] = ()):
        self.adjacency: dict[str, list[Edge]] = {}
        self.coordinates: dict[str, tuple[float, float]] = {}
        self._build(list(features), list(evidence))

    @staticmethod
    def node_id(point: tuple[float, float]) -> str:
        return f"{point[0]:.7f},{point[1]:.7f}"

    def _build(self, features: list[dict], evidence: list[dict]) -> None:
        for feature in features:
            if feature.get("geometry", {}).get("type") != "LineString":
                continue
            raw = feature["geometry"].get("coordinates", [])
            if len(raw) < 2:
                continue
            points = [tuple(map(float, point[:2])) for point in raw]
            properties = dict(feature.get("properties") or {})
            path_id = str(properties.get("path_id") or feature.get("id") or "osm-way")
            tags = dict(properties.get("osm_tags") or {})
            merged = {**tags, **properties}
            for index, (start, end) in enumerate(zip(points, points[1:])):
                if start == end:
                    continue
                start_id, end_id = self.node_id(start), self.node_id(end)
                self.coordinates[start_id] = start
                self.coordinates[end_id] = end
                edge_properties = dict(merged)
                edge_properties["path_id"] = path_id
                edge = self._make_edge(start_id, end_id, (start, end), path_id, index, edge_properties, evidence)
                self.adjacency.setdefault(start_id, []).append(edge)
                if _truth(merged.get("oneway")) not in {"yes", "true", "1"}:
                    reverse = self._make_edge(end_id, start_id, (end, start), path_id, index, edge_properties, evidence)
                    self.adjacency.setdefault(end_id, []).append(reverse)

    def _make_edge(self, start_id, end_id, points, path_id, index, properties, evidence) -> Edge:
        associated = []
        for item in evidence:
            geometry = item.get("geometry") or {}
            coords = geometry.get("coordinates", [])
            if geometry.get("type") != "Point" or len(coords) < 2:
                continue
            point = (float(coords[0]), float(coords[1]))
            if point_to_segment_m(point, points[0], points[1]) <= 50:
                associated.append(item)
        length = distance_m(points[0], points[1])
        speed = {"steps": 2.0, "footway": 4.2, "path": 3.8, "pedestrian": 4.5}.get(
            _truth(properties.get("highway")), 5.0
        )
        return Edge(start_id, end_id, (start_id, end_id, path_id, index), path_id, tuple(points), length, length / (speed * 1000 / 3600), properties, tuple(associated))

    def nearest_node(self, point: tuple[float, float]) -> tuple[str, float]:
        if not self.coordinates:
            raise ValueError("The pedestrian graph is empty")
        node, distance = min(self.coordinates.items(), key=lambda item: distance_m(point, item[1]))
        return node, distance_m(point, self.coordinates[node])

    def _edge_cost(self, edge: Edge, profile: str) -> tuple[float, list[str], float]:
        p = edge.properties
        verified = _verified(p)
        cost = edge.duration_s
        penalty = 0.0
        warnings: list[str] = []
        highway, stairs = _truth(p.get("highway")), _truth(p.get("stairs"))
        wheelchair = _truth(p.get("wheelchair_access") or p.get("wheelchair"))
        surface, smoothness = _truth(p.get("surface")), _truth(p.get("smoothness"))
        incline = _truth(p.get("incline"))

        if profile == "wheelchair":
            if verified and (highway == "steps" or stairs == "yes" or wheelchair == "no"):
                return math.inf, ["Verified inaccessible segment"], 0
            if highway == "steps" or stairs == "yes":
                penalty += edge.duration_s * 3
                warnings.append("Stairs are mapped but not independently verified")
            if wheelchair == "unknown":
                penalty += edge.duration_s * 0.25
            elif wheelchair == "yes":
                penalty -= edge.duration_s * 0.08
            if incline in {"high", "steep"} or (incline.endswith("%") and _numeric(incline) > 8):
                penalty += edge.duration_s * 1.5
                warnings.append("Steep incline")
            if surface in {"gravel", "cobblestone", "ground", "dirt", "sand", "unpaved"} or smoothness in {"bad", "very_bad", "horrible", "very_horrible"}:
                penalty += edge.duration_s * 0.8
                warnings.append("Surface may be difficult for wheelchair users")
        elif profile == "walking_difficulty":
            if verified and highway == "steps" and stairs == "yes":
                penalty += edge.duration_s * 2.5
            elif highway == "steps" or stairs == "yes":
                penalty += edge.duration_s * 1.3
                warnings.append("Stairs are mapped but not independently verified")
            if incline in {"high", "steep"} or (incline.endswith("%") and _numeric(incline) > 8):
                penalty += edge.duration_s
                warnings.append("Steep incline")
            if surface in {"gravel", "cobblestone", "ground", "dirt", "sand", "unpaved"} or smoothness in {"bad", "very_bad", "horrible", "very_horrible"}:
                penalty += edge.duration_s * 0.5
                warnings.append("Uneven surface may require care")

        unknown_fields = sum(_truth(p.get(name)) == "unknown" for name in ("surface", "incline", "wheelchair_access", "smoothness"))
        if profile != "general":
            penalty += edge.duration_s * min(0.5, unknown_fields * 0.06)
        for item in edge.evidence:
            props = item.get("properties") or {}
            status = _truth(props.get("verification_status"))
            source = _truth(props.get("source"))
            label = props.get("evidence_type") or props.get("feature_name") or "accessibility condition"
            if status in VERIFIED:
                penalty += edge.duration_s * (0.5 if profile != "general" else 0.1)
                warnings.append(f"Verified {label} evidence nearby")
            elif source == "gemini_ai" or props.get("model"):
                warnings.append(f"{label} prediction needs verification")
            else:
                warnings.append(f"Potential {label} nearby; needs verification")
        return max(0.1, cost + penalty), warnings, penalty

    def shortest_path(self, start: str, goal: str, profile: str, banned_edges=frozenset(), banned_nodes=frozenset()) -> Route | None:
        queue = [(0.0, start, (start,), ())]
        best = {start: 0.0}
        while queue:
            cost, node, nodes, edges = heapq.heappop(queue)
            if node == goal:
                return Route(list(nodes), list(edges), cost)
            if cost > best.get(node, math.inf):
                continue
            for edge in self.adjacency.get(node, []):
                if edge.key in banned_edges or edge.end in banned_nodes:
                    continue
                edge_cost, _, _ = self._edge_cost(edge, profile)
                if math.isinf(edge_cost):
                    continue
                new_cost = cost + edge_cost
                if new_cost < best.get(edge.end, math.inf):
                    best[edge.end] = new_cost
                    heapq.heappush(queue, (new_cost, edge.end, nodes + (edge.end,), edges + (edge,)))
        return None

    def alternatives(self, start: str, goal: str, profile: str, count: int = 3) -> list[Route]:
        first = self.shortest_path(start, goal, profile)
        if not first:
            return []
        found = [first]
        candidates: list[tuple[float, tuple[tuple[str, str, str, int], ...], Route]] = []
        seen = {tuple(edge.key for edge in first.edges)}
        for _ in range(1, count):
            previous = found[-1]
            for index in range(len(previous.edges)):
                root_nodes = previous.nodes[: index + 1]
                root_edges = previous.edges[:index]
                removed = {route.edges[index].key for route in found if len(route.edges) > index and route.nodes[: index + 1] == root_nodes}
                spur = self.shortest_path(root_nodes[-1], goal, profile, removed, set(root_nodes[:-1]))
                if not spur:
                    continue
                combined = Route(root_nodes[:-1] + spur.nodes, list(root_edges) + spur.edges, 0)
                combined.cost = sum(self._edge_cost(edge, profile)[0] for edge in combined.edges)
                signature = tuple(edge.key for edge in combined.edges)
                if signature not in seen:
                    seen.add(signature)
                    heapq.heappush(candidates, (combined.cost, signature, combined))
            if not candidates:
                break
            found.append(heapq.heappop(candidates)[2])
        return found

    def serialize_route(self, route: Route, requested_start, requested_destination, profile: str, snap_warnings: list[str]) -> dict:
        points: list[list[float]] = [[requested_start[0], requested_start[1]]]
        for edge in route.edges:
            edge_points = list(edge.coordinates)
            if edge_points and tuple(points[-1]) == edge_points[0]:
                edge_points = edge_points[1:]
            points.extend([[p[0], p[1]] for p in edge_points])
        if points[-1] != [requested_destination[0], requested_destination[1]]:
            points.append([requested_destination[0], requested_destination[1]])
        warnings = list(snap_warnings)
        unknown = 0
        for edge in route.edges:
            _, edge_warnings, _ = self._edge_cost(edge, profile)
            warnings.extend(edge_warnings)
            unknown += sum(_truth(edge.properties.get(name)) == "unknown" for name in ("surface", "incline", "wheelchair_access"))
        unique_warnings = list(dict.fromkeys(warnings))
        penalty = sum(1 for warning in unique_warnings if "Verified" in warning) * 18
        penalty += sum(1 for warning in unique_warnings if "needs verification" in warning or "not independently verified" in warning) * 5
        penalty += min(25, unknown * 2) if profile != "general" else 0
        score = max(0, min(100, 100 - penalty))
        return {"geometry": {"type": "LineString", "coordinates": points}, "distance": round(route.distance_m, 1), "duration": round(sum(edge.duration_s for edge in route.edges)), "accessibilityScore": score, "warnings": unique_warnings, "profile": profile, "pathIds": list(dict.fromkeys(edge.path_id for edge in route.edges))}


def _numeric(value: str) -> float:
    try:
        return float(value.rstrip("%"))
    except ValueError:
        return 0


def load_geojson(path: Path) -> tuple[list[dict], list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("features", []), []


def load_graph(paths_file: Path, evidence_file: Path | None = None) -> PedestrianGraph:
    features, _ = load_geojson(paths_file)
    evidence = []
    if evidence_file and evidence_file.exists():
        evidence = json.loads(evidence_file.read_text(encoding="utf-8")).get("features", [])
    return PedestrianGraph(features, evidence)
