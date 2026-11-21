# Evaluation set

`labels.csv` holds 66 hand-labelled (facility, service) pairs for the six headline services (dialysis,
emergency C-section, NICU, trauma, cardiac surgery, MRI) plus three cath-lab rows. Each was labelled by reading the
facility's own record (procedures, capabilities, equipment, description, specialties, beds).

| label | meaning |
|---|---|
| `yes` | a careful reader of this record would conclude the facility provides the service: it is stated plainly, or the facility is a large teaching hospital (AIIMS, medical college, 500+ beds) with the relevant department, where the service is standard |
| `no` | the record does not support it: the keyword hit is about something else (bile-duct stents, "atraumatic extraction", an ambulance labelled "NICU") or is only a guess |
| `unclear` | genuinely can't tell (specialty listed only, photo-based guess at a mid-size hospital); left out of precision and recall |

`why_sampled` says how each row was picked: `random_sm` (random strong/moderate rows), `random_weak`, `merged`
(records flagged `possible_merged_record`), `known_issue` (false positives and misses found while testing).
Because known problems were deliberately included, the numbers below are a stress test, not a population estimate.

## Running it

```powershell
python eval/run_eval.py                          # evaluates workspace.datathon
python eval/run_eval.py --schema datathon_dev    # or another schema
python eval/run_eval.py --freeze v2              # snapshot current tiers as eval/predictions_v2.csv
```

`run_eval.py` loads `labels.csv` and the frozen `predictions_*.csv` into tables, then runs `evaluate.sql`
(also runnable as a Databricks notebook once those tables exist).

A prediction is **positive** when the evidence tier is `strong` or `moderate` (the `current+probable` row
also counts `probable`). `keyword_baseline` = any service alias appears anywhere in the record, no rules.
`v1` = the original rules, frozen before the quality-ranking work.

## Results

| version | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| keyword baseline | 39 | 10 | 5 | 0.80 | 0.89 |
| v1 (original rules) | 39 | 11 | 5 | 0.78 | 0.89 |
| Phase 1 (exclusions, claim types, scope gate) | 38 | 0 | 6 | **1.00** | 0.86 |

Per service after Phase 1: cardiac surgery 0.50 → 1.00 precision, cath lab 0.33 → 1.00, MRI 0.75 → 1.00,
NICU 0.88 → 1.00, trauma 0.77 → 1.00 (recall 1.00 → 0.80). Dialysis and C-section had no false positives to start with.

Remaining misses: five large teaching hospitals (AIIMS Patna ×2, AIIMS Nagpur, IGIMS, KGMU) that list obstetrics but
never name C-section, and a 1,416-bed medical college whose only trauma mention is a paper affiliation (correctly
discounted as `third_party`). These are what the `probable` tier (Phase 2) is meant to surface.
