-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Evaluation: does a facility really offer the service?
-- MAGIC
-- MAGIC Compares predictions against the hand-labelled set in `eval/labels.csv` (loaded by `eval/run_eval.py`
-- MAGIC into `eval_labels`). A prediction is **positive** when the evidence tier is `strong` or `moderate`
-- MAGIC (and, in the `+probable` row, `probable`). Rows labelled `unclear` are left out of precision and recall.
-- MAGIC
-- MAGIC Versions compared:
-- MAGIC * `keyword_baseline`: positive if any service alias appears anywhere in the record's text (no rules at all)
-- MAGIC * `v1`, ...: frozen tiers from earlier rule versions (`eval/predictions_<version>.csv`)
-- MAGIC * `current`: the live `gold_facility_services`

-- COMMAND ----------

CREATE OR REPLACE VIEW workspace.datathon.eval_preds AS
WITH kw AS (
  SELECT 'keyword_baseline' AS version, l.facility_id, l.service_key,
         CASE WHEN lower(concat_ws(' ', array_join(f.procedures, ' '), array_join(f.capabilities, ' '),
                                   array_join(f.equipment, ' '), f.description))
                   RLIKE concat('\\b(', array_join(s.aliases, '|'), ')') THEN 'match' ELSE 'none' END AS evidence_tier
  FROM workspace.datathon.eval_labels l
  JOIN workspace.datathon.silver_facilities f USING (facility_id)
  JOIN workspace.datathon.ref_services s USING (service_key)
),
cur AS (
  SELECT 'current' AS version, l.facility_id, l.service_key, coalesce(g.evidence_tier, 'none') AS evidence_tier
  FROM workspace.datathon.eval_labels l
  LEFT JOIN workspace.datathon.gold_facility_services g USING (facility_id, service_key)
)
SELECT * FROM kw
UNION ALL SELECT version, facility_id, service_key, evidence_tier FROM workspace.datathon.eval_predictions_frozen
UNION ALL SELECT * FROM cur
UNION ALL SELECT 'current+probable', facility_id, service_key, evidence_tier FROM cur;

-- COMMAND ----------

CREATE OR REPLACE VIEW workspace.datathon.eval_scored AS
SELECT p.version, p.service_key, p.facility_id, l.label, l.facility_name, p.evidence_tier,
       CASE WHEN p.version = 'current+probable' THEN p.evidence_tier IN ('strong', 'moderate', 'probable')
            ELSE p.evidence_tier IN ('strong', 'moderate', 'match') END AS predicted
FROM workspace.datathon.eval_preds p JOIN workspace.datathon.eval_labels l USING (facility_id, service_key);

-- COMMAND ----------

-- Precision / recall per version (all services pooled), then per service
SELECT version, 'ALL' AS service_key,
       count_if(predicted AND label = 'yes') AS tp, count_if(predicted AND label = 'no') AS fp,
       count_if(NOT predicted AND label = 'yes') AS fn,
       round(count_if(predicted AND label = 'yes') / nullif(count_if(predicted AND label IN ('yes', 'no')), 0), 2) AS precision,
       round(count_if(predicted AND label = 'yes') / nullif(count_if(label = 'yes'), 0), 2) AS recall
FROM workspace.datathon.eval_scored GROUP BY version
ORDER BY CASE version WHEN 'keyword_baseline' THEN 0 WHEN 'current' THEN 8 WHEN 'current+probable' THEN 9 ELSE 1 END, version;

-- COMMAND ----------

SELECT service_key, version,
       count_if(predicted AND label = 'yes') AS tp, count_if(predicted AND label = 'no') AS fp,
       count_if(NOT predicted AND label = 'yes') AS fn,
       round(count_if(predicted AND label = 'yes') / nullif(count_if(predicted AND label IN ('yes', 'no')), 0), 2) AS precision,
       round(count_if(predicted AND label = 'yes') / nullif(count_if(label = 'yes'), 0), 2) AS recall
FROM workspace.datathon.eval_scored GROUP BY ALL
ORDER BY service_key, CASE version WHEN 'keyword_baseline' THEN 0 WHEN 'current' THEN 8 WHEN 'current+probable' THEN 9 ELSE 1 END, version;

-- COMMAND ----------

-- Remaining errors in the current rules (false positives first)
SELECT service_key, facility_name, label, evidence_tier,
       CASE WHEN predicted AND label = 'no' THEN 'false positive' ELSE 'missed' END AS error
FROM workspace.datathon.eval_scored
WHERE version = 'current+probable' AND ((predicted AND label = 'no') OR (NOT predicted AND label = 'yes'))
ORDER BY error DESC, service_key;
