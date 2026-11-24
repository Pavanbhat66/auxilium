"""Vercel production health endpoint for AUXILIUM routing."""

from http.server import BaseHTTPRequestHandler
import json

from backend.server import GRAPH


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"ok": True, "nodes": len(GRAPH.coordinates), "edges": sum(len(edges) for edges in GRAPH.adjacency.values())}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
