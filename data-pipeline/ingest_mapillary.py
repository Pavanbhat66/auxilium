"""Fetch Mapillary imagery and accessibility-relevant detections for Mangalore.

The access token is read from MAPILLARY_ACCESS_TOKEN and is never written to
the output. Results are evidence points only; they are not verified route
accessibility claims.
"""

import json
import math
import os
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = Path(__file__).resolve().parent
load_dotenv(PIPELINE_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")


CITY = "mangalore"
BBOX = (74.78, 12.80, 75.05, 13.00)  # west, south, east, north
TILE_SIZE_DEGREES = 0.02  # Keep each request small enough for dense city areas.
MAX_IMAGES = 200  # Initial Mangalore import cap; increase after the first review.
MAX_WORKERS = 6
GRAPH_URL = "https://graph.mapillary.com"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
OUTPUT_FILE = Path(__file__).parent / "output" / "mangalore_mapillary_accessibility.geojson"
OSM_PATHS_FILE = Path(__file__).parent / "output" / "pedestrian_paths.geojson"

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


def distance_meters(point_a, point_b):
    """Approximate distance between [lon, lat] points."""
    earth_radius = 6371000
    lon_a, lat_a = point_a
    lon_b, lat_b = point_b
    latitude_delta = (lat_b - lat_a) * 3.141592653589793 / 180
    longitude_delta = (lon_b - lon_a) * 3.141592653589793 / 180
    average_latitude = (lat_a + lat_b) * 3.141592653589793 / 360
    x = longitude_delta * __import__("math").cos(average_latitude)
    y = latitude_delta
    return earth_radius * (x * x + y * y) ** 0.5


def load_osm_paths():
    if not OSM_PATHS_FILE.exists():
        return []
    try:
        return json.loads(OSM_PATHS_FILE.read_text(encoding="utf-8")).get("features", [])
    except (OSError, json.JSONDecodeError):
        return []


def point_to_segment_distance_meters(point, segment_start, segment_end):
    """Distance from a lon/lat point to a LineString segment in local meters."""
    earth_radius = 6371000
    latitude_origin = point[1] * 3.141592653589793 / 180

    def project(coordinate):
        longitude_delta = (coordinate[0] - point[0]) * 3.141592653589793 / 180
        latitude_delta = (coordinate[1] - point[1]) * 3.141592653589793 / 180
        return (
            earth_radius * longitude_delta * __import__("math").cos(latitude_origin),
            earth_radius * latitude_delta,
        )

    start_x, start_y = project(segment_start)
    end_x, end_y = project(segment_end)
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return (start_x * start_x + start_y * start_y) ** 0.5
    projection = -(start_x * delta_x + start_y * delta_y) / length_squared
    projection = max(0, min(1, projection))
    closest_x = start_x + projection * delta_x
    closest_y = start_y + projection * delta_y
    return (closest_x * closest_x + closest_y * closest_y) ** 0.5


def nearest_path_id(point, paths, max_distance_meters=50):
    nearest_id = None
    nearest_distance = float("inf")
    for path in paths:
        coordinates = path.get("geometry", {}).get("coordinates", [])
        for index in range(len(coordinates) - 1):
            distance = point_to_segment_distance_meters(point, coordinates[index], coordinates[index + 1])
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_id = path.get("properties", {}).get("path_id") or path.get("id")
    return nearest_id if nearest_distance <= max_distance_meters else None


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


def fetch_images(token, max_images=MAX_IMAGES):
    images_by_id = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_tile_images, tile, token) for tile in bbox_tiles(BBOX)]
        for future in as_completed(futures):
            try:
                for image in future.result():
                    images_by_id[image["id"]] = image
                    if len(images_by_id) >= max_images:
                        return list(images_by_id.values())[:max_images]
            except requests.RequestException as error:
                print(f"Skipping one Mangalore tile: {error}")
    return list(images_by_id.values())[:max_images]


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


AI_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "feature_name": {
                        "type": "string",
                        "enum": ["stairs", "ramp", "curb", "dropped_curb", "tactile_paving", "obstacle", "surface", "other"],
                    },
                    "predicted_value": {
                        "type": "string",
                        "enum": ["present", "smooth", "uneven", "damaged", "unknown"],
                    },
                    "confidence": {"type": "number"},
                    "visual_explanation": {"type": "string"},
                },
                "required": ["feature_name", "predicted_value", "confidence", "visual_explanation"],
            },
        },
    },
    "required": ["findings"],
}


AI_INSTRUCTIONS = """You analyze one Mapillary street-level image for accessibility evidence.
Return only the requested structured JSON. Inspect only what is visibly supported by the image.
Analyze stairs, ramps, curbs or dropped curbs, tactile paving, pedestrian obstacles, and visible
surface conditions. Use predicted_value=present only when the feature is visibly present. Use
unknown when it is not visible, ambiguous, blocked, or cannot be reliably identified. For an
unknown finding, explain the visibility limitation; do not state that the feature is absent. Never
infer that a feature is absent merely because it is not detected. Confidence must be between 0 and 1.
This is evidence for human review, not a final accessibility certification."""


def is_quota_error(error):
    text = str(error).lower()
    return any(marker in text for marker in ("429", "resource_exhausted", "quota", "rate limit", "too many requests"))


ALLOWED_FEATURE_NAMES = {"stairs", "ramp", "curb", "dropped_curb", "tactile_paving", "obstacle", "surface", "other"}
ALLOWED_PREDICTED_VALUES = {"present", "smooth", "uneven", "damaged", "unknown"}


def normalize_findings(findings):
    if not isinstance(findings, list):
        raise ValueError("Gemini response findings must be an array.")
    normalized = []
    seen = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        feature_name = finding.get("feature_name", "other")
        if feature_name not in ALLOWED_FEATURE_NAMES:
            feature_name = "other"
        predicted_value = finding.get("predicted_value", "unknown")
        if predicted_value not in ALLOWED_PREDICTED_VALUES:
            predicted_value = "unknown"
        try:
            confidence = float(finding.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        if not math.isfinite(confidence):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        key = (feature_name, predicted_value)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "feature_name": feature_name,
            "predicted_value": predicted_value,
            "confidence": confidence,
            "visual_explanation": str(finding.get("visual_explanation", "")),
        })
    return normalized


def load_existing_gemini_features():
    if not OUTPUT_FILE.exists():
        return []


def load_existing_features():
    if not OUTPUT_FILE.exists():
        return []
    try:
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8")).get("features", [])
    except (OSError, json.JSONDecodeError):
        return []
    try:
        features = json.loads(OUTPUT_FILE.read_text(encoding="utf-8")).get("features", [])
        return [feature for feature in features if feature.get("properties", {}).get("source") == "gemini_ai"]
    except (OSError, json.JSONDecodeError):
        return []


def load_inspection_features(path):
    if not path:
        return []
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        return [feature for feature in report.get("features", []) if feature.get("properties", {}).get("source") == "gemini_ai"]
    except (OSError, json.JSONDecodeError):
        return []


def analyze_image_with_gemini(image, client, model):
    from google.genai import types

    image_url = image.get("thumb_1024_url")
    if not image_url:
        return []
    image_response = requests.get(
        image_url,
        headers={"User-Agent": "AUXILIUM-AccessibilityResearch/1.0"},
        timeout=45,
    )
    image_response.raise_for_status()
    mime_type = image_response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
    response = client.models.generate_content(
        model=model,
        contents=[
            AI_INSTRUCTIONS,
            types.Part.from_bytes(data=image_response.content, mime_type=mime_type),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AI_SCHEMA,
            temperature=0.1,
            max_output_tokens=700,
        ),
    )
    if not response.text:
        return []
    parsed = json.loads(response.text)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini response must be a JSON object.")
    return normalize_findings(parsed.get("findings", []))


def ai_features(images, relevant_image_ids, paths, client, model, max_images, existing_ai_ids, force_one_image=False):
    analyze_all = os.getenv("AUXILIUM_AI_ANALYZE_ALL", "0").lower() in ("1", "true", "yes")
    if force_one_image:
        eligible = [
            image for image in images
            if image.get("thumb_1024_url") and image["id"] not in existing_ai_ids
        ][:1]
    else:
        eligible = [
            image for image in images
            if image.get("thumb_1024_url")
            and image["id"] not in existing_ai_ids
            and (analyze_all or image["id"] in relevant_image_ids)
        ][:max_images]
    features = []
    successful_images = 0
    failed_images = 0
    quota_exhausted = False
    for index, image in enumerate(eligible, start=1):
        try:
            findings = analyze_image_with_gemini(image, client, model)
            successful_images += 1
        except Exception as error:
            failed_images += 1
            print(f"Skipping Gemini analysis for image {image['id']}: {error}")
            if is_quota_error(error):
                quota_exhausted = True
                print("Gemini quota or rate limit reached; stopping AI analysis without retrying.")
                break
            continue
        point = image_point(image)
        if not point:
            continue
        path_id = nearest_path_id(point, paths)
        for finding_index, finding in enumerate(findings):
            confidence = max(0, min(1, float(finding.get("confidence", 0))))
            features.append({
                "type": "Feature",
                "id": f"mapillary_ai_{image['id']}_{finding_index}",
                "geometry": {"type": "Point", "coordinates": point},
                "properties": {
                    "city": CITY,
                    "source": "gemini_ai",
                    "mapillary_image_id": image["id"],
                    "captured_at": image.get("captured_at"),
                    "sequence_id": image.get("sequence"),
                    "path_id": path_id,
                    "feature_name": finding.get("feature_name", "other"),
                    "predicted_value": finding.get("predicted_value", "unknown"),
                    "evidence_type": finding.get("feature_name", "other"),
                    "raw_value": finding.get("predicted_value", "unknown"),
                    "confidence": confidence,
                    "visual_explanation": finding.get("visual_explanation", ""),
                    "model": model,
                    "verification_status": "needs_review",
                    "accessibility_claim": "unknown",
                },
            })
        print(f"AI analyzed {index}/{len(eligible)} eligible images")
    return features, successful_images, failed_images, quota_exhausted


def main():
    parser = argparse.ArgumentParser(description="Collect Mapillary accessibility evidence for Mangalore.")
    parser.add_argument("--ai", action="store_true", help="Run Gemini vision analysis when GEMINI_API_KEY is set.")
    parser.add_argument("--max-images", type=int, help="Override GEMINI_MAX_IMAGES for this run.")
    parser.add_argument("--image-limit", type=int, help="Limit Mapillary images retrieved for this run.")
    parser.add_argument("--force-ai-image", action="store_true", help="Test Gemini on exactly one retrieved image, regardless of Mapillary detections.")
    parser.add_argument("--inspection-file", help="Write a separate JSON inspection report for AI results.")
    parser.add_argument("--import-inspection-file", help="Include validated Gemini records from a separate inspection report.")
    parser.add_argument("--no-write", action="store_true", help="Run collection and analysis without changing the GeoJSON output.")
    args = parser.parse_args()
    token = os.getenv("MAPILLARY_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set MAPILLARY_ACCESS_TOKEN before running this script.")

    images = fetch_images(token, args.image_limit or MAX_IMAGES)
    paths = load_osm_paths()

    existing_features = load_existing_features()
    existing_gemini_features = [
        feature for feature in existing_features
        if feature.get("properties", {}).get("source") == "gemini_ai"
    ]
    imported_gemini_features = load_inspection_features(args.import_inspection_file)
    existing_gemini_features.extend(imported_gemini_features)
    existing_ai_ids = {
        feature.get("properties", {}).get("mapillary_image_id")
        for feature in existing_gemini_features
    }
    features = list(existing_features)
    existing_feature_ids = {feature.get("id") for feature in features}
    for feature in imported_gemini_features:
        if feature.get("id") not in existing_feature_ids:
            features.append(feature)
            existing_feature_ids.add(feature.get("id"))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        detection_jobs = [executor.submit(fetch_image_detections, image, token) for image in images]
        detection_results = [job.result() for job in as_completed(detection_jobs)]

    relevant_image_ids = set()
    for image, detections in detection_results:
        point = image_point(image)
        if not point:
            continue

        for detection in detections:
            raw_value = detection.get("value", "")
            label = evidence_label(raw_value)
            if not label:
                continue
            relevant_image_ids.add(image["id"])
            feature_id = f"mapillary_detection_{detection.get('id', image['id'])}"
            if feature_id in existing_feature_ids:
                continue
            features.append({
                "type": "Feature",
                "id": feature_id,
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
            existing_feature_ids.add(feature_id)

    ai_key = os.getenv("GEMINI_API_KEY")
    ai_model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    ai_features_list = []
    ai_successful_images = 0
    ai_failed_images = 0
    ai_quota_exhausted = False
    if args.ai:
        if not ai_key:
            raise SystemExit("--ai requires GEMINI_API_KEY in data-pipeline/.env or the environment.")
        try:
            from google import genai
            gemini_client = genai.Client(api_key=ai_key)
            model_info = gemini_client.models.get(model=ai_model)
            supported_actions = getattr(model_info, "supported_actions", []) or []
            if supported_actions and "generateContent" not in supported_actions:
                raise RuntimeError(f"Gemini model {ai_model} does not support generateContent.")
            print(f"Gemini model verified: {ai_model}")
        except Exception as error:
            print(f"Gemini model verification failed for {ai_model}: {error}")
            return
        ai_features_list, ai_successful_images, ai_failed_images, ai_quota_exhausted = ai_features(
            images,
            relevant_image_ids,
            paths,
            gemini_client,
            ai_model,
            1 if args.force_ai_image else (args.max_images or int(os.getenv("GEMINI_MAX_IMAGES", "25"))),
            existing_ai_ids,
            force_one_image=args.force_ai_image,
        )
        features.extend(ai_features_list)

    if args.inspection_file:
        inspection_path = Path(args.inspection_file)
        inspection_path.parent.mkdir(parents=True, exist_ok=True)
        inspection_path.write_text(json.dumps({
            "model": ai_model if args.ai else None,
            "images_retrieved": len(images),
            "images_analyzed": ai_successful_images,
            "images_failed": ai_failed_images,
            "quota_exhausted": ai_quota_exhausted,
            "features": ai_features_list,
        }, indent=2), encoding="utf-8")
        print(f"AI inspection report saved to: {inspection_path.resolve()}")

    output = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "city": CITY,
            "bbox": BBOX,
            "source": "mapillary",
            "ai_provider": "google_gemini" if args.ai else None,
            "ai_model": ai_model if args.ai else None,
            "ai_images_analyzed": ai_successful_images,
            "ai_images_failed": ai_failed_images,
            "ai_quota_exhausted": ai_quota_exhausted,
            "note": "Evidence only. Review before using for accessible routing.",
        },
    }
    if not args.no_write:
        OUTPUT_FILE.parent.mkdir(exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Images retrieved: {len(images)}")
    print(f"Gemini images successfully analysed: {ai_successful_images}")
    print(f"Gemini failed analyses: {ai_failed_images}")
    print(f"Existing Mapillary detection evidence: {sum(1 for feature in features if feature.get('properties', {}).get('source') == 'mapillary')}")
    print(f"Evidence records generated: {len(features)}")
    print(f"GeoJSON saved to: {OUTPUT_FILE.resolve()}" if not args.no_write else "GeoJSON write skipped (--no-write)")


if __name__ == "__main__":
    main()
