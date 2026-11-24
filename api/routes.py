"""Vercel production adapter for the existing AUXILIUM routing graph."""

from http.server import BaseHTTPRequestHandler
import json

from backend.routing import PROFILES
from backend.server import GRAPH, _point


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_POST(self):
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
            start = _point(request.get("start"), "start")
            destination = _point(request.get("destination"), "destination")
            start_node, start_snap = GRAPH.nearest_node(start)
            destination_node, destination_snap = GRAPH.nearest_node(destination)
            snap_warnings = []
            if start_snap > 100:
                snap_warnings.append(f"Start snapped {round(start_snap)} m to mapped pedestrian data")
            if destination_snap > 100:
                snap_warnings.append(f"Destination snapped {round(destination_snap)} m to mapped pedestrian data")
            routes = GRAPH.alternatives(start_node, destination_node, profile, count)
            valid_routes = [
                GRAPH.serialize_route(route, start, destination, profile, snap_warnings)
                for route in routes
                if GRAPH.validate_route(route, start_node, destination_node)[0]
            ]
            if not valid_routes:
                self._send(422, {"error": "No complete pedestrian route was found for this profile"})
                return
            self._send(200, {"routes": valid_routes, "requested": {"start": start, "destination": destination}})
        except (ValueError, json.JSONDecodeError) as error:
            self._send(400, {"error": str(error)})
        except Exception as error:
            self._send(500, {"error": f"Routing service error: {error}"})
