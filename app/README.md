# Care Finder (Databricks App)

React + FastAPI app over `workspace.datathon.find_care` (Find care) and `gold_district_access` (District planner). Plan and status: [`../interface_build_plan.md`](../interface_build_plan.md).

```
app/
  app.yaml              Databricks Apps runtime config (command + env)
  requirements.txt      Python deps (installed by Apps)
  package.json          Frontend deps; Apps runs `npm install` + `npm run build` -> static/
  backend/
    main.py             FastAPI: /api/services, /api/places, /api/recommend, /api/chat, serves static/
    schema.py           The universal contract (Query, Recommendation, ...). Keep stable.
    adapters/           One adapter per data source; find_care.py is the default
    chat.py             LLM query extraction + grounded reply, with keyword/template fallback
    sql.py              Statement Execution API helper
  frontend/             Vite + React source (form, chat, voice, cards, Leaflet map)
```

## Run locally (PowerShell)

One time:

```powershell
cd app; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt; npm install
```

Each time (build the UI, then serve API + UI on http://localhost:8000):

```powershell
npm run build; $env:DATABRICKS_CONFIG_PROFILE = "YOUR_PROFILE"; .venv\Scripts\python -m uvicorn backend.main:app --port 8000
```

For hot reload on the UI, also run `npm run dev` and open http://localhost:5173 (it proxies `/api` to port 8000).

## Deploy

```powershell
databricks bundle deploy --target dev; databricks bundle run care_finder --target dev
```

Before a deploy, refresh the shipped service/place snapshot so a freshly started app answers the page-load calls
without waiting for the warehouse (needs a working warehouse; skip it and the app just loads them from SQL):

```powershell
$env:DATABRICKS_CONFIG_PROFILE = "YOUR_PROFILE"; .venv\Scripts\python scripts\snapshot_reference.py
```

## Speed settings (env vars, all optional)

- `RESULT_CACHE_TTL` (default `600`): seconds an identical search is answered from memory. Verifications clear it.
  `0` turns it off.
- `WARMUP` (default `1`): start the SQL warehouse in the background at app start and on page load (`POST /api/warmup`),
  at most once per `WARMUP_COOLDOWN` seconds (default `120`). There is deliberately no periodic keep-alive, which would
  burn the Free Edition compute quota. `WARMUP=0` turns it off.

After the first deploy, give the app's service principal read access to the cleaned data (once, in the SQL editor;
the principal's application id is on the app's page under **Authorization**):

```sql
GRANT USE CATALOG ON CATALOG workspace TO `<app-sp-application-id>`;
GRANT USE SCHEMA, SELECT, EXECUTE ON SCHEMA workspace.datathon TO `<app-sp-application-id>`;
-- reviewer Confirm / Reject buttons write to this overlay table (only this one)
GRANT MODIFY ON TABLE workspace.datathon.verifications TO `<app-sp-application-id>`;
```

## UI conventions

- **Tokens only.** Colour, space (`--s-1`..`--s-7`), type (six steps, `--fs-1`..`--fs-6`), radius and motion live in
  `frontend/src/styles/tokens.css`. No hex colours in `.jsx` (the map reads its colours with `getComputedStyle`).
- **One accent.** Use it only for the primary action, the focus ring, the selected state and links in running text.
  Status colours (green, amber, red) go only on the confidence badge, status icons and score bars.
- **Contrast.** Run `node frontend/scripts/check-contrast.mjs` after any colour change. Text must reach 4.5:1 and
  controls 3:1, in light and dark. Nothing smaller than 12px. Two weights only (400, 600).
- **Components.** Use `frontend/src/components/ui/` (Button, Badge, Tabs, Select, Combobox, Slider, Switch, Popover,
  Tooltip, Dialog, Skeleton, Toast) and `Icon.jsx` (lucide, 16 or 20px). No emoji or text glyphs as icons.
  Never use `prompt` or `alert`.
- **Motion.** Use the pieces in `frontend/src/motion/` and the tokens. Animate only transform, opacity, filter and
  clip-path. No springs that rebound. Everything respects `prefers-reduced-motion`. `app/docs/motion-notes.md` says
  where each rule lives.
- **Copy.** Plain, short sentences. No em dashes, no exclamation marks.
- **Interpretability stays.** Score breakdown, quotes, rejected evidence, caveats, sources, "How we score" and the
  double-checks may move, but must not be removed.
- **Without a backend:** `VITE_MOCK=1 npm run dev` (also `slow`, `empty`, `fail`) serves made-up data from
  `frontend/src/fixtures/`. The mock is dev-only and is not in the production build.

## Adding another model or dataset

Implement `services()` and `recommend(query)` in a new class under `backend/adapters/`, returning the shapes in
`backend/schema.py`; register it in `backend/adapters/__init__.py`; set `ADAPTER` in `app.yaml`. The UI needs no changes.
