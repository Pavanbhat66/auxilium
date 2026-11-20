"""Extract OSM pedestrian-related ways for the AUXILIUM Mangalore area."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import time

import requests


OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "pedestrian_paths.geojson"
DEFAULT_OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"
DEFAULT_GEOFABRIK_URL = "https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf"
DEFAULT_PBF_FILE = Path(__file__).resolve().parent / "cache" / "southern-zone-latest.osm.pbf"
USER_AGENT = "AUXILIUM-AccessibilityResearch/1.0 (student project)"

# Same coverage as ingest_mapillary.py: west, south, east, north.
DEFAULT_BBOX = (74.78, 12.80, 75.05, 13.00)
DEFAULT_TILE_SIZE = 0.05
REQUEST_DELAY_SECONDS = 1.0
REQUEST_CONNECT_TIMEOUT_SECONDS = 20
REQUEST_READ_TIMEOUT_SECONDS = 120

# Include dedicated pedestrian ways and roads that can carry pedestrian access.
HIGHWAY_VALUES = "footway|path|pedestrian|steps|service|living_street|residential|cycleway|track"


def bbox_tiles(bbox, tile_size):
    west, south, east, north = bbox
    longitude = west
    while longitude < east:
        latitude = south
        tile_east = min(longitude + tile_size, east)
        while latitude < north:
            tile_north = min(latitude + tile_size, north)
            yield (longitude, latitude, tile_east, tile_north)
            latitude = tile_north
        longitude = tile_east


def overpass_query(tile):
    west, south, east, north = tile
    return f"""
[out:json][timeout:90];
(
  way["highway"~"^({HIGHWAY_VALUES})$"]({south},{west},{north},{east});
  way["sidewalk"]({south},{west},{north},{east});
);
out geom;
"""


def parse_bbox(value):
    try:
        parts = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("bbox must be west,south,east,north") from error
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be west,south,east,north")
    west, south, east, north = parts
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise argparse.ArgumentTypeError("bbox coordinates are invalid")
    return parts


def fetch_tile(tile, session, overpass_url):
    response = session.post(
        overpass_url,
        data={"data": overpass_query(tile)},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=(REQUEST_CONNECT_TIMEOUT_SECONDS, REQUEST_READ_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    return response.json().get("elements", [])


def element_to_feature(element):
    if element.get("type") != "way":
        return None
    geometry = element.get("geometry", [])
    if len(geometry) < 2:
        return None
    tags = element.get("tags", {})
    coordinates = [[point["lon"], point["lat"]] for point in geometry]
    properties = {
        "path_id": f"osm_way_{element['id']}",
        "highway": tags.get("highway", "unknown"),
        "surface": tags.get("surface", "unknown"),
        "incline": tags.get("incline", "unknown"),
        "stairs": "yes" if tags.get("highway") == "steps" else "unknown",
        "ramp": tags.get("ramp", "unknown"),
        "wheelchair_access": tags.get("wheelchair", "unknown"),
        "sidewalk": tags.get("sidewalk", "unknown"),
        "crossing": tags.get("crossing", "unknown"),
        "kerb": tags.get("kerb", "unknown"),
        "smoothness": tags.get("smoothness", "unknown"),
        "tactile_paving": tags.get("tactile_paving", "unknown"),
        "source": "openstreetmap",
        "verification_status": "unverified",
        "osm_tags": tags,
    }
    return {
        "type": "Feature",
        "id": properties["path_id"],
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": properties,
    }


def download_pbf(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        head = session.head(url, headers={"User-Agent": USER_AGENT}, allow_redirects=True, timeout=(20, 30))
        head.raise_for_status()
        expected_size = int(head.headers.get("Content-Length", "0"))
        if destination.exists() and (not expected_size or destination.stat().st_size == expected_size):
            print(f"Using cached Geofabrik PBF: {destination.resolve()} ({destination.stat().st_size} bytes)")
            return destination.stat().st_size

        partial = destination.with_suffix(destination.suffix + ".part")
        with session.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=(20, 300)) as response:
            response.raise_for_status()
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
        actual_size = partial.stat().st_size
        if expected_size and actual_size != expected_size:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"PBF size mismatch: expected {expected_size}, received {actual_size}")
        partial.replace(destination)
        print(f"Downloaded Geofabrik PBF: {destination.resolve()} ({actual_size} bytes)")
        return actual_size


def extract_geofabrik(bbox, pbf_url, pbf_file):
    try:
        import osmium
    except ImportError as error:
        raise RuntimeError("The osmium package is required for Geofabrik PBF extraction.") from error

    pbf_size = download_pbf(pbf_url, pbf_file)
    west, south, east, north = bbox
    elements_by_id = {}

    class PedestrianWayHandler(osmium.SimpleHandler):
        def way(self, way):
            tags = dict(way.tags)
            if "sidewalk" not in tags and tags.get("highway") not in set(HIGHWAY_VALUES.split("|")):
                return
            coordinates = []
            for node in way.nodes:
                if not node.location.valid():
                    return
                coordinates.append([node.location.lon, node.location.lat])
            if len(coordinates) < 2 or not any(
                west <= coordinate[0] <= east and south <= coordinate[1] <= north
                for coordinate in coordinates
            ):
                return
            elements_by_id[way.id] = {"type": "way", "id": way.id, "tags": tags, "geometry": [
                {"lon": coordinate[0], "lat": coordinate[1]} for coordinate in coordinates
            ]}

    handler = PedestrianWayHandler()
    handler.apply_file(str(pbf_file), locations=True)
    features = [element_to_feature(element) for element in elements_by_id.values()]
    features = [feature for feature in features if feature]
    features.sort(key=lambda feature: feature["id"])
    return features, pbf_size


def backup_output():
    if not OUTPUT_FILE.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = OUTPUT_FILE.with_name(f"{OUTPUT_FILE.stem}.backup-{stamp}{OUTPUT_FILE.suffix}")
    shutil.copy2(OUTPUT_FILE, backup)
    return backup


def main():
    parser = argparse.ArgumentParser(description="Extract Mangalore pedestrian-related OSM ways.")
    parser.add_argument("--bbox", type=parse_bbox, default=DEFAULT_BBOX, help="west,south,east,north")
    parser.add_argument("--tile-size", type=float, default=DEFAULT_TILE_SIZE, help="Tile size in degrees.")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_SECONDS, help="Delay between Overpass requests.")
    parser.add_argument("--overpass-url", default=DEFAULT_OVERPASS_URL, help="Overpass API interpreter URL.")
    parser.add_argument("--source", choices=("overpass", "geofabrik"), default="overpass")
    parser.add_argument("--pbf-url", default=DEFAULT_GEOFABRIK_URL, help="Geofabrik PBF URL.")
    parser.add_argument("--pbf-file", type=Path, default=DEFAULT_PBF_FILE, help="Local PBF cache path.")
    args = parser.parse_args()
    if args.tile_size <= 0:
        raise SystemExit("--tile-size must be greater than zero.")
    if args.delay < 0:
        raise SystemExit("--delay cannot be negative.")

    print(f"Extracting OSM pedestrian ways for bbox: {args.bbox}")
    failures = []
    pbf_size = None
    tiles = []
    if args.source == "geofabrik":
        features, pbf_size = extract_geofabrik(args.bbox, args.pbf_url, args.pbf_file)
    else:
        tiles = list(bbox_tiles(args.bbox, args.tile_size))
        print(f"Tiles to process: {len(tiles)}")
        elements_by_id = {}
        with requests.Session() as session:
            for index, tile in enumerate(tiles, start=1):
                try:
                    elements = fetch_tile(tile, session, args.overpass_url)
                    for element in elements:
                        if element.get("type") == "way":
                            elements_by_id[element["id"]] = element
                    print(f"Tile {index}/{len(tiles)}: {len(elements)} elements, {len(elements_by_id)} unique ways")
                except (requests.RequestException, ValueError) as error:
                    failures.append({"tile": tile, "error": str(error)})
                    print(f"Tile {index}/{len(tiles)} failed: {error}")
                if index < len(tiles):
                    time.sleep(args.delay)
        features = [element_to_feature(element) for element in elements_by_id.values()]
        features = [feature for feature in features if feature]
        features.sort(key=lambda feature: feature["id"])

    backup = backup_output()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "openstreetmap",
            "bbox": list(args.bbox),
            "extractor": args.source,
            "pbf_url": args.pbf_url if args.source == "geofabrik" else None,
            "pbf_size_bytes": pbf_size,
            "tile_size_degrees": args.tile_size,
            "tiles_processed": len(tiles),
            "tiles_failed": len(failures),
            "failed_tiles": failures,
            "unique_osm_ways": len(features),
        },
    }
    OUTPUT_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Unique pedestrian ways: {len(features)}")
    print(f"Tiles failed: {len(failures)}")
    print(f"GeoJSON saved to: {OUTPUT_FILE.resolve()}")
    if backup:
        print(f"Previous GeoJSON backed up to: {backup.resolve()}")


if __name__ == "__main__":
    main()
