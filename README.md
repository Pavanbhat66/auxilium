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
