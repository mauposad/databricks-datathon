# Next steps plan (2026-11-22)

Covers Mauricio's handoff notes: point the live app at the new bundle, then (1) faster searches, (2) city/town
search, (3) broad medical categories, then a bug pass.

## 0. Status and going live

- **Why both apps show "unavailable":** the workspace hit the Free Edition daily compute limit. `databricks apps start`
  returns "you have hit your free daily limit. Please come back again tomorrow", and the SQL warehouse also refuses
  queries. Nothing is wrong with the code. Both `care-finder` (live) and `care-finder-mposadas` (Mauricio's dev copy)
  were stopped at 06:43 UTC.
- **Where "the bundle" is:** Mauricio's deployment lives at
  `/Workspace/Datathon-2026-Shared/virtue-foundation-india-healthcare-datathon/mposadas/files`. It is identical to
  `origin/main` (commit `a57962b`, PR #8 "ui-polish"); the only extra file is a leftover
  `app/frontend/src/components/ResultCard.jsx` that nothing imports. `main` already contains all of
  `feature/quality-ranking`.
- **Both apps read the same SQL objects** (`workspace.datathon.find_care`, `CARE_SCHEMA=datathon`), so going live only
  means redeploying the **app code** from `main`. No table rebuild is needed.

Once compute is back, run these from `databricks-datathon/` on `main`, in PowerShell:

```powershell
databricks bundle deploy --target dev
databricks bundle run care_finder --target dev
```

Then smoke-test the live URL with `dialysis` + `Jaipur`, `nicu` + `Patna` and a PIN code, and stop
`care-finder-mposadas` (`databricks apps stop care-finder-mposadas`) so the two apps don't split the daily quota.

**To preview the UI without compute,** use the `care-finder-ui-mock` launch config (Vite with `VITE_MOCK=1`, port 5173).

---

## 1. Faster searches ("better relation mapping")

### Where the time goes (from reading the code; measure first)

1. **Cold warehouse.** The Serverless Starter Warehouse auto-stops, so the first search after idle waits for it to
   start. This is probably the biggest single cost, and it is invisible in the SQL.
2. **`resolve_location` scans every PIN code for every place search.** The `po_cand` CTE explodes `place_names` for all
   ~19k PIN codes and runs two regexes on every office name (`src/04_find_care_function.sql:74-86`). `as_city` joins
   all of `silver_facilities` on `upper(trim(city_raw))`.
3. **`find_care` recomputes haversine many times** (lines 259, 260, 283, 349, 410, 419) over all
   `gold_facility_services` rows for the service, with no bounding-box prefilter, so Delta can't skip files.
4. **The app runs queries one after another and caches nothing per search.** `services()` and `places()` are cached
   for an hour, but `recommend()` is not, and the `/api/services` and `/api/places` page-load calls each pay a warehouse
   round trip.

### Plan

| # | Change | Where | Expected win |
|---|--------|-------|--------------|
| 1a | **Measure:** time 10 typical searches (PIN, district, city, village) and read the query profile for `resolve_location` vs. the rest of `find_care` | query history | tells us which fixes matter |
| 1b | **Gazetteer table** `silver_places` (see §2) with one row per normalized name, so `resolve_location` becomes an equality lookup instead of explode + regex over all PINs | new `src/01b_silver_places.sql`, rewrite `resolve_location` | large for place-name searches |
| 1c | **Bounding-box prefilter:** add `g.lat BETWEEN loc.lat ± dlat AND g.lon BETWEEN loc.lon ± dlon` before any haversine, and compute `km` once in the first CTE, reusing it afterwards | `04_find_care_function.sql` | medium |
| 1d | **Liquid clustering:** `ALTER TABLE gold_facility_services CLUSTER BY (service_key, lat, lon)` and `silver_places CLUSTER BY (name_norm)`, then `OPTIMIZE` | `03_…sql` / new notebook | medium (enables file skipping) |
| 1e | **App-side result cache:** cache `recommend()` by `(service, place, max_km, top_n, public_only)` for about 10 minutes; serve `/api/services` and `/api/places` from a static JSON baked in at deploy time | `app/backend/adapters/find_care.py`, `main.py` | demo searches answer instantly when repeated |
| 1f | **Warm-up:** fire a `SELECT 1` against the warehouse at app startup and when the search page loads, so the warehouse is starting while the user types | `main.py`, `App.jsx` | hides most of the cold start |

**Done when:** a warm search returns in under 2 s at the 95th percentile, a repeated search takes under 200 ms, and
`eval/run_eval.py` results are unchanged (the ranking must not move).

---

## 2. Search by city or town

### Today

- The place picker only offers **districts** (`places()` = distinct `silver_pincode_geo.district`).
- `resolve_location` does understand PIN codes, `lat,lon`, districts, post-office names (with the BO/SO/HO suffix
  stripped) and cities, but "city" only exists if **10 or more high-confidence facilities** list that `city_raw`. Small
  towns fall through to post-office matching, which is ambiguous ("Rampur" matches dozens of offices) and misses common
  spellings (Bangalore/Bengaluru, Gurgaon/Gurugram, Bombay/Mumbai).
- *Need from Mauricio:* what the "95% PIN coverage" figure measures (PINs with a usable lat/lon? facilities with a
  matched PIN?), so we measure city coverage the same way.

### Plan: one gazetteer table that both the picker and `resolve_location` use

`workspace.datathon.silver_places`, with one row per (place, district, state):

| column | meaning |
|---|---|
| `name`, `name_norm` | display name, plus a normalized key (lower-case, no punctuation or suffixes, collapsed spaces) |
| `place_type` | `city` / `town` / `village` / `post_office` / `district` |
| `district`, `state`, `pincodes[]` | for disambiguation and the label |
| `lat`, `lon`, `geo_method` | median of the PINs or offices it covers |
| `n_facilities`, `n_post_offices` | used to rank same-name places ("Rampur, UP" ahead of a branch office) |
| `aliases[]` | old names and spellings |

Sources, in order of trust:

1. **India Post offices** (all ~155k): strip the BO/SO/HO/GPO suffix. A head office (HO) or sub office (SO) name ≈ a town.
2. **Facility `city_raw`** values that agree with their PIN's `place_names` (already checked in silver), with no
   10-facility floor.
3. **Districts** from `silver_pincode_geo`.
4. **A small hand-written alias list** (`ref_place_aliases`) for renamed cities: Bombay→Mumbai, Madras→Chennai,
   Calcutta→Kolkata, Bangalore→Bengaluru, Gurgaon→Gurugram, Allahabad→Prayagraj, Poona→Pune, Trivandrum→Thiruvananthapuram,
   and so on. About 40 rows covers most of it.
5. *(Optional, needs agreement: external data)* the 2011 Census town list or GeoNames India (CC BY), to rank by
   population and catch towns with no post office of the same name.

Matching inside `resolve_location`: exact `name_norm`, then alias, then a fuzzy fallback (`levenshtein(name_norm, q) <= 2`
on a prefix-filtered candidate set). Ties go to `n_facilities`, then to office rank, and the response still says
"Others: …" so the user can add ", district".

Front end: `/api/places` becomes a **type-ahead endpoint** (`?q=ram` returns the top 15 `name, district, state, type`)
instead of shipping one fixed district list. The combobox shows "Rampur — Rampur district, Uttar Pradesh (town)".

**Done when:** a list of ~50 test towns (big cities, renamed cities, small towns, duplicate names) all resolve to
the right district. Add it as `eval/places_labels.csv` with a small check script. Coverage is reported as the share of
facility `city_raw` values and of India Post HO/SO names that resolve.

---

## 3. Broad medical categories (biggest piece)

### Today

- Users choose from **17 fixed services** (`ref_services`: dialysis, NICU, MRI, cath lab, …). Each is defined by
  hand-written regexes in `src/03_gold_facility_services.sql:57-151`.
- Anything outside those 17 is not searchable, even though the raw `specialties`, `procedures` and `capabilities`
  columns hold thousands of distinct terms (gastroenterology, ENT, psychiatry, physiotherapy, IVF, …).
- Lay words only work through `aliases` and the LLM prompt in `app/backend/chat.py:32-39`.

### Plan: a two-level taxonomy, broad category → specific service

1. **Profile the raw vocabulary.** Count distinct normalized terms in `facility_phrases` by field, and keep the top
   ~1,000 terms (they probably cover more than 90% of mentions).
2. **Define about 15–20 broad categories**, close to how a patient or caregiver would ask:
   Heart · Pregnancy & birth · Newborn & child · Kidney · Cancer · Brain & nerves · Bones & joints · Eyes · ENT ·
   Emergency & trauma · Critical care · Imaging & scans · Lungs & breathing · Stomach & liver · Mental health ·
   Skin · Dental · General medicine / surgery.
3. **Map terms to categories** in a reviewable table `ref_term_category(term_norm, category_key, service_key NULL,
   source)`:
   - Our existing 17 services fold in as children of a category (dialysis → Kidney; cath_lab and cardiac_surgery → Heart).
   - For the long tail, run `ai_query` once **offline** with the Llama endpoint to propose a category for each top term,
     then a person reviews the CSV. Keep the regex rules as the explanation for each mapping, so citations stay verbatim.
4. **New gold table** `gold_facility_categories` with one row per (facility, category): evidence tier, matched phrases
   and Quality, built the same way as `gold_facility_services`. Specific services keep their richer checklists.
5. **Search contract:** `find_care` accepts either a `service_key` or a `category_key`. Searching a category ranks
   facilities by category evidence and shows which specific services were found ("Heart: cath lab ✓, cardiac surgery ✓").
6. **UI:** the service picker becomes grouped (category heading, specific services under it), and searches like
   "heart problem" or "pregnancy" map to a category. The chat prompt gets the category list, so symptoms map to a
   category when no specific service fits.

**Done when:** each category has labelled examples in `eval/labels.csv`, precision@5 for category searches is no
lower than for today's services, and every result still cites verbatim text.

*Need from Mauricio:* is (a) "let users search in plain categories" or (b) "cover the specialties beyond our 17
services" the main goal? The plan above does both. If time is short, (a) alone is steps 2, 3 (existing 17 only) and 6,
roughly half a day.

---

## 4. Bug and odd-behaviour pass

- Run the mock UI states (`VITE_MOCK=1|slow|empty|fail`) and the live app against a fixed script: each example chip,
  PIN, district, village with a duplicate name, an unknown place, an unknown service, the public-only toggle, radius
  extremes, chat, voice and the planner tab.
- Delete the stray `ResultCard.jsx` from the deployed bundle (redeploying from `main` removes it).
- Check `_diagnose()` messages after §2 changes the place resolver.
- Re-run `python eval/run_eval.py` after every SQL change.

## Suggested order

1. Go live from `main` (as soon as the quota resets).
2. §1a measurement, plus the quick wins 1e and 1f (app only, no table rebuild).
3. §2 gazetteer, which also delivers §1b.
4. §3 categories, starting with the "(a)" slice.
5. §1c/1d SQL tuning, then §4 bug pass.

Rebuild `workspace.datathon` only with agreement, because the live app reads it. Test SQL changes in
`workspace.datathon_dev` first.
