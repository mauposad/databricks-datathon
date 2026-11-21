# Evaluation set

`labels.csv` holds 82 hand-labelled (facility, service) pairs for the six headline services (dialysis,
emergency C-section, NICU, trauma, cardiac surgery, MRI) plus three cath-lab rows. Each was labelled by reading the
facility's own record (procedures, capabilities, equipment, description, specialties, beds).

| label | meaning |
|---|---|
| `yes` | a careful reader of this record would conclude the facility provides the service: it is stated plainly, or the facility is a large teaching hospital (AIIMS, medical college, 500+ beds) with the relevant department, where the service is standard |
| `no` | the record does not support it: the keyword hit is about something else (bile-duct stents, "atraumatic extraction", an ambulance labelled "NICU") or is only a guess |
| `unclear` | genuinely can't tell (specialty listed only, photo-based guess at a mid-size hospital); left out of precision and recall |

`why_sampled` says how each row was picked: `random_sm` (random strong/moderate rows), `random_weak`, `merged`
(records flagged `possible_merged_record`), `known_issue` (false positives and misses found while testing), `probable_sample` (16 random `probable`-tier rows
not seen before labelling, added in Phase 2 to measure that tier).
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

All 82 rows (`unclear` rows excluded from the counts):

| version | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| keyword baseline | 39 | 10 | 12 | 0.80 | 0.76 |
| v1 (original rules) | 39 | 11 | 12 | 0.78 | 0.76 |
| Phase 1: strong/moderate only | 38 | 0 | 13 | **1.00** | 0.75 |
| Phase 2: strong/moderate/probable | 51 | 0 | 0 | **1.00** | **1.00** |

Phase 1 (exclusions, claim types, dental/eye scope gate) removed every false positive: cardiac surgery precision
0.50 → 1.00, cath lab 0.33 → 1.00, MRI 0.75 → 1.00, NICU 0.88 → 1.00, trauma 0.77 → 1.00.

Phase 2 added the `probable` tier for large or teaching hospitals that list the specialty but never name the
procedure (AIIMS, KGMU, IGIMS, medical colleges). Read the recall of 1.00 with care:

* the original misses are the cases this tier was designed for, so recovering them is partly by construction;
* in the fresh random sample of 16 `probable` rows, 7 were `yes`, 9 `unclear`, 0 `no`. The tier finds real
  hospitals, but about half are genuinely uncertain, which is why it is labelled "call to confirm" and ranked
  below strong/moderate evidence.
