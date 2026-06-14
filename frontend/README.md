# MAISYS frontend demo

Vite + React 18 + TypeScript + Tailwind 3 + i18next.

Demonstrates the PR3 surface:

- Free-text query submission to `/drugs/query`
- WebSocket subscription to `/ws/drugs/query/{job_id}` for progress
- Bilingual UI with full RTL flip on Arabic
- All 4 visual types (`severity_bar`, `comparison_table`, `dosing_flowchart`, `pk_curve`) + generic card fallback

## Running

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

The dev server proxies `/auth`, `/drugs`, `/ws` to the local
compose stack (ports 8001 and 8002), so bring the stack up first:

```bash
docker-compose up -d
```

## Authentication

For the demo, paste a JWT into the browser console:

```js
localStorage.setItem("maisys.access_token", "<paste JWT here>")
```

Production deployments add a real login page.

## Type contract

`src/types/api.ts` mirrors `services/drug-service/models/schemas.py`.
Any backend schema change MUST update this file in the same commit.
