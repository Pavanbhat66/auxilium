import sys
import unittest
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE_DIR))

import extract_osm  # noqa: E402


class FakeResponse:
    content = b'''<osm version="0.6">
      <node id="1" lat="12.9000" lon="74.8100" />
      <node id="2" lat="12.9000" lon="74.8110" />
      <node id="3" lat="12.9000" lon="74.8120" />
      <way id="77"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way>
      <way id="88"><nd ref="2"/><nd ref="3"/><tag k="building" v="yes"/></way>
    </osm>'''

    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, *_args, **_kwargs):
        return FakeResponse()


class ExtractOsmTests(unittest.TestCase):
    def test_osm_api_tile_preserves_only_eligible_ways_and_geometry(self):
        elements = extract_osm.fetch_osm_api_tile((74.81, 12.90, 74.82, 12.91), FakeSession())
        self.assertEqual([element["id"] for element in elements], [77])
        self.assertEqual(elements[0]["geometry"][0], {"lon": 74.81, "lat": 12.9})

    def test_bbox_tiles_cover_requested_evidence_area(self):
        tiles = list(extract_osm.bbox_tiles((74.80, 12.89, 74.83, 12.92), 0.01))
        self.assertEqual(len(tiles), 9)
        self.assertEqual((min(tile[0] for tile in tiles), min(tile[1] for tile in tiles)), (74.8, 12.89))
        self.assertEqual((max(tile[2] for tile in tiles), max(tile[3] for tile in tiles)), (74.83, 12.92))


if __name__ == "__main__":
    unittest.main()
