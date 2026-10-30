## Mapillary accessibility evidence

The Mangalore ingestion pipeline reads `MAPILLARY_ACCESS_TOKEN`, fetches imagery and detections within the configured city bounding box, and writes evidence points to `data-pipeline/output/mangalore_mapillary_accessibility.geojson`.

```powershell
$env:MAPILLARY_ACCESS_TOKEN = "MLY|..."
python data-pipeline/ingest_mapillary.py
Copy-Item data-pipeline/output/mangalore_mapillary_accessibility.geojson frontend/public/data/mangalore_mapillary_accessibility.geojson
```

The frontend displays these points as review markers. They are deliberately marked `needs_review` and `accessibility_claim: unknown`; Mapillary detections must not be treated as verified accessible or inaccessible paths without path matching and human verification.
