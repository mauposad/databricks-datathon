# Interface build plan: Care Finder app

> Living plan for the Databricks App that sits on top of `workspace.datathon.find_care`.
> Agents and teammates: read this before touching `app/`, and update the **Status** table when you finish a piece.
> Branch: `feature/facility-finder-app`.

## Goal

A user gives a **service** and a **location**. The app returns the **top 5 facilities** as cards and on a map,
with contact details, a confidence level, and **exactly which data in the table led to each recommendation**.
Three ways in, one way out:

| Input | How | Notes |
|---|---|---|
| Form | Service dropdown (from `ref_services`) + location box (PIN, city, district or `lat,lon`, with district autocomplete) + radius slider | Always works; no LLM needed |
| Chat | Free text → LLM extracts `{service, place, max_km}` → same recommend call → LLM writes a short answer **using only the returned rows** | Keyword fallback if the LLM endpoint is down |
| Voice | Browser Web Speech API: mic → transcript → chat path; a speaker button reads the answer aloud (`speechSynthesis`) | Chrome / Edge / Safari. Not Firefox. Lang `en-IN` |

## Interpretability (what judges should see)

Judges care *why* a place was recommended. Every card answers that without the reader trusting us:

1. **Score breakdown bar**: `match = 0.6 × trust + 0.4 × distance`, and trust split into its parts
   (evidence /60, sources /15, size /10, location /15, minus penalties). Rendered as a stacked bar with numbers, not just prose.
2. **Verbatim evidence**: the exact strings from the facility record (procedures, capabilities, equipment, description,
   specialties), each labelled with the **column it came from**, with the service keyword **highlighted** using the same
   regex the pipeline matched on (`match_pattern`).
3. **Rejected evidence**: mentions we threw out as negative or referral-only ("no dialysis", "referred to…"), shown struck through.
4. **Caveats as warning tags**: single source, location uncertain, possible merged record, not a hospital, etc.
5. **Source links**: the websites the claims came from, plus the count of independent domains.
6. **Ranking context**: "#2 ranks below #1 because…" (difference in each component), how many candidates were within the radius,
   and the rule that weak evidence can never outrank strong/moderate.
7. **Confidence label**: High / Medium / Low / Unconfirmed, derived from `trust_score` and `evidence_tier`, with the
   rule printed in a "How we score" panel so nothing is a black box.
8. **Chat/voice explanations** cite the same fields; the LLM is told to use only the returned data and never to add facilities.

## Architecture

```
React (Vite) SPA  ──►  FastAPI (app/backend)  ──►  Adapter  ──►  SQL warehouse: workspace.datathon.find_care(...)
  form / chat / voice        /api/services                       (or any other model/table, via a new adapter)
  cards + map (Leaflet)      /api/places
                             /api/recommend
                             /api/chat  ──► Databricks Foundation Model endpoint (Llama 3.3 70B by default)
```

### The universal contract (keep this stable)

All inputs become a `Query`; every adapter returns `Recommendation`s. The frontend reads only these shapes
(see `app/backend/schema.py`):

```
Query           { service, place, max_km, top_n }
Recommendation  { rank, id, name, address, city, state, pincode, phone, website, facebook, email, lat, lon,
                  distance_km, facility_type, operator_type,
                  confidence: { label, score, tier, rule },
                  score: { match, trust, distance, parts: [{ key, label, points, max }] },
                  tags[], evidence: [{ field, label, text }], rejected_evidence[], match_pattern,
                  caveats[], sources[], why, how }
RecommendResponse { query, origin: { lat, lon, label, matched_as }, results[], n_candidates, adapter, notes[] }
```

**Plugging in another model or cleaned dataset:** write a class in `app/backend/adapters/` that implements
`services()` and `recommend(query)` and returns the contract above, then register it in `adapters/__init__.py`
and set `ADAPTER=<name>` in `app/app.yaml`. If the new source is a SQL table function with different column names,
the `SqlFunctionAdapter` only needs a new column mapping, no new code.

## Data changes made for the app

- `02_silver_facilities.sql`: keeps `facebook_link` (raw `facebookLink`, only if it is a URL).
- `03_gold_facility_services.sql`: carries `email`, `facebook_link`, `city_raw`.
- `04_find_care_function.sql`: new columns are added at the **end** so existing callers keep working: `lat, lon, address, city, pincode, email,
  facebook, facility_type, operator_type, specialties_cited, number_doctors, capacity_beds, n_source_domains,
  distance_score, origin_lat/lon/matched_as`, plus the numeric score components (`pts_*`, `pen_*`),
  `negated_or_referral_mentions`, `match_pattern`, `max_km_used`, `n_candidates`.

## Deployment

- App source lives in `app/`. The bundle resource is in `resources/care_finder.app.yml`.
- The app's service principal needs: `CAN_USE` on the warehouse, `CAN_QUERY` on the LLM endpoint (both declared as app
  resources), and `USE CATALOG workspace`, `USE SCHEMA workspace.datathon`, `SELECT` + `EXECUTE` on the schema (granted once with SQL).
- Run locally: see `app/README.md`.

## Phases & status

| # | Piece | Status | Owner |
|---|---|---|---|
| 0 | Data fixes (facebook, lat/lon, score parts in `find_care`) | done, tables rebuilt 2026-11-21 | Claude session |
| 1 | FastAPI backend + adapter contract | done | Claude session |
| 2 | Form + cards with interpretability panel (score bar, highlighted evidence, rejected mentions, caveats, #N vs #1) | done | Claude session |
| 3 | Leaflet map (numbered pins, origin, radius, card↔pin link) | done | Claude session |
| 4 | Chat endpoint (Llama 3.3 70B parse + grounded summary, keyword fallback) | done, tested via API | Claude session |
| 5 | Voice in/out (Web Speech API, `en-IN`) | built; needs a real-mic test in Chrome/Edge | |
| 6 | Deploy as Databricks App + grants | done: https://care-finder-7474656679702587.aws.databricksapps.com | Claude session |
| 7 | Polish: empty/loading states and a "Search up to N km" button when empty done; still todo: "strong evidence only" filter, demo script | todo | |
| 8 | UI/UX pass (`uiux-improvement-plan.md`): tokens, icons, hero card + rows, real states, motion system | done on branch `feature/ui-polish` | Claude session |

## Open questions / risks

- Free Edition app limits (number of apps, compute size, auto-stop): check on first deploy.
- Foundation Model API rate limits on Free Edition; the keyword fallback keeps chat usable.
- Many facilities have no phone/website: the cards show "Not listed" rather than hiding the field.
