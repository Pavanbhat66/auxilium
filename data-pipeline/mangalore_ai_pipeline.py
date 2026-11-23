"""Resumable Mangalore Mapillary inventory and Gemini analysis workflow."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.parse import parse_qs, urlparse

import requests

from accessibility_quality import (
    EVIDENCE_FILE,
    MATCH_THRESHOLD_METERS,
    build_matching_report,
    nearest_path,
    read_json,
    write_json,
)
from ingest_mapillary import (
    BBOX,
    GRAPH_URL,
    MAX_WORKERS,
    analyze_image_with_gemini,
    api_get,
    bbox_tiles,
    is_quota_error,
    normalize_findings,
)


OUTPUT_DIR = Path(__file__).resolve().parent / "output"
INVENTORY_FILE = OUTPUT_DIR / "mangalore_image_inventory.json"
COVERAGE_REPORT = OUTPUT_DIR / "mangalore_ai_coverage_report.json"
OSM_FILE = OUTPUT_DIR / "pedestrian_paths.geojson"
USER_AGENT = "AUXILIUM-AccessibilityResearch/1.0"
TRANSIENT_MARKERS = ("429", "408", "500", "502", "503", "504", "timeout", "temporarily", "unavailable", "connection")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def valid_point(coordinates):
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
        return False
    try:
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError):
        return False
    return 74.78 <= longitude <= 75.05 and 12.80 <= latitude <= 13.00


def after_from_paging(paging):
    cursor = (paging.get("cursors") or {}).get("after")
    if cursor:
        return cursor
    next_url = paging.get("next")
    if next_url:
        return parse_qs(urlparse(next_url).query).get("after", [None])[0]
    return None


def is_transient_error(error):
    text = str(error).lower()
    return any(marker in text for marker in TRANSIENT_MARKERS)


def call_with_bounded_retry(function, attempts=3):
    for attempt in range(attempts):
        try:
            return function()
        except Exception as error:
            if attempt == attempts - 1 or is_quota_error(error) or not is_transient_error(error):
                raise
            time.sleep(2 ** attempt)


def iter_image_pages(token, tile):
    after = None
    while True:
        params = {
            "bbox": ",".join(str(value) for value in tile),
            "fields": "id,computed_geometry,captured_at,sequence,compass_angle,thumb_1024_url",
            "limit": 100,
        }
        if after:
            params["after"] = after
        payload = call_with_bounded_retry(lambda: api_get("images", token, **params))
        yield payload.get("data", [])
        next_after = after_from_paging(payload.get("paging", {}))
        if not next_after or next_after == after:
            break
        after = next_after


def load_inventory(path=INVENTORY_FILE):
    path = Path(path)
    if not path.exists():
        return {"bbox": list(BBOX), "images": [], "discovery_failures": [], "discovery_tiles": [], "updated_at": None}
    inventory = read_json(path)
    inventory.setdefault("bbox", list(BBOX))
    inventory.setdefault("images", [])
    inventory.setdefault("discovery_failures", [])
    inventory.setdefault("discovery_tiles", [])
    return inventory


def tile_key(tile):
    return ",".join(f"{float(value):.8f}" for value in tile)


def tile_state_map(inventory, tiles):
    states = {
        str(state.get("tile_key")): state
        for state in inventory.get("discovery_tiles", [])
        if state.get("tile_key")
    }
    for index, tile in enumerate(tiles, start=1):
        key = tile_key(tile)
        states.setdefault(key, {
            "tile_key": key,
            "tile": list(tile),
            "tile_number": index,
            "status": "pending",
            "pages": 0,
            "unique_images": 0,
            "updated_at": None,
        })
        states[key]["tile"] = list(tile)
        states[key]["tile_number"] = index
    return states


def existing_ai_statuses():
    if not EVIDENCE_FILE.exists():
        return {}, {}
    evidence = read_json(EVIDENCE_FILE)
    by_image = defaultdict(list)
    for feature in evidence.get("features", []):
        properties = feature.get("properties", {})
        if properties.get("source") == "gemini_ai" and properties.get("mapillary_image_id"):
            by_image[str(properties["mapillary_image_id"])].append(feature)
    return by_image, evidence


def merge_existing_statuses(inventory):
    by_image, _ = existing_ai_statuses()
    existing_detections = defaultdict(list)
    if EVIDENCE_FILE.exists():
        evidence = read_json(EVIDENCE_FILE)
        for feature in evidence.get("features", []):
            properties = feature.get("properties", {})
            if properties.get("source") == "mapillary" and properties.get("mapillary_image_id"):
                existing_detections[str(properties["mapillary_image_id"])].append({
                    "evidence_id": feature.get("id"),
                    "detection_id": properties.get("mapillary_detection_id"),
                    "evidence_type": properties.get("evidence_type"),
                    "raw_value": properties.get("raw_value"),
                })
    for image in inventory.get("images", []):
        image_id = str(image.get("image_id"))
        image["existing_mapillary_detections"] = existing_detections.get(
            image_id, image.get("existing_mapillary_detections", [])
        )
        if image_id in by_image and image.get("ai_status") != "analyzed":
            image["ai_status"] = "analyzed"
            image["findings_count"] = len(by_image[image_id])
            image["evidence_ids"] = [feature.get("id") for feature in by_image[image_id]]
    return inventory


def discover_inventory(token, inventory_path=INVENTORY_FILE):
    inventory = merge_existing_statuses(load_inventory(inventory_path))
    records = {str(image["image_id"]): image for image in inventory.get("images", []) if image.get("image_id")}
    failures = list(inventory.get("discovery_failures", []))
    pages = 0
    tiles = list(bbox_tiles(BBOX))
    states = tile_state_map(inventory, tiles)
    completed = {key for key, state in states.items() if state.get("status") == "completed"}
    for tile_number, tile in enumerate(tiles, start=1):
        key = tile_key(tile)
        state = states[key]
        if state.get("status") == "completed":
            print(f"Tile {tile_number}/{len(tiles)} already completed; unique images discovered: {len(records)}")
            continue
        state["status"] = "processing"
        state["error"] = None
        state["updated_at"] = utc_now()
        try:
            for page_number, page in enumerate(iter_image_pages(token, tile), start=1):
                pages += 1
                for raw_image in page:
                    point = raw_image.get("computed_geometry") or raw_image.get("geometry")
                    coordinates = point.get("coordinates", []) if point else []
                    if not valid_point(coordinates):
                        continue
                    image_id = str(raw_image["id"])
                    previous = records.get(image_id, {})
                    records[image_id] = {
                        **previous,
                        "image_id": image_id,
                        "longitude": coordinates[0],
                        "latitude": coordinates[1],
                        "captured_at": raw_image.get("captured_at"),
                        "sequence_id": raw_image.get("sequence"),
                        "thumbnail_url": raw_image.get("thumb_1024_url"),
                        "existing_mapillary_detections": previous.get("existing_mapillary_detections", []),
                        "discovery_status": "discovered",
                        "ai_status": previous.get("ai_status", "pending"),
                        "last_processing_attempt": previous.get("last_processing_attempt"),
                        "failure_reason": previous.get("failure_reason"),
                    }
                state["pages"] = page_number
                state["unique_images"] = sum(
                    1 for image in records.values()
                    if valid_point([image.get("longitude"), image.get("latitude")])
                    and tile[0] <= image["longitude"] <= tile[2]
                    and tile[1] <= image["latitude"] <= tile[3]
                )
                state["updated_at"] = utc_now()
                inventory["bbox"] = list(BBOX)
                inventory["images"] = sorted(records.values(), key=lambda image: image["image_id"])
                inventory["discovery_pages"] = pages
                inventory["discovery_tiles"] = sorted(states.values(), key=lambda item: item["tile_number"])
                inventory["discovery_failures"] = failures
                inventory["updated_at"] = utc_now()
                atomic_write_json(inventory_path, inventory)
                print(f"Tile {tile_number}/{len(tiles)}, page {page_number}, unique images discovered: {len(records)}")
            state["status"] = "completed"
            completed.add(key)
            state["updated_at"] = utc_now()
        except Exception as error:
            state["status"] = "failed"
            state["error"] = str(error)
            failure = {"tile": list(tile), "tile_key": key, "tile_number": tile_number, "error": str(error), "recorded_at": utc_now()}
            failures.append(failure)
            print(f"Tile {tile_number}/{len(tiles)} failed; preserving discovered images: {error}")
        state["updated_at"] = utc_now()
        inventory["bbox"] = list(BBOX)
        inventory["images"] = sorted(records.values(), key=lambda image: image["image_id"])
        inventory["discovery_pages"] = pages
        inventory["discovery_tiles"] = sorted(states.values(), key=lambda item: item["tile_number"])
        inventory["discovery_failures"] = failures
        inventory["updated_at"] = utc_now()
        atomic_write_json(inventory_path, inventory)
    return inventory


def image_candidates(inventory, include_detection_filter=False):
    candidates = []
    for image in inventory.get("images", []):
        status = image.get("ai_status", "pending")
        if status == "processing":
            image["ai_status"] = "pending"
            image["failure_reason"] = "recovered after an interrupted processing attempt"
            status = "pending"
        if status == "analyzed":
            continue
        if status in {"quota_blocked", "skipped_with_reason"}:
            continue
        if not image.get("thumbnail_url"):
            image["ai_status"] = "skipped_with_reason"
            image["failure_reason"] = "missing permitted thumbnail URL"
            continue
        if not valid_point([image.get("longitude"), image.get("latitude")]):
            image["ai_status"] = "skipped_with_reason"
            image["failure_reason"] = "coordinates outside configured Mangalore bbox"
            continue
        if include_detection_filter and not image.get("existing_mapillary_detections"):
            continue
        candidates.append(image)
    return candidates


def make_ai_features(image, findings, osm_paths):
    point = [image["longitude"], image["latitude"]]
    matching = nearest_path(point, osm_paths)
    features = []
    for index, finding in enumerate(normalize_findings(findings)):
        features.append({
            "type": "Feature",
            "id": f"mapillary_ai_{image['image_id']}_{index}",
            "geometry": {"type": "Point", "coordinates": point},
            "properties": {
                "city": "mangalore",
                "source": "gemini_ai",
                "mapillary_image_id": image["image_id"],
                "captured_at": image.get("captured_at"),
                "sequence_id": image.get("sequence_id"),
                "path_id": matching.get("matched_path_id"),
                "matching_distance_m": matching.get("nearest_distance_m"),
                "feature_name": finding["feature_name"],
                "predicted_value": finding["predicted_value"],
                "evidence_type": finding["feature_name"],
                "raw_value": finding["predicted_value"],
                "confidence": finding["confidence"],
                "visual_explanation": finding["visual_explanation"],
                "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                "verification_status": "needs_review",
                "accessibility_claim": "unknown",
            },
        })
    return features


def backup_evidence(path=EVIDENCE_FILE):
    path = Path(path)
    if not path.exists():
        return None
    backup = path.with_name(f"{path.stem}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    backup.write_bytes(path.read_bytes())
    return backup


def save_evidence(evidence, path=EVIDENCE_FILE):
    atomic_write_json(path, evidence)


def update_evidence_metadata(evidence):
    features = evidence.get("features", [])
    ai_image_ids = {
        str(feature.get("properties", {}).get("mapillary_image_id"))
        for feature in features
        if feature.get("properties", {}).get("source") == "gemini_ai"
    }
    metadata = evidence.setdefault("metadata", {})
    metadata["ai_provider"] = "google_gemini"
    metadata["ai_model"] = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    metadata["ai_images_analyzed"] = len(ai_image_ids)


def analyze_batch(inventory_path=INVENTORY_FILE, batch_size=1, include_detection_filter=False, dry_run=False):
    inventory = merge_existing_statuses(load_inventory(inventory_path))
    candidates = image_candidates(inventory, include_detection_filter)
    print(f"Images in inventory: {len(inventory.get('images', []))}")
    print(f"Eligible pending images: {len(candidates)}")
    if dry_run:
        print(f"Dry run; would analyze: {min(batch_size, len(candidates))}")
        atomic_write_json(inventory_path, inventory)
        return {"analyzed": 0, "failed": 0, "quota_blocked": 0, "dry_run": True}

    evidence = read_json(EVIDENCE_FILE) if EVIDENCE_FILE.exists() else {"type": "FeatureCollection", "features": [], "metadata": {}}
    existing_ids = {feature.get("id") for feature in evidence.get("features", [])}
    osm_paths = read_json(OSM_FILE).get("features", []) if OSM_FILE.exists() else []
    selected = candidates[:max(0, batch_size)]
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required for analysis.")
    from google import genai
    client = genai.Client(api_key=api_key)
    client.models.get(model=model)
    backup = backup_evidence() if selected else None
    analyzed = failed = quota_blocked = 0
    for image in selected:
        image["ai_status"] = "processing"
        image["last_processing_attempt"] = utc_now()
        image["failure_reason"] = None
        atomic_write_json(inventory_path, inventory)
        try:
            findings = call_with_bounded_retry(lambda: analyze_image_with_gemini(image, client, model))
            new_features = [feature for feature in make_ai_features(image, findings, osm_paths) if feature["id"] not in existing_ids]
            evidence["features"].extend(new_features)
            existing_ids.update(feature["id"] for feature in new_features)
            update_evidence_metadata(evidence)
            image["ai_status"] = "analyzed"
            image["findings_count"] = len(new_features)
            image["evidence_ids"] = [feature["id"] for feature in new_features]
            image["failure_reason"] = None
            analyzed += 1
            save_evidence(evidence)
            atomic_write_json(inventory_path, inventory)
        except Exception as error:
            image["ai_status"] = "quota_blocked" if is_quota_error(error) else "failed"
            image["failure_reason"] = str(error)
            if is_quota_error(error):
                quota_blocked += 1
                atomic_write_json(inventory_path, inventory)
                break
            failed += 1
            atomic_write_json(inventory_path, inventory)
    if backup:
        print(f"Canonical evidence backup: {backup.resolve()}")
    return {"analyzed": analyzed, "failed": failed, "quota_blocked": quota_blocked, "dry_run": False}


def coverage_report(inventory_path=INVENTORY_FILE):
    inventory = load_inventory(inventory_path)
    evidence = read_json(EVIDENCE_FILE) if EVIDENCE_FILE.exists() else {"features": []}
    images = inventory.get("images", [])
    statuses = Counter(image.get("ai_status", "pending") for image in images)
    findings = [feature for feature in evidence.get("features", []) if feature.get("properties", {}).get("source") == "gemini_ai"]
    image_findings = Counter(str(feature.get("properties", {}).get("mapillary_image_id")) for feature in findings)
    analyzed = statuses.get("analyzed", 0)
    eligible = sum(image.get("ai_status") not in {"skipped_with_reason"} for image in images)
    reviewed_count = 0
    if (OUTPUT_DIR / "accessibility_review_queue.csv").exists():
        with (OUTPUT_DIR / "accessibility_review_queue.csv").open(newline="", encoding="utf-8") as handle:
            reviewed_count = sum(1 for row in csv.DictReader(handle) if row.get("reviewer_decision") not in {"", "pending"})
    report = {
        "bbox": inventory.get("bbox", list(BBOX)),
        "total_images_discovered": len(images),
        "total_unique_image_ids": len({image.get("image_id") for image in images}),
        "total_images_eligible": eligible,
        "total_images_analyzed_successfully": analyzed,
        "images_analyzed_with_zero_findings": sum(image.get("findings_count", 0) == 0 for image in images if image.get("ai_status") == "analyzed"),
        "total_accessibility_observations": len(findings),
        "images_pending": statuses.get("pending", 0) + statuses.get("discovered", 0),
        "images_failed": statuses.get("failed", 0),
        "images_blocked_by_quota": statuses.get("quota_blocked", 0),
        "images_skipped_with_reasons": statuses.get("skipped_with_reason", 0),
        "analysis_completion_percentage": round((analyzed / eligible) * 100, 2) if eligible else 0.0,
        "observation_counts_by_category": dict(Counter(feature.get("properties", {}).get("feature_name", "other") for feature in findings)),
        "observation_counts_by_predicted_value": dict(Counter(feature.get("properties", {}).get("predicted_value", "unknown") for feature in findings)),
        "confidence_distribution": {
            "min": min((feature.get("properties", {}).get("confidence", 0) for feature in findings), default=None),
            "max": max((feature.get("properties", {}).get("confidence", 0) for feature in findings), default=None),
            "mean": round(sum(feature.get("properties", {}).get("confidence", 0) for feature in findings) / len(findings), 3) if findings else None,
        },
        "human_review_queue_count": len(findings),
        "human_reviewed_count": reviewed_count,
        "remaining_pending_review_count": max(0, len(findings) - reviewed_count),
        "last_updated": utc_now(),
        "status_note": "Coverage is not complete until every eligible inventory image has a terminal analyzed, failed, quota_blocked, or skipped_with_reason status.",
    }
    atomic_write_json(COVERAGE_REPORT, report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Discover and analyze Mangalore Mapillary images incrementally.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover = subparsers.add_parser("discover")
    discover.add_argument("--token", default=os.getenv("MAPILLARY_ACCESS_TOKEN"), help=argparse.SUPPRESS)
    discover.add_argument("--inventory", default=str(INVENTORY_FILE))
    preview = subparsers.add_parser("preview")
    preview.add_argument("--inventory", default=str(INVENTORY_FILE))
    preview.add_argument("--detection-filter", action="store_true")
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--inventory", default=str(INVENTORY_FILE))
    analyze.add_argument("--batch-size", type=int, default=1)
    analyze.add_argument("--detection-filter", action="store_true")
    analyze.add_argument("--dry-run", action="store_true")
    resume = subparsers.add_parser("resume")
    resume.add_argument("--inventory", default=str(INVENTORY_FILE))
    resume.add_argument("--batch-size", type=int, default=1)
    resume.add_argument("--dry-run", action="store_true")
    coverage = subparsers.add_parser("coverage")
    coverage.add_argument("--inventory", default=str(INVENTORY_FILE))
    args = parser.parse_args()

    if args.command == "discover":
        if not args.token:
            raise SystemExit("MAPILLARY_ACCESS_TOKEN is required for discovery.")
        inventory = discover_inventory(args.token, args.inventory)
        print(f"Discovered unique images: {len(inventory.get('images', []))}")
        print(f"Discovery pages: {inventory.get('discovery_pages', 0)}")
        print(f"Discovery failures: {len(inventory.get('discovery_failures', []))}")
    elif args.command == "preview":
        inventory = load_inventory(args.inventory)
        candidates = image_candidates(inventory, args.detection_filter)
        print(json.dumps({"inventory_images": len(inventory.get("images", [])), "eligible_pending": len(candidates), "detection_filter": args.detection_filter}, indent=2))
    elif args.command in {"analyze", "resume"}:
        result = analyze_batch(args.inventory, args.batch_size, getattr(args, "detection_filter", False), args.dry_run)
        coverage_report(args.inventory)
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(coverage_report(args.inventory), indent=2))


if __name__ == "__main__":
    main()
