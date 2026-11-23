"""Minimal dependency-free HTTP API for AUXILIUM routing."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .routing import PROFILES, load_graph


ROOT = Path(__file__).resolve().parents[1]
GRAPH = load_graph(ROOT / "data-pipeline/output/pedestrian_paths.geojson", ROOT / "data-pipeline/output/mangalore_mapillary_accessibility.geojson")


def _point(value, name):
    if isinstance(value, dict):
        lat, lon = value.get("lat"), value.get("lon")
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        lat, lon = value
    else:
        raise ValueError(f"{name} must contain lat and lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"{name} coordinates are invalid")
    return (float(lon), float(lat))


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", os.getenv("AUXILIUM_CORS_ORIGIN", "http://localhost:5173"))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", os.getenv("AUXILIUM_CORS_ORIGIN", "http://localhost:5173"))
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/health":
            self._send(200, {"ok": True, "nodes": len(GRAPH.coordinates), "edges": sum(len(edges) for edges in GRAPH.adjacency.values())})
            return
        self._send(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/api/routes":
            self._send(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 32_000:
                raise ValueError("Request is too large")
            request = json.loads(self.rfile.read(size))
            profile = request.get("profile", "general")
            if profile not in PROFILES:
                raise ValueError("profile must be general, wheelchair, or walking_difficulty")
            count = request.get("alternatives", 3)
            if not isinstance(count, int) or not 1 <= count <= 3:
                raise ValueError("alternatives must be an integer from 1 to 3")
            start, destination = _point(request.get("start"), "start"), _point(request.get("destination"), "destination")
            start_node, start_snap = GRAPH.nearest_node(start)
            destination_node, destination_snap = GRAPH.nearest_node(destination)
            snap_warnings = []
            if start_snap > 100:
                snap_warnings.append(f"Start snapped {round(start_snap)} m to mapped pedestrian data")
            if destination_snap > 100:
                snap_warnings.append(f"Destination snapped {round(destination_snap)} m to mapped pedestrian data")
            routes = GRAPH.alternatives(start_node, destination_node, profile, count)
            if not routes:
                self._send(422, {"error": "No pedestrian route was found for this profile"})
                return
            valid_routes = []
            for route in routes:
                valid, _ = GRAPH.validate_route(route, start_node, destination_node)
                if valid:
                    valid_routes.append(GRAPH.serialize_route(route, start, destination, profile, snap_warnings))
            if not valid_routes:
                self._send(422, {"error": "No complete pedestrian route was found for this profile"})
                return
            self._send(200, {"routes": valid_routes, "requested": {"start": start, "destination": destination}})
        except (ValueError, json.JSONDecodeError) as error:
            self._send(400, {"error": str(error)})
        except Exception as error:
            self._send(500, {"error": f"Routing service error: {error}"})


if __name__ == "__main__":
    port = int(os.getenv("AUXILIUM_ROUTING_PORT", "8000"))
    print(f"AUXILIUM routing API listening on http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
