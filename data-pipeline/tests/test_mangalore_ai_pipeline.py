import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE_DIR))

import mangalore_ai_pipeline as pipeline  # noqa: E402


class MangalorePipelineTests(unittest.TestCase):
    def test_tiles_are_safe_complete_and_gap_free(self):
        tiles = list(pipeline.bbox_tiles(pipeline.BBOX))
        self.assertEqual(len(tiles), 12)
        self.assertLess(max((tile[2] - tile[0]) * (tile[3] - tile[1]) for tile in tiles), 0.0081)
        self.assertLess(max((tile[2] - tile[0]) * (tile[3] - tile[1]) for tile in tiles), 0.010)
        self.assertEqual(min(tile[0] for tile in tiles), pipeline.BBOX[0])
        self.assertEqual(max(tile[2] for tile in tiles), pipeline.BBOX[2])
        self.assertEqual(min(tile[1] for tile in tiles), pipeline.BBOX[1])
        self.assertEqual(max(tile[3] for tile in tiles), pipeline.BBOX[3])
        longitudes = sorted({pipeline.BBOX[0], pipeline.BBOX[2], *(edge for tile in tiles for edge in (tile[0], tile[2]))})
        latitudes = sorted({pipeline.BBOX[1], pipeline.BBOX[3], *(edge for tile in tiles for edge in (tile[1], tile[3]))})
        self.assertEqual(longitudes, [74.78, 74.86, 74.94, 75.02, 75.05])
        self.assertEqual(latitudes, [12.8, 12.88, 12.96, 13.0])
        for left, right in zip(longitudes, longitudes[1:]):
            self.assertTrue(any(tile[0] == left and tile[2] == right for tile in tiles))
        for bottom, top in zip(latitudes, latitudes[1:]):
            self.assertTrue(any(tile[1] == bottom and tile[3] == top for tile in tiles))

    def test_coordinates_outside_full_bbox_are_rejected(self):
        self.assertTrue(pipeline.valid_point([74.80, 12.81]))
        self.assertFalse(pipeline.valid_point([75.050001, 12.81]))
        self.assertFalse(pipeline.valid_point([74.80, 12.799999]))

    def test_pagination_cursor_and_next_url(self):
        self.assertEqual(pipeline.after_from_paging({"cursors": {"after": "abc"}}), "abc")
        self.assertEqual(pipeline.after_from_paging({"next": "https://graph.mapillary.com/images?after=xyz"}), "xyz")
        self.assertIsNone(pipeline.after_from_paging({}))

    def test_inventory_discovery_deduplicates_and_persists(self):
        pages = iter([
            [{"id": "1", "computed_geometry": {"type": "Point", "coordinates": [74.81, 12.90]}, "captured_at": 1, "thumb_1024_url": "url-1"}],
            [{"id": "1", "computed_geometry": {"type": "Point", "coordinates": [74.81, 12.90]}, "captured_at": 1, "thumb_1024_url": "url-1"}, {"id": "2", "computed_geometry": {"type": "Point", "coordinates": [74.82, 12.91]}, "captured_at": 2, "thumb_1024_url": "url-2"}],
        ])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            with patch.object(pipeline, "bbox_tiles", return_value=[(74.8, 12.9, 74.83, 12.93)]), patch.object(pipeline, "iter_image_pages", side_effect=lambda token, tile: pages):
                inventory = pipeline.discover_inventory("token", output)
            self.assertEqual(len(inventory["images"]), 2)
            self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))["images"]), 2)

    def test_pagination_is_independent_per_tile_and_completed_tiles_are_skipped(self):
        tiles = [(74.78, 12.80, 74.86, 12.88), (74.86, 12.80, 74.94, 12.88)]
        calls = []

        def pages(_token, tile):
            calls.append(tile)
            if tile == tiles[0]:
                yield [{"id": "same", "computed_geometry": {"coordinates": [74.80, 12.81]}, "thumb_1024_url": "one"}]
                yield [{"id": "same", "computed_geometry": {"coordinates": [74.80, 12.81]}, "thumb_1024_url": "one"}]
            else:
                yield [{"id": "same", "computed_geometry": {"coordinates": [74.80, 12.81]}, "thumb_1024_url": "one"}, {"id": "two", "computed_geometry": {"coordinates": [74.90, 12.81]}, "thumb_1024_url": "two"}]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            with patch.object(pipeline, "bbox_tiles", return_value=tiles), patch.object(pipeline, "iter_image_pages", side_effect=pages):
                inventory = pipeline.discover_inventory("token", output)
                self.assertEqual(len(inventory["images"]), 2)
                self.assertEqual(inventory["discovery_pages"], 3)
                self.assertEqual([state["status"] for state in inventory["discovery_tiles"]], ["completed", "completed"])
                calls.clear()
                pipeline.discover_inventory("token", output)
            self.assertEqual(calls, [])

    def test_failed_tile_is_recorded_and_retried_without_losing_completed_inventory(self):
        tiles = [(74.78, 12.80, 74.86, 12.88), (74.86, 12.80, 74.94, 12.88)]
        attempts = {tiles[1]: 0}

        def pages(_token, tile):
            if tile == tiles[0]:
                yield [{"id": "kept", "computed_geometry": {"coordinates": [74.80, 12.81]}, "thumb_1024_url": "kept"}]
                return
            attempts[tile] += 1
            if attempts[tile] == 1:
                raise RuntimeError("synthetic tile failure")
            yield [{"id": "recovered", "computed_geometry": {"coordinates": [74.90, 12.81]}, "thumb_1024_url": "recovered"}]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            with patch.object(pipeline, "bbox_tiles", return_value=tiles), patch.object(pipeline, "iter_image_pages", side_effect=pages):
                first = pipeline.discover_inventory("token", output)
                self.assertEqual([image["image_id"] for image in first["images"]], ["kept"])
                self.assertEqual(first["discovery_tiles"][0]["status"], "completed")
                self.assertEqual(first["discovery_tiles"][1]["status"], "failed")
                second = pipeline.discover_inventory("token", output)
            self.assertEqual({image["image_id"] for image in second["images"]}, {"kept", "recovered"})
            self.assertEqual(second["discovery_tiles"][0]["status"], "completed")
            self.assertEqual(second["discovery_tiles"][1]["status"], "completed")

    def test_resume_skips_analyzed_and_skips_missing_thumbnail(self):
        inventory = {"images": [
            {"image_id": "done", "ai_status": "analyzed", "thumbnail_url": "url", "longitude": 74.81, "latitude": 12.90},
            {"image_id": "interrupted", "ai_status": "processing", "thumbnail_url": "url", "longitude": 74.81, "latitude": 12.90},
            {"image_id": "missing", "ai_status": "pending", "longitude": 74.81, "latitude": 12.90},
            {"image_id": "pending", "ai_status": "pending", "thumbnail_url": "url", "longitude": 74.81, "latitude": 12.90},
        ]}
        candidates = pipeline.image_candidates(inventory)
        self.assertEqual([item["image_id"] for item in candidates], ["interrupted", "pending"])
        self.assertEqual(inventory["images"][2]["ai_status"], "skipped_with_reason")
        self.assertEqual(inventory["images"][1]["ai_status"], "pending")

    def test_zero_findings_and_quota_marker_are_safe(self):
        self.assertEqual(pipeline.make_ai_features({"image_id": "1", "longitude": 74.81, "latitude": 12.90}, [], []), [])
        self.assertTrue(pipeline.is_quota_error(Exception("429 resource exhausted")))

    def test_coverage_report_distinguishes_pending_and_zero_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            inventory_path = directory / "inventory.json"
            evidence_path = directory / "evidence.json"
            report_path = directory / "coverage.json"
            inventory_path.write_text(json.dumps({"bbox": list(pipeline.BBOX), "images": [
                {"image_id": "a", "ai_status": "analyzed", "findings_count": 0},
                {"image_id": "b", "ai_status": "pending"},
                {"image_id": "c", "ai_status": "quota_blocked"},
            ]}), encoding="utf-8")
            evidence_path.write_text(json.dumps({"features": []}), encoding="utf-8")
            with patch.object(pipeline, "EVIDENCE_FILE", evidence_path), patch.object(pipeline, "COVERAGE_REPORT", report_path):
                report = pipeline.coverage_report(inventory_path)
            self.assertEqual(report["total_images_discovered"], 3)
            self.assertEqual(report["images_analyzed_with_zero_findings"], 1)
            self.assertEqual(report["images_pending"], 1)
            self.assertEqual(report["images_blocked_by_quota"], 1)
            self.assertEqual(report["analysis_completion_percentage"], 33.33)


if __name__ == "__main__":
    unittest.main()
