## Mapillary accessibility evidence

The Mangalore ingestion pipeline reads `MAPILLARY_ACCESS_TOKEN`, fetches imagery and detections within the configured city bounding box, and writes evidence points to `data-pipeline/output/mangalore_mapillary_accessibility.geojson`.

```powershell
$env:MAPILLARY_ACCESS_TOKEN = "MLY|..."
python data-pipeline/ingest_mapillary.py
Copy-Item data-pipeline/output/mangalore_mapillary_accessibility.geojson frontend/public/data/mangalore_mapillary_accessibility.geojson
```

The frontend displays these points as review markers. They are deliberately marked `needs_review` and `accessibility_claim: unknown`; Mapillary detections must not be treated as verified accessible or inaccessible paths without path matching and human verification.

To enable optional AI image analysis, set the keys in the environment and pass `--ai`:

```powershell
$python = "D:\\AUXILIUM\\.venv\\Scripts\\python.exe"
& $python data-pipeline/ingest_mapillary.py --ai --max-images 1
Copy-Item data-pipeline/output/mangalore_mapillary_accessibility.geojson frontend/public/data/mangalore_mapillary_accessibility.geojson
```

The script loads `data-pipeline/.env` from either the repository root or the `data-pipeline` directory. It expects `MAPILLARY_ACCESS_TOKEN`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_MAX_IMAGES`, and `AUXILIUM_AI_ANALYZE_ALL` there. By default, AI analyzes only images with existing relevant Mapillary detections. Set `AUXILIUM_AI_ANALYZE_ALL=1` to analyze all collected images. AI findings contain a model, confidence, explanation, and `needs_review` status; `unknown` is retained when the image does not support a conclusion.

## Local evidence quality and review

These commands use existing local GeoJSON only; they do not call Mapillary or Gemini:

```powershell
$python = "D:\\AUXILIUM\\.venv\\Scripts\\python.exe"
& $python data-pipeline/accessibility_quality.py validate
& $python data-pipeline/accessibility_quality.py match
& $python data-pipeline/accessibility_quality.py review-init
```

They create `data-pipeline/output/accessibility_validation_report.json`, `osm_matching_report.json`, and `accessibility_review_queue.csv`. Review decisions must be one of `pending`, `confirmed`, `rejected`, or `needs_more_evidence`; export a reviewed queue with:

```powershell
& $python data-pipeline/accessibility_quality.py review-export --input data-pipeline/output/accessibility_review_queue.csv
```

Matching remains provisional until the expanded OSM dataset replaces the current six-path extract.

## Complete Mapillary image analysis workflow

The resumable workflow uses only the configured Mangalore bbox and does not start Gemini analysis during discovery:

```powershell
$python = "D:\\AUXILIUM\\.venv\\Scripts\\python.exe"

# Discover all paginated Mapillary images and persist the inventory.
& $python data-pipeline/mangalore_ai_pipeline.py discover

# Preview workload without Gemini calls.
& $python data-pipeline/mangalore_ai_pipeline.py preview

# Analyze a small batch; completed images are persisted and skipped on resume.
& $python data-pipeline/mangalore_ai_pipeline.py analyze --batch-size 1

# Resume another bounded batch later.
& $python data-pipeline/mangalore_ai_pipeline.py resume --batch-size 5

# Regenerate coverage statistics.
& $python data-pipeline/mangalore_ai_pipeline.py coverage
```

Use `--detection-filter` only when intentionally limiting analysis to images with existing Mapillary detections. The default workflow analyzes every discovered eligible image with a permitted thumbnail, including images without detections. Quota exhaustion marks the current image `quota_blocked`, preserves completed work, and leaves remaining images pending.
