"""Local validation, OSM association, and human-review tools for AUXILIUM."""

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PIPELINE_DIR / "output"
EVIDENCE_FILE = OUTPUT_DIR / "mangalore_mapillary_accessibility.geojson"
OSM_FILE = OUTPUT_DIR / "pedestrian_paths.geojson"
VALIDATION_REPORT = OUTPUT_DIR / "accessibility_validation_report.json"
MATCHING_REPORT = OUTPUT_DIR / "osm_matching_report.json"
REVIEW_QUEUE = OUTPUT_DIR / "accessibility_review_queue.csv"
REVIEW_DECISIONS = OUTPUT_DIR / "accessibility_review_decisions.json"
MATCH_THRESHOLD_METERS = 50.0
FEATURE_NAMES = {"stairs", "ramp", "curb", "dropped_curb", "tactile_paving", "obstacle", "surface", "other"}
PREDICTED_VALUES = {"present", "smooth", "uneven", "damaged", "unknown"}
REVIEW_DECISIONS_ALLOWED = {"pending", "confirmed", "rejected", "needs_more_evidence"}
ELIGIBLE_HIGHWAYS = {"footway", "path", "pedestrian", "steps", "service", "living_street", "residential", "cycleway", "track"}
REVIEW_FIELDS = [
    "evidence_id", "evidence_source", "mapillary_image_id", "observation_category", "predicted_value",
    "ai_explanation", "confidence", "latitude", "longitude", "associated_osm_path_id",
    "matching_distance_m", "model", "verification_status", "reviewer_decision", "reviewer_notes",
]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2), encoding="utf-8")


def is_valid_coordinate_pair(coordinates):
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
        return False
    try:
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError):
        return False
    return math.isfinite(longitude) and math.isfinite(latitude) and -180 <= longitude <= 180 and -90 <= latitude <= 90


def normalize_observation(properties):
    category = properties.get("feature_name", properties.get("evidence_type", "other"))
    value = properties.get("predicted_value", "unknown")
    try:
        confidence = float(properties.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    return {
        "feature_name": category if category in FEATURE_NAMES else "other",
        "predicted_value": value if value in PREDICTED_VALUES else "unknown",
        "confidence": max(0.0, min(1.0, confidence)),
        "visual_explanation": str(properties.get("visual_explanation", "")),
    }


def validate_evidence(features):
    ai_features = [feature for feature in features if feature.get("properties", {}).get("source") == "gemini_ai"]
    issues = []
    category_counts = Counter()
    value_counts = Counter()
    duplicate_keys = Counter()
    for index, feature in enumerate(ai_features):
        properties = feature.get("properties", {})
        evidence_id = feature.get("id") or f"record_{index}"
        normalized = normalize_observation(properties)
        category_counts[normalized["feature_name"]] += 1
        value_counts[normalized["predicted_value"]] += 1
        duplicate_keys[(properties.get("mapillary_image_id"), normalized["feature_name"], normalized["predicted_value"])] += 1
        record_issues = []
        if properties.get("feature_name") not in FEATURE_NAMES:
            record_issues.append("invalid_or_missing_category")
        if properties.get("predicted_value") not in PREDICTED_VALUES:
            record_issues.append("invalid_or_missing_value")
        if not is_valid_coordinate_pair(feature.get("geometry", {}).get("coordinates")):
            record_issues.append("invalid_coordinates")
        if not properties.get("mapillary_image_id"):
            record_issues.append("missing_mapillary_image_id")
        if properties.get("verification_status") != "needs_review":
            record_issues.append("verification_status_not_needs_review")
        if properties.get("accessibility_claim") != "unknown":
            record_issues.append("accessibility_claim_not_unknown")
        if record_issues:
            issues.append({"evidence_id": evidence_id, "issues": record_issues})
    duplicates = [
        {"mapillary_image_id": key[0], "feature_name": key[1], "predicted_value": key[2], "count": count}
        for key, count in duplicate_keys.items() if count > 1
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(EVIDENCE_FILE),
        "total_features": len(features),
        "ai_evidence_records": len(ai_features),
        "valid_records": len(ai_features) - len(issues),
        "invalid_records": len(issues),
        "category_counts": dict(sorted(category_counts.items())),
        "predicted_value_counts": dict(sorted(value_counts.items())),
        "unknown_observations": value_counts.get("unknown", 0),
        "exact_duplicate_groups": duplicates,
        "issues": issues,
        "normalization_rules": {
            "invalid_category": "other",
            "invalid_or_missing_value": "unknown",
            "confidence": "finite numeric value clamped to 0..1; invalid values become 0",
        },
    }


def project_point(point, origin):
    radius = 6371000.0
    radians = math.pi / 180
    latitude_origin = origin[1] * radians
    return (
        (point[0] - origin[0]) * radians * radius * math.cos(latitude_origin),
        (point[1] - origin[1]) * radians * radius,
    )


def point_to_segment_distance_meters(point, start, end):
    start_x, start_y = project_point(start, point)
    end_x, end_y = project_point(end, point)
    delta_x, delta_y = end_x - start_x, end_y - start_y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return math.hypot(start_x, start_y)
    projection = max(0.0, min(1.0, -(start_x * delta_x + start_y * delta_y) / length_squared))
    return math.hypot(start_x + projection * delta_x, start_y + projection * delta_y)


def line_parts(geometry):
    if not geometry:
        return []
    if geometry.get("type") == "LineString":
        return [geometry.get("coordinates", [])]
    if geometry.get("type") == "MultiLineString":
        return geometry.get("coordinates", [])
    return []


def nearest_path(point, paths, threshold= MATCH_THRESHOLD_METERS):
    nearest = None
    for path in paths:
        properties = path.get("properties", {})
        if properties.get("source") not in (None, "openstreetmap"):
            continue
        if properties.get("highway") and properties.get("highway") not in ELIGIBLE_HIGHWAYS:
            continue
        path_id = properties.get("path_id") or path.get("id")
        for line in line_parts(path.get("geometry", {})):
            for index in range(len(line) - 1):
                start, end = line[index], line[index + 1]
                if not is_valid_coordinate_pair(start) or not is_valid_coordinate_pair(end):
                    continue
                distance = point_to_segment_distance_meters(point, start, end)
                if nearest is None or distance < nearest["distance_m"]:
                    nearest = {"path_id": path_id, "distance_m": distance}
    if nearest is None:
        return {"nearest_path_id": None, "nearest_distance_m": None, "matched_path_id": None}
    return {
        "nearest_path_id": nearest["path_id"],
        "nearest_distance_m": round(nearest["distance_m"], 3),
        "matched_path_id": nearest["path_id"] if nearest["distance_m"] <= threshold else None,
    }


def build_matching_report(evidence, osm):
    ai_features = [feature for feature in evidence.get("features", []) if feature.get("properties", {}).get("source") in {"gemini_ai", "mapillary"}]
    paths = osm.get("features", [])
    observations = []
    for feature in ai_features:
        properties = feature.get("properties", {})
        coordinates = feature.get("geometry", {}).get("coordinates", [None, None])
        matching = nearest_path(coordinates, paths)
        observations.append({
            "evidence_id": feature.get("id"),
            "mapillary_image_id": properties.get("mapillary_image_id"),
            "feature_name": properties.get("feature_name", properties.get("evidence_type", "other")),
            "predicted_value": properties.get("predicted_value", properties.get("raw_value", "unknown")),
            "longitude": coordinates[0],
            "latitude": coordinates[1],
            **matching,
        })
    distances = [row["nearest_distance_m"] for row in observations if row["nearest_distance_m"] is not None]
    associated = Counter(row["matched_path_id"] for row in observations if row["matched_path_id"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_file": str(EVIDENCE_FILE),
        "osm_file": str(OSM_FILE),
        "threshold_m": MATCH_THRESHOLD_METERS,
        "total_accessibility_observations": len(observations),
        "total_osm_paths_considered": len(paths),
        "matched_within_10m": sum(distance <= 10 for distance in distances),
        "matched_within_25m": sum(distance <= 25 for distance in distances),
        "matched_within_50m": sum(distance <= 50 for distance in distances),
        "matched_within_100m": sum(distance <= 100 for distance in distances),
        "unmatched_observations": sum(row["matched_path_id"] is None for row in observations),
        "distance_distribution_m": {
            "min": round(min(distances), 3) if distances else None,
            "max": round(max(distances), 3) if distances else None,
            "mean": round(sum(distances) / len(distances), 3) if distances else None,
        },
        "observations_per_osm_path": dict(sorted(associated.items())),
        "observations": observations,
        "status": "provisional_until_expanded_osm_dataset_is_available" if len(paths) <= 6 else "current_dataset",
    }


def load_decisions():
    if not REVIEW_DECISIONS.exists():
        return {}
    data = read_json(REVIEW_DECISIONS)
    return {item["evidence_id"]: item for item in data if item.get("evidence_id")}


def write_review_queue(evidence, matching):
    matching_by_id = {item["evidence_id"]: item for item in matching.get("observations", [])}
    decisions = load_decisions()
    rows = []
    for feature in evidence.get("features", []):
        properties = feature.get("properties", {})
        if properties.get("source") not in {"gemini_ai", "mapillary"}:
            continue
        coordinates = feature.get("geometry", {}).get("coordinates", [None, None])
        match = matching_by_id.get(feature.get("id"), {})
        previous = decisions.get(feature.get("id"), {})
        decision = previous.get("reviewer_decision", "pending")
        if decision not in REVIEW_DECISIONS_ALLOWED:
            decision = "pending"
        rows.append({
            "evidence_id": feature.get("id", ""),
            "evidence_source": properties.get("source", ""),
            "mapillary_image_id": properties.get("mapillary_image_id", ""),
            "observation_category": properties.get("feature_name", properties.get("evidence_type", "other")),
            "predicted_value": properties.get("predicted_value", properties.get("raw_value", "unknown")),
            "ai_explanation": properties.get("visual_explanation", ""),
            "confidence": properties.get("confidence", ""),
            "latitude": coordinates[1],
            "longitude": coordinates[0],
            "associated_osm_path_id": match.get("matched_path_id"),
            "matching_distance_m": match.get("nearest_distance_m"),
            "model": properties.get("model", ""),
            "verification_status": properties.get("verification_status", "needs_review"),
            "reviewer_decision": decision,
            "reviewer_notes": previous.get("reviewer_notes", ""),
        })
    with REVIEW_QUEUE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def synchronize_review_artifacts(evidence, osm=None):
    """Regenerate matching and review artifacts while preserving decisions."""
    osm = osm or read_json(OSM_FILE)
    matching = build_matching_report(evidence, osm)
    write_json(MATCHING_REPORT, matching)
    rows = write_review_queue(evidence, matching)
    return matching, rows


def export_reviewed(input_path, output_path):
    canonical = {
        feature.get("id"): feature
        for feature in read_json(EVIDENCE_FILE).get("features", [])
        if feature.get("properties", {}).get("source") in {"gemini_ai", "mapillary"}
    }
    rows = []
    with Path(input_path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            decision = row.get("reviewer_decision", "pending")
            if decision not in REVIEW_DECISIONS_ALLOWED:
                raise ValueError(f"Invalid reviewer decision for {row.get('evidence_id')}: {decision}")
            feature = canonical.get(row.get("evidence_id"))
            if not feature:
                raise ValueError(f"Unknown evidence ID: {row.get('evidence_id')}")
            properties = feature["properties"]
            coordinates = feature.get("geometry", {}).get("coordinates", [None, None])
            immutable_values = {
                "mapillary_image_id": str(properties.get("mapillary_image_id", "")),
                "observation_category": str(properties.get("feature_name", properties.get("evidence_type", "other"))),
                "predicted_value": str(properties.get("predicted_value", properties.get("raw_value", "unknown"))),
                "ai_explanation": str(properties.get("visual_explanation", "")),
                "confidence": str(properties.get("confidence", "")),
                "latitude": str(coordinates[1]),
                "longitude": str(coordinates[0]),
                "verification_status": str(properties.get("verification_status", "needs_review")),
            }
            for field, expected in immutable_values.items():
                if row.get(field, "") != expected:
                    raise ValueError(f"Immutable AI field changed for {row.get('evidence_id')}: {field}")
            rows.append(row)
    write_json(output_path, {"exported_at": datetime.now(timezone.utc).isoformat(), "records": rows})
    write_json(REVIEW_DECISIONS, rows)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Validate and review local AUXILIUM accessibility evidence.")
    parser.add_argument("command", choices=("validate", "match", "review-init", "review-export"))
    parser.add_argument("--input", default=str(REVIEW_QUEUE), help="Review CSV for review-export.")
    parser.add_argument("--output", default=str(OUTPUT_DIR / "reviewed_accessibility_evidence.json"))
    args = parser.parse_args()
    evidence = read_json(EVIDENCE_FILE)
    if args.command == "validate":
        report = validate_evidence(evidence.get("features", []))
        write_json(VALIDATION_REPORT, report)
        print(json.dumps(report, indent=2))
    elif args.command == "match":
        report = build_matching_report(evidence, read_json(OSM_FILE))
        write_json(MATCHING_REPORT, report)
        print(json.dumps({key: value for key, value in report.items() if key != "observations"}, indent=2))
    elif args.command == "review-init":
        matching = read_json(MATCHING_REPORT) if MATCHING_REPORT.exists() else build_matching_report(evidence, read_json(OSM_FILE))
        rows = write_review_queue(evidence, matching)
        print(f"Review queue written: {REVIEW_QUEUE.resolve()} ({len(rows)} records)")
    else:
        print(f"Reviewed records exported: {export_reviewed(args.input, args.output)}")


if __name__ == "__main__":
    main()
