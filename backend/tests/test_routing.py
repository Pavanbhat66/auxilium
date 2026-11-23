import unittest

from backend.routing import PedestrianGraph


def feature(path_id, coordinates, **properties):
    return {"type": "Feature", "id": path_id, "geometry": {"type": "LineString", "coordinates": coordinates}, "properties": {"path_id": path_id, "verification_status": "unverified", "surface": "unknown", "incline": "unknown", "wheelchair_access": "unknown", **properties}}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.features = [
            feature("direct", [[0, 0], [0.001, 0]], highway="steps", stairs="yes"),
            feature("safe-a", [[0, 0], [0, 0.001], [0.001, 0.001], [0.001, 0]], highway="footway", wheelchair_access="yes", surface="paved"),
        ]

    def test_wheelchair_prefers_accessible_alternative(self):
        graph = PedestrianGraph(self.features)
        start, goal = graph.nearest_node((0, 0))[0], graph.nearest_node((0.001, 0))[0]
        routes = graph.alternatives(start, goal, "wheelchair", 2)
        self.assertGreaterEqual(len(routes), 2)
        self.assertEqual(routes[0].edges[0].path_id, "safe-a")

    def test_unverified_gemini_evidence_is_warning_not_barrier(self):
        evidence = [{"geometry": {"type": "Point", "coordinates": [0.0005, 0]}, "properties": {"source": "gemini_ai", "feature_name": "stairs", "predicted_value": "present", "verification_status": "needs_review"}}]
        graph = PedestrianGraph([feature("path", [[0, 0], [0.001, 0]], highway="residential")], evidence)
        start, goal = graph.nearest_node((0, 0))[0], graph.nearest_node((0.001, 0))[0]
        route = graph.shortest_path(start, goal, "wheelchair")
        payload = graph.serialize_route(route, (0, 0), (0.001, 0), "wheelchair", [])
        self.assertIsNotNone(route)
        self.assertTrue(any("needs verification" in warning for warning in payload["warnings"]))

    def test_verified_wheelchair_barrier_is_avoided(self):
        blocked = feature("blocked", [[0, 0], [0.001, 0]], highway="steps", stairs="yes", verification_status="verified")
        graph = PedestrianGraph([blocked])
        start, goal = graph.nearest_node((0, 0))[0], graph.nearest_node((0.001, 0))[0]
        self.assertIsNone(graph.shortest_path(start, goal, "wheelchair"))


if __name__ == "__main__":
    unittest.main()
