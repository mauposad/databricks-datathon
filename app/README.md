# Care Finder (Databricks App)

React + FastAPI app over `workspace.datathon.find_care`. Plan and status: [`../interface_build_plan.md`](../interface_build_plan.md).

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

After the first deploy, give the app's service principal read access to the cleaned data (once, in the SQL editor;
the principal's application id is on the app's page under **Authorization**):

```sql
GRANT USE CATALOG ON CATALOG workspace TO `<app-sp-application-id>`;
GRANT USE SCHEMA, SELECT, EXECUTE ON SCHEMA workspace.datathon TO `<app-sp-application-id>`;
```

## Adding another model or dataset

Implement `services()` and `recommend(query)` in a new class under `backend/adapters/`, returning the shapes in
`backend/schema.py`; register it in `backend/adapters/__init__.py`; set `ADAPTER` in `app.yaml`. The UI needs no changes.
