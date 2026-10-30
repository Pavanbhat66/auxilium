"""Fetch Mapillary imagery and accessibility-relevant detections for Mangalore.

The access token is read from MAPILLARY_ACCESS_TOKEN and is never written to
the output. Results are evidence points only; they are not verified route
accessibility claims.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests


CITY = "mangalore"
BBOX = (74.78, 12.80, 75.05, 13.00)  # west, south, east, north
TILE_SIZE_DEGREES = 0.02  # Keep each request small enough for dense city areas.
MAX_IMAGES = 200  # Initial Mangalore import cap; increase after the first review.
MAX_WORKERS = 6
GRAPH_URL = "https://graph.mapillary.com"
OUTPUT_FILE = Path(__file__).parent / "output" / "mangalore_mapillary_accessibility.geojson"

# Keep this intentionally conservative. Unknown detections remain available in
# raw_value, but only likely accessibility-related values become evidence.
KEYWORDS = {
    "stairs": "stairs",
    "step": "stairs",
    "ramp": "ramp",
    "curb": "curb",
    "sidewalk": "sidewalk",
    "obstacle": "obstacle",
    "construction": "construction",
    "barrier": "barrier",
    "crossing": "crossing",
    "wheelchair": "wheelchair",
}


def api_get(path, token, **params):
    params["access_token"] = token
    response = requests.get(
        f"{GRAPH_URL}/{path.lstrip('/')}",
        params=params,
        headers={"User-Agent": "AUXILIUM-AccessibilityResearch/1.0"},
        timeout=45,
    )
    if not response.ok:
        raise requests.HTTPError(
            f"Mapillary API returned HTTP {response.status_code}: {response.text[:300]}"
        )
    return response.json()


def evidence_label(raw_value):
    value = (raw_value or "").lower()
    for keyword, label in KEYWORDS.items():
        if keyword in value:
            return label
    return None


def image_point(image):
    geometry = image.get("computed_geometry") or image.get("geometry")
    if not geometry or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates", [])
    if len(coordinates) != 2:
        return None
    return coordinates


def bbox_tiles(bbox):
    west, south, east, north = bbox
    longitude = west
    while longitude < east:
        latitude = south
        tile_east = min(longitude + TILE_SIZE_DEGREES, east)
        while latitude < north:
            tile_north = min(latitude + TILE_SIZE_DEGREES, north)
            yield longitude, latitude, tile_east, tile_north
            latitude = tile_north
        longitude = tile_east


def fetch_tile_images(tile, token):
    return api_get(
        "images",
        token,
        bbox=",".join(str(value) for value in tile),
        fields="id,computed_geometry,captured_at,sequence,compass_angle,thumb_1024_url",
        limit=100,
    ).get("data", [])


def fetch_images(token):
    images_by_id = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_tile_images, tile, token) for tile in bbox_tiles(BBOX)]
        for future in as_completed(futures):
            try:
                for image in future.result():
                    images_by_id[image["id"]] = image
                    if len(images_by_id) >= MAX_IMAGES:
                        return list(images_by_id.values())[:MAX_IMAGES]
            except requests.RequestException as error:
                print(f"Skipping one Mangalore tile: {error}")
    return list(images_by_id.values())[:MAX_IMAGES]


def fetch_image_detections(image, token):
    try:
        return image, api_get(
            f"{image['id']}/detections",
            token,
            fields="id,value,created_at,geometry,image",
        ).get("data", [])
    except requests.RequestException as error:
        print(f"Skipping detections for one image: {error}")
        return image, []


def main():
    token = os.getenv("MAPILLARY_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set MAPILLARY_ACCESS_TOKEN before running this script.")

    images = fetch_images(token)

    features = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        detection_jobs = [executor.submit(fetch_image_detections, image, token) for image in images]
        detection_results = [job.result() for job in as_completed(detection_jobs)]

    for image, detections in detection_results:
        point = image_point(image)
        if not point:
            continue

        for detection in detections:
            raw_value = detection.get("value", "")
            label = evidence_label(raw_value)
            if not label:
                continue
            features.append({
                "type": "Feature",
                "id": f"mapillary_detection_{detection.get('id', image['id'])}",
                "geometry": {"type": "Point", "coordinates": point},
                "properties": {
                    "city": CITY,
                    "source": "mapillary",
                    "mapillary_image_id": image["id"],
                    "mapillary_detection_id": detection.get("id"),
                    "captured_at": image.get("captured_at"),
                    "sequence_id": image.get("sequence"),
                    "thumbnail_url": image.get("thumb_1024_url"),
                    "evidence_type": label,
                    "raw_value": raw_value,
                    "verification_status": "needs_review",
                    "accessibility_claim": "unknown",
                },
            })

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "city": CITY,
            "bbox": BBOX,
            "source": "mapillary",
            "note": "Evidence only. Review before using for accessible routing.",
        },
    }, indent=2), encoding="utf-8")
    print(f"Images scanned: {len(images)}")
    print(f"Accessibility evidence points: {len(features)}")
    print(f"GeoJSON saved to: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
