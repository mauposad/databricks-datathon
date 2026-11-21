-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 03 · Gold: facility × service evidence
-- MAGIC
-- MAGIC Builds two tables:
-- MAGIC
-- MAGIC * `ref_services`: the services a user can ask for, each defined by transparent keyword rules
-- MAGIC   (what counts as a mention in procedures/capabilities, what counts as supporting equipment, related specialties).
-- MAGIC * `gold_facility_services`: **one row per (facility, service) with any evidence**, including the exact matched
-- MAGIC   phrases (for citation), an evidence tier, a 0–100 trust score, and plain-English caveats.
-- MAGIC
-- MAGIC **Evidence tiers**
-- MAGIC * `strong`: the service is named in procedures/capabilities **and** backed by matching equipment
-- MAGIC   (or named in both procedures and capabilities with 3+ independent source websites)
-- MAGIC * `moderate`: named in procedures or capabilities (or service-specific equipment such as an MRI scanner or
-- MAGIC   dialysis machine is listed), but not corroborated as above. Generic kit (OT, ventilator, C-arm) never counts on its own.
-- MAGIC * `weak`: only implied (related specialty, or only in the free-text description)
-- MAGIC
-- MAGIC **Trust score (0–100)** = evidence (≤60) + source corroboration (≤15) + reported scale (≤10) + location confidence (≤15)
-- MAGIC minus penalties (possible merged record −15, clinic claiming hospital-level care −20, negated/referral mentions −10,
-- MAGIC implausible numbers −5). Every component is stored as its own column so the app can show *how* the score was made.
-- MAGIC
-- MAGIC Requires notebook 02 (`silver_facilities`).

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.ref_services
COMMENT 'Services users can search for, with the keyword rules used to find evidence (regexes are applied to lower-cased text)'
AS SELECT *,
  -- Can equipment alone prove the service? Yes for an MRI/CT scanner, dialysis machine, LINAC or blood bank;
  -- no for generic kit (an operating theatre does not prove C-sections, a ventilator does not prove trauma care).
  service_key IN ('dialysis', 'mri', 'ct_scan', 'oncology', 'blood_bank') AS equipment_alone_counts
FROM VALUES
  ('dialysis', 'Dialysis',
   array('dialysis', 'kidney dialysis', 'haemodialysis', 'hemodialysis', 'renal replacement'),
   'dialysis|haemodialysis|hemodialysis|renal replacement|\\bcrrt\\b',
   'dialysis|dialy[sz]er|\\bcrrt\\b|\\bro (water|plant)',
   array('nephrology'), false),
  ('emergency_csection', 'Emergency C-section',
   array('c-section', 'c section', 'caesarean', 'cesarean', 'emergency c-section', 'lscs'),
   'c-section|c section|caesarean|cesarean|\\blscs\\b',
   'operation theat|operating theat|\\bot\\b|ana?esthesia|fetal monitor|\\bctg\\b',
   array('gynecologyandobstetrics', 'obstetrics', 'maternalfetalmedicineorperinatology'), true),
  ('high_risk_delivery', 'High-risk pregnancy & delivery',
   array('high-risk delivery', 'high risk pregnancy', 'maternity', 'obstetrics', 'delivery', 'labour room'),
   'high[- ]risk (pregnan|obstetric|deliver)|maternal[- ]fetal medicine|perinatolog|labou?r (room|ward|suite)|normal deliver|obstetric (emergenc|icu|care)',
   'fetal monitor|\\bctg\\b|cardiotocograph|labou?r table|delivery table|doppler',
   array('gynecologyandobstetrics', 'maternalfetalmedicineorperinatology'), true),
  ('nicu', 'NICU (newborn intensive care)',
   array('nicu', 'neonatal icu', 'newborn icu', 'neonatal intensive care', 'sncu'),
   '\\bnicu\\b|neonatal intensive|newborn intensive|\\bsncu\\b|level (ii|iii|2|3) neonatal',
   'incubator|radiant warmer|phototherapy|neonatal ventilator|bubble cpap|\\bcpap\\b',
   array('neonatalperinatalmedicine', 'neonatology'), true),
  ('icu', 'ICU / critical care',
   array('icu', 'intensive care', 'critical care', 'ventilator'),
   '\\bicu\\b|\\biccu\\b|\\bmicu\\b|\\bsicu\\b|intensive care|critical care',
   'ventilator|icu bed|multipara|patient monitor|defibrillator',
   array('criticalcaremedicine'), true),
  ('cardiac_surgery', 'Cardiac surgery',
   array('cardiac surgery', 'heart surgery', 'bypass surgery', 'cabg', 'open heart surgery', 'valve replacement'),
   '\\bcabg\\b|bypass (graft|surgery)|open[- ]heart|valve (replacement|repair|surgery)|cardiac surgery|cardiothoracic|heart surgery',
   'heart[- ]lung|cardiopulmonary bypass|\\biabp\\b|intra[- ]aortic|perfusion',
   array('cardiacsurgery', 'cardiothoracicsurgery', 'cardiothoracicandvascularsurgery'), true),
  ('cath_lab', 'Angiography / angioplasty (cath lab)',
   array('angioplasty', 'angiography', 'cath lab', 'stent', 'heart attack', 'pci'),
   'angioplasty|angiograph|cath(eteri[sz]ation)? ?lab|\\bptca\\b|\\bstent|\\bpci\\b',
   'cath ?lab|catheteri[sz]ation lab|\\bdsa\\b|flat panel|c-arm',
   array('cardiology', 'interventionalcardiology'), true),
  ('trauma', 'Trauma & accident care',
   array('trauma', 'accident', 'road accident', 'polytrauma', 'injury'),
   'trauma|polytrauma|accident|road traffic',
   '\\bct\\b|ct scan|ventilator|c-arm|blood bank',
   array('emergencymedicine', 'traumasurgery'), true),
  ('emergency_24x7', '24/7 emergency department',
   array('emergency', 'casualty', '24x7', '24/7 emergency', 'er'),
   '24 ?[x/*] ?7|24 hours? (emergency|casualty)|round[- ]the[- ]clock emergency|emergency (department|ward|room|services?|care|unit)|casualty',
   'ambulance|defibrillator|ventilator|crash cart',
   array('emergencymedicine'), false),
  ('burn_care', 'Burn care',
   array('burn', 'burns', 'burn unit', 'burn ward'),
   '\\bburns?\\b',
   'burn|skin graft|dermatome|air[- ]fluidi[sz]ed',
   array('plasticsurgery', 'burnsurgery', 'plasticandreconstructivesurgery'), true),
  ('mri', 'MRI scan',
   array('mri', 'mri scan', 'magnetic resonance'),
   '\\bmri\\b|magnetic resonance',
   '\\bmri\\b|magnetic resonance|tesla',
   array('radiology'), false),
  ('ct_scan', 'CT scan',
   array('ct', 'ct scan', 'cat scan', 'computed tomography'),
   '\\bct\\b|ct scan|computed tomography|\\bmdct\\b|\\bcect\\b|\\bhrct\\b',
   '\\bct\\b|ct scan|computed tomography|\\bmdct\\b|slice',
   array('radiology'), false),
  ('oncology', 'Cancer treatment (chemo / radiotherapy)',
   array('cancer', 'oncology', 'chemotherapy', 'chemo', 'radiotherapy', 'radiation therapy'),
   'chemotherapy|radiotherapy|radiation therapy|oncology|cancer (surgery|treatment|care)|\\blinac\\b|brachytherapy',
   'linac|linear accelerator|brachytherapy|cobalt|tomotherapy|pet[- ]?ct',
   array('medicaloncology', 'surgicaloncology', 'radiationoncology', 'oncology'), false),
  ('neurosurgery', 'Neurosurgery',
   array('neurosurgery', 'brain surgery', 'spine surgery', 'brain tumour'),
   'neurosurg|brain (surgery|tumou?r)|craniotomy|spin(e|al) surgery',
   'neuro ?navigation|operating microscope|c-arm',
   array('neurosurgery', 'orthopedicspinesurgery'), true),
  ('blood_bank', 'Blood bank / transfusion',
   array('blood bank', 'blood transfusion', 'blood'),
   'blood bank|blood transfusion|blood storage|blood cent(re|er)',
   'blood bank|blood storage|apheresis',
   array('transfusionmedicine'), false),
  ('orthopedic_surgery', 'Orthopaedic surgery / joint replacement',
   array('orthopedic surgery', 'orthopaedic', 'fracture', 'joint replacement', 'knee replacement', 'hip replacement'),
   'joint replacement|knee replacement|hip replacement|arthroplasty|fracture (fixation|surgery|treatment|management)|orthopa?edic surgery|arthroscop',
   'c-arm|arthroscop',
   array('orthopedicsurgery'), false),
  ('cataract', 'Cataract / eye surgery',
   array('cataract', 'eye surgery', 'phaco', 'phacoemulsification'),
   'cataract|phaco|\\biol\\b|intraocular lens',
   'phaco|operating microscope|biometr',
   array('ophthalmology'), false)
AS t(service_key, service_label, aliases, text_regex, equipment_regex, specialties, needs_hospital);

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.gold_facility_services
COMMENT 'Gold: one row per (facility, service) with evidence. Matched phrases are verbatim from the facility record for citation; trust_score components are stored separately for transparency.'
AS
WITH m AS (
  SELECT
    f.facility_id, s.service_key, s.service_label, s.needs_hospital, s.equipment_alone_counts,
    f.name, f.facility_type, f.operator_type, f.lat, f.lon, f.district, f.state, f.pincode, f.address_text,
    f.location_confidence, f.location_note, f.possible_merged_record, f.far_places_in_text, f.quality_flags,
    f.number_doctors, f.capacity_beds, f.year_established, f.n_source_domains, f.source_urls,
    f.official_phone, f.official_website, f.email, f.facebook_link, f.city_raw,
    -- verbatim phrases that mention the service
    filter(f.procedures,   x -> lower(x) RLIKE s.text_regex)      AS proc_hits,
    filter(f.capabilities, x -> lower(x) RLIKE s.text_regex)      AS cap_hits,
    filter(f.equipment,    x -> lower(x) RLIKE s.equipment_regex OR lower(x) RLIKE s.text_regex) AS equip_hits,
    exists(f.equipment,    x -> lower(x) RLIKE s.text_regex)      AS equip_names_service,  -- e.g. "NICU with 25 beds and incubators"
    nullif(regexp_extract(f.description, concat('(?i)([^.]*(?:', s.text_regex, ')[^.]*)'), 1), '') AS desc_hit,
    array_intersect(transform(f.specialties, x -> lower(x)), s.specialties) AS spec_hits
  FROM workspace.datathon.silver_facilities f
  CROSS JOIN workspace.datathon.ref_services s
),
neg AS (  -- separate out negated / referral-only mentions ("no dialysis", "referred to ... for cath lab")
  SELECT m.*,
    filter(concat(proc_hits, cap_hits), x -> lower(x) RLIKE '\\b(no|not|without|lacks?|unavailable|refer(red|ral|s)?)\\b') AS negated_hits
  FROM m
),
e AS (
  SELECT neg.*,
    array_except(proc_hits, negated_hits) AS procedures_cited,
    array_except(cap_hits,  negated_hits) AS capabilities_cited
  FROM neg
),
scored AS (
  SELECT e.*,
    size(procedures_cited) AS n_proc, size(capabilities_cited) AS n_cap,
    -- generic equipment only counts when the service itself is also mentioned
    CASE WHEN equipment_alone_counts OR coalesce(equip_names_service, false)
           OR size(procedures_cited) + size(capabilities_cited) > 0 OR desc_hit IS NOT NULL
         THEN size(equip_hits) ELSE 0 END AS n_equip
  FROM e
),
scored_kept AS (
  SELECT * FROM scored WHERE n_proc + n_cap + n_equip + size(spec_hits) > 0 OR desc_hit IS NOT NULL
),
tiers AS (
  SELECT scored_kept.*,
    CASE
      WHEN (n_proc > 0 OR n_cap > 0) AND n_equip > 0 THEN 'strong'
      WHEN n_proc > 0 AND n_cap > 0 AND n_source_domains >= 3 THEN 'strong'
      WHEN n_proc > 0 OR n_cap > 0 OR n_equip > 0 THEN 'moderate'
      ELSE 'weak'
    END AS evidence_tier,
    -- score components
    least(60,
        CASE WHEN n_proc > 0 THEN 25 ELSE 0 END
      + CASE WHEN n_cap > 0 THEN 15 ELSE 0 END
      + CASE WHEN n_equip > 0 THEN 15 ELSE 0 END
      + CASE WHEN desc_hit IS NOT NULL THEN 5 ELSE 0 END
      + CASE WHEN size(spec_hits) > 0 THEN 5 ELSE 0 END)                         AS pts_evidence,
    3 * least(coalesce(n_source_domains, 0), 5)                                   AS pts_sources,
    CASE WHEN number_doctors IS NOT NULL THEN 5 ELSE 0 END
      + CASE WHEN capacity_beds IS NOT NULL THEN 5 ELSE 0 END                     AS pts_scale,
    CASE location_confidence WHEN 'high' THEN 15 WHEN 'medium' THEN 8 ELSE 0 END  AS pts_location,
    CASE WHEN possible_merged_record THEN -15 ELSE 0 END                          AS pen_merged,
    CASE WHEN needs_hospital AND facility_type IN ('clinic', 'dentist', 'pharmacy', 'doctor') THEN -20 ELSE 0 END AS pen_facility_type,
    CASE WHEN size(negated_hits) > 0 THEN -10 ELSE 0 END                          AS pen_negated,
    CASE WHEN array_contains(quality_flags, 'implausible_number_removed') THEN -5 ELSE 0 END AS pen_numbers
  FROM scored_kept
)
SELECT
  facility_id, service_key, service_label, name, facility_type, operator_type,
  lat, lon, district, state, pincode, address_text, location_confidence, location_note,
  evidence_tier,
  greatest(0, least(100, pts_evidence + pts_sources + pts_scale + pts_location
                         + pen_merged + pen_facility_type + pen_negated + pen_numbers)) AS trust_score,
  pts_evidence, pts_sources, pts_scale, pts_location, pen_merged, pen_facility_type, pen_negated, pen_numbers,
  -- citations (verbatim from the record)
  procedures_cited, capabilities_cited, CASE WHEN n_equip > 0 THEN equip_hits ELSE array() END AS equipment_cited, desc_hit AS description_cited, spec_hits AS specialties_cited,
  negated_hits AS negated_or_referral_mentions,
  concat_ws(' · ',
    CASE WHEN n_proc > 0  THEN concat('Procedures: "', array_join(slice(procedures_cited, 1, 2), '"; "'), '"') END,
    CASE WHEN n_cap > 0   THEN concat('Capabilities: "', array_join(slice(capabilities_cited, 1, 2), '"; "'), '"') END,
    CASE WHEN n_equip > 0 THEN concat('Equipment: "', array_join(slice(equip_hits, 1, 2), '"; "'), '"') END,
    CASE WHEN n_proc + n_cap + n_equip = 0 AND desc_hit IS NOT NULL THEN concat('Description: "', trim(desc_hit), '"') END,
    CASE WHEN n_proc + n_cap + n_equip = 0 AND size(spec_hits) > 0 THEN concat('Specialty listed: ', array_join(spec_hits, ', ')) END
  ) AS evidence_summary,
  array_compact(array(
    CASE WHEN n_proc + n_cap + n_equip = 0 AND desc_hit IS NULL THEN 'Only a related specialty is listed; the service itself is never mentioned.' END,
    CASE WHEN n_proc + n_cap + n_equip = 0 AND desc_hit IS NOT NULL THEN 'Mentioned only in the general description, not in the listed procedures or capabilities.' END,
    CASE WHEN evidence_tier = 'moderate' AND n_equip = 0 THEN 'No supporting equipment is listed for this service.' END,
    CASE WHEN possible_merged_record THEN concat('This record may combine more than one facility (its text also mentions ', array_join(far_places_in_text, ', '), ').') END,
    CASE WHEN pen_facility_type < 0 THEN concat('Listed as a ', facility_type, '; this service normally requires a hospital.') END,
    CASE WHEN size(negated_hits) > 0 THEN concat('Some mentions are negative or referral-only: "', negated_hits[0], '".') END,
    CASE WHEN location_confidence IN ('low', 'none') THEN location_note END,
    CASE WHEN n_source_domains <= 1 THEN 'Backed by a single source website.' END,
    CASE WHEN number_doctors IS NULL AND capacity_beds IS NULL THEN 'Facility size (doctors, beds) is not reported.' END
  )) AS caveats,
  number_doctors, capacity_beds, year_established, n_source_domains, source_urls,
  official_phone, official_website, email, facebook_link, city_raw
FROM tiers;

-- COMMAND ----------

-- Health check: evidence depth per service
SELECT service_key,
       count(*) AS facilities_with_any_evidence,
       count_if(evidence_tier = 'strong')   AS strong,
       count_if(evidence_tier = 'moderate') AS moderate,
       count_if(evidence_tier = 'weak')     AS weak,
       round(avg(trust_score)) AS avg_trust
FROM workspace.datathon.gold_facility_services
GROUP BY service_key ORDER BY facilities_with_any_evidence DESC;
