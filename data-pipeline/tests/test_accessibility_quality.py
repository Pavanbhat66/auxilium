import json
import csv
import sys
import tempfile
import unittest
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE_DIR))

from accessibility_quality import (  # noqa: E402
    MATCH_THRESHOLD_METERS,
    REVIEW_DECISIONS_ALLOWED,
    build_matching_report,
    is_valid_coordinate_pair,
    nearest_path,
    normalize_observation,
    validate_evidence,
    export_reviewed,
    write_review_queue,
)


def point_feature(evidence_id, coordinates, category="obstacle", value="present", confidence=0.5):
    return {
        "type": "Feature",
        "id": evidence_id,
        "geometry": {"type": "Point", "coordinates": coordinates},
        "properties": {
            "source": "gemini_ai",
            "mapillary_image_id": f"image-{evidence_id}",
            "feature_name": category,
            "predicted_value": value,
            "confidence": confidence,
            "visual_explanation": "Visible evidence.",
            "verification_status": "needs_review",
            "accessibility_claim": "unknown",
        },
    }


class AccessibilityQualityTests(unittest.TestCase):
    def test_normalization_and_confidence(self):
        normalized = normalize_observation({"feature_name": "bogus", "predicted_value": "bogus", "confidence": 9})
        self.assertEqual(normalized["feature_name"], "other")
        self.assertEqual(normalized["predicted_value"], "unknown")
        self.assertEqual(normalized["confidence"], 1.0)
        self.assertEqual(normalize_observation({})["confidence"], 0.0)

    def test_coordinate_order_and_validity(self):
        self.assertTrue(is_valid_coordinate_pair([74.81, 12.90]))
        self.assertFalse(is_valid_coordinate_pair([12.90, 200]))
        self.assertFalse(is_valid_coordinate_pair([74.81]))

    def test_validation_duplicate_and_unknown_claims(self):
        features = [point_feature("a", [74.81, 12.90], value="unknown"), point_feature("b", [74.81, 12.90], value="unknown")]
        features[1]["properties"]["mapillary_image_id"] = features[0]["properties"]["mapillary_image_id"]
        report = validate_evidence(features)
        self.assertEqual(report["ai_evidence_records"], 2)
        self.assertEqual(len(report["exact_duplicate_groups"]), 1)
        self.assertEqual(report["unknown_observations"], 2)

    def test_linestring_thresholds_and_closest_path(self):
        paths = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "far", "geometry": {"type": "LineString", "coordinates": [[74.809, 12.90], [74.8095, 12.90]]}, "properties": {"source": "openstreetmap", "path_id": "far"}},
                {"type": "Feature", "id": "near", "geometry": {"type": "LineString", "coordinates": [[74.81004, 12.90], [74.81104, 12.90]]}, "properties": {"source": "openstreetmap", "path_id": "near"}},
            ],
        }
        candidate = nearest_path([74.81005, 12.90], paths["features"])
        self.assertEqual(candidate["matched_path_id"], "near")
        self.assertLess(candidate["nearest_distance_m"], 10)
        self.assertIsNone(nearest_path([75.0, 13.0], paths["features"])["matched_path_id"])

    def test_multilinestring_and_matching_report(self):
        paths = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "id": "multi", "geometry": {"type": "MultiLineString", "coordinates": [[[74.81, 12.90], [74.811, 12.90]], [[74.82, 12.90], [74.821, 12.90]]]}, "properties": {"source": "openstreetmap", "path_id": "multi"},
        }]}
        evidence = {"type": "FeatureCollection", "features": [point_feature("near", [74.81005, 12.90]), point_feature("outside", [75.0, 13.0])]}
        report = build_matching_report(evidence, paths)
        self.assertEqual(report["total_accessibility_observations"], 2)
        self.assertEqual(report["matched_within_10m"], 1)
        self.assertEqual(report["matched_within_50m"], 1)
        self.assertEqual(report["unmatched_observations"], 1)

    def test_review_queue_defaults_pending_and_decisions_are_constrained(self):
        evidence = {"type": "FeatureCollection", "features": [point_feature("a", [74.81, 12.90])]}
        matching = build_matching_report(evidence, {"type": "FeatureCollection", "features": []})
        with tempfile.TemporaryDirectory() as directory:
            import accessibility_quality as quality
            original_queue = quality.REVIEW_QUEUE
            quality.REVIEW_QUEUE = Path(directory) / "queue.csv"
            try:
                rows = write_review_queue(evidence, matching)
            finally:
                quality.REVIEW_QUEUE = original_queue
        self.assertEqual(rows[0]["reviewer_decision"], "pending")
        self.assertEqual(REVIEW_DECISIONS_ALLOWED, {"pending", "confirmed", "rejected", "needs_more_evidence"})
        self.assertEqual(MATCH_THRESHOLD_METERS, 50.0)

    def test_invalid_review_decision_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            import accessibility_quality as quality
            input_path = Path(directory) / "queue.csv"
            output_path = Path(directory) / "export.json"
            with input_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["evidence_id", "reviewer_decision"])
                writer.writeheader()
                writer.writerow({"evidence_id": "a", "reviewer_decision": "approved_by_ai"})
            original_decisions = quality.REVIEW_DECISIONS
            quality.REVIEW_DECISIONS = Path(directory) / "decisions.json"
            try:
                with self.assertRaises(ValueError):
                    export_reviewed(input_path, output_path)
            finally:
                quality.REVIEW_DECISIONS = original_decisions

    def test_review_export_rejects_changed_ai_prediction(self):
        with tempfile.TemporaryDirectory() as directory:
            import accessibility_quality as quality
            input_path = Path(directory) / "queue.csv"
            output_path = Path(directory) / "export.json"
            feature = point_feature("a", [74.81, 12.90])
            original_evidence = quality.EVIDENCE_FILE
            original_decisions = quality.REVIEW_DECISIONS
            quality.EVIDENCE_FILE = Path(directory) / "evidence.json"
            quality.REVIEW_DECISIONS = Path(directory) / "decisions.json"
            quality.EVIDENCE_FILE.write_text(json.dumps({"features": [feature]}), encoding="utf-8")
            with input_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "evidence_id", "mapillary_image_id", "observation_category", "predicted_value",
                    "ai_explanation", "confidence", "latitude", "longitude", "verification_status",
                    "reviewer_decision", "reviewer_notes",
                ])
                writer.writeheader()
                writer.writerow({
                    "evidence_id": "a", "mapillary_image_id": "image-a", "observation_category": "obstacle",
                    "predicted_value": "rejected_value", "ai_explanation": "Visible evidence.", "confidence": "0.5",
                    "latitude": "12.9", "longitude": "74.81", "verification_status": "needs_review",
                    "reviewer_decision": "rejected", "reviewer_notes": "",
                })
            try:
                with self.assertRaises(ValueError):
                    export_reviewed(input_path, output_path)
            finally:
                quality.EVIDENCE_FILE = original_evidence
                quality.REVIEW_DECISIONS = original_decisions


if __name__ == "__main__":
    unittest.main()
