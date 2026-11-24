# AUXILIUM

AUXILIUM is an accessibility-aware pedestrian routing demo for Mangalore. It combines OSM pedestrian paths with Mapillary and Gemini accessibility observations, while keeping AI evidence subject to human review.

## Run locally

From the repository root, start the routing API:

```bash
python -m backend.server
```

In another terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the local Vite URL shown in the terminal. Select two points on the map to request a route.

## Main components

- `frontend/` — React, Vite and Leaflet map application.
- `backend/` — accessibility-aware pedestrian graph and route API.
- `data-pipeline/` — OSM extraction, Mapillary/Gemini evidence, matching and review artifacts.
- `api/` — Vercel production adapters for `/api/routes` and `/api/health`.
- `firestore.rules` — owner-scoped Firebase Auth and review access rules.

## Profiles

- **General** uses valid pedestrian paths without accessibility filtering.
- **Wheelchair** excludes confirmed barriers and cautiously ranks unknown conditions.
- **Walking support** applies walking-specific costs for stairs, inclines and difficult surfaces.

AI observations remain unverified until a human reviewer accepts, rejects or flags them.

## Firebase

Set these variables in `frontend/.env.local` or the deployment environment:

```text
VITE_FIREBASE_API_KEY=
VITE_FIREBASE_AUTH_DOMAIN=
VITE_FIREBASE_PROJECT_ID=
VITE_FIREBASE_STORAGE_BUCKET=
VITE_FIREBASE_MESSAGING_SENDER_ID=
VITE_FIREBASE_APP_ID=
```

Without Firebase configuration, the app opens in local demo mode and stores review decisions in browser storage. Deploy rules after configuring Firebase:

```bash
firebase deploy --only firestore:rules
```

## Vercel deployment

Keep the Vercel Root Directory at the repository root. Use:

```text
Framework Preset: Vite
Install Command: npm --prefix frontend ci
Build Command: npm --prefix frontend run build
Output Directory: frontend/dist
```

The root `api/` directory provides the production routing endpoints. Leave `VITE_ROUTING_API_URL` unset when frontend and API share the same Vercel deployment.

## Tests

```bash
python -m unittest discover -s backend/tests -v
python -m unittest discover -s data-pipeline/tests -v
cd frontend && npm run build && npm run lint
```

The 50 metre evidence-to-OSM matching threshold is defined in `data-pipeline/accessibility_quality.py` and should remain unchanged.
