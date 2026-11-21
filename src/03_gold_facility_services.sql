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
-- MAGIC * `weak`: only implied (related specialty, only in the free-text description, or only guessed, e.g. from photos)
-- MAGIC
-- MAGIC **What counts as a mention** (checked per comma-separated item of each phrase):
-- MAGIC * it matches the service's `text_regex` (or `equipment_regex` for equipment) and **not** its `exclude_regex`
-- MAGIC   (e.g. bile-duct stents are not a cath lab, "atraumatic extraction" is not trauma care, "brain bypass" is not cardiac surgery);
-- MAGIC * it is not about an ambulance or vehicle (an ambulance "labelled ICU, NICU" is not a NICU);
-- MAGIC * the facility is not dental-only (or eye-only, except for cataract): see `scope_family` in silver.
-- MAGIC
-- MAGIC **Claim type of every cited phrase** (stored in `claims_cited` so the app can label each quote):
-- MAGIC
-- MAGIC | claim_type | rule | counts as |
-- MAGIC |---|---|---|
-- MAGIC | `direct` | a plain statement | full evidence |
-- MAGIC | `list_dump` | 8+ comma/semicolon items, or starts "Departments / Specializations / Services include" | at most `moderate`, 10 points |
-- MAGIC | `hedged` | "appears", "likely", "resembles", "visible in photos", "depicted" ... | `weak` only, with a caveat |
-- MAGIC | `third_party` | affiliation / paper / study / partnership, or names a different hospital | nothing (shown, struck through) |
-- MAGIC | `negated` | "no", "not", "without", "referred" (benign uses like "no-stitch" or "License No." excluded) | nothing, −10 penalty |
-- MAGIC
-- MAGIC **Trust score (0–100)** = evidence (≤60) + source corroboration (≤15) + reported scale (≤10) + location confidence (≤15)
-- MAGIC minus penalties (possible merged record −15, clinic claiming hospital-level care −20, negated/referral mentions −10,
-- MAGIC implausible numbers −5). Every component is stored as its own column so the app can show *how* the score was made.
-- MAGIC
-- MAGIC Requires notebook 02 (`silver_facilities`).

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.ref_services
COMMENT 'Services users can search for, with the keyword rules used to find evidence (regexes are applied to lower-cased text)'
AS SELECT t.*,
  -- Can equipment alone prove the service? Yes for an MRI/CT scanner, dialysis machine, LINAC or blood bank;
  -- no for generic kit (an operating theatre does not prove C-sections, a ventilator does not prove trauma care).
  t.service_key IN ('dialysis', 'mri', 'ct_scan', 'oncology', 'blood_bank') AS equipment_alone_counts,
  -- Can a large hospital that lists the specialty be shown as `probable` even if the procedure is never named?
  -- Yes where that department essentially always provides it (an obstetrics department at a 100+ bed or teaching
  -- hospital does C-sections); no where it depends on specific kit (cardiology does not imply a cath lab).
  t.service_key IN ('emergency_csection', 'high_risk_delivery', 'nicu', 'icu', 'trauma', 'cardiac_surgery', 'neurosurgery') AS probable_if_specialty,
  -- A phrase that matches text_regex but also matches exclude_regex is about something else and is ignored.
  x.exclude_regex
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
   '\\bcabg\\b|(coronary|cardiac|heart)[a-z ()-]{0,25}bypass|open[- ]heart|valve (replacement|repair|surgery)|cardiac surgery|cardiothoracic|heart surgery',
   'heart[- ]lung|cardiopulmonary bypass|\\biabp\\b|intra[- ]aortic|perfusion',
   array('cardiacsurgery', 'cardiothoracicsurgery', 'cardiothoracicandvascularsurgery'), true),
  ('cath_lab', 'Angiography / angioplasty (cath lab)',
   array('angioplasty', 'angiography', 'cath lab', 'stent', 'heart attack', 'pci'),
   'angioplasty|angiograph|cath(eteri[sz]ation)? ?lab|\\bptca\\b|\\bstent|\\bpci\\b',
   'cath ?lab|catheteri[sz]ation lab|\\bdsa\\b|flat panel|c-arm',
   array('cardiology', 'interventionalcardiology'), true),
  ('trauma', 'Trauma & accident care',
   array('trauma', 'accident', 'road accident', 'polytrauma', 'injury'),
   '\\btrauma\\b|polytrauma|traumatolog|\\baccidents?\\b|road traffic',
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
AS t(service_key, service_label, aliases, text_regex, equipment_regex, specialties, needs_hospital)
LEFT JOIN VALUES
  -- tooth / facial trauma in dentistry, psychological trauma, "cerebrovascular accident" (= stroke)
  ('trauma', 'dental|dentist|tooth|teeth|oral surgeon|orthodont|maxillofacial|\\bjaw\\b|psycholog|emotional|counsel|ptsd|cerebro ?vascular accident'),
  -- bile duct / ureteric / GI stents are not a cath lab, unless the same phrase is clearly coronary
  ('cath_lab', '^(?!.*(angioplast|coronary|cardiac|cath ?lab|ptca|heart)).*(bile|biliary|ureter|\\bdj\\b|\\bpcn\\b|ptbd|ercp|esophag|oesophag|colonic|duodenal|pancrea|enteral)'),
  -- brain / gastric / peripheral bypass is not cardiac surgery
  ('cardiac_surgery', 'brain bypass|gastric bypass|blood vessel bypass|vascular bypass|femoro|fem-pop|bariatric'),
  ('burn_care', 'heartburn|burning (sensation|micturition|feet|eyes)'),
  ('mri', 'mri (report|referral|film)s?\\b')
AS x(service_key, exclude_regex) ON x.service_key = t.service_key;

-- COMMAND ----------

-- Is this phrase a mention of the service? It must match the service's regex, must not match its exclusion regex,
-- and must not be about an ambulance/vehicle (an ambulance "labelled ICU, NICU" is not a NICU), except for the
-- 24/7 emergency service where an ambulance is genuine supporting equipment.
-- Checked per comma/semicolon item, so "Maxillofacial Surgery, ..., Emergency Medicine & Accident" still counts
-- for trauma: the exclusion only removes the item it is in.
CREATE OR REPLACE FUNCTION workspace.datathon.phrase_matches(phrase STRING, pattern STRING, exclude_pattern STRING, service_key STRING)
RETURNS BOOLEAN
RETURN exists(split(lower(phrase), '[,;]'), item ->
       item RLIKE pattern
   AND NOT coalesce(item RLIKE exclude_pattern, false)
   AND NOT (service_key <> 'emergency_24x7' AND item RLIKE '\\b(ambulances?|vehicles?|vans?)\\b'));

-- COMMAND ----------

-- Claim type of a cited phrase. Only `direct` claims count fully; `list_dump` counts at most as moderate evidence;
-- `hedged` (guessed from photos, "appears to") counts as weak only; `third_party` and `negated` never count.
CREATE OR REPLACE FUNCTION workspace.datathon.claim_type(phrase STRING, own_name STRING)
RETURNS STRING
RETURN CASE
  -- "no", "without", "referred" ... but not benign uses: "no-stitch", "at no cost", "License No. 16", "with or without stent"
  WHEN lower(phrase) RLIKE '\\b(no|not|without|lacks?|unavailable|refer(red|ral|s)?)\\b'
   AND NOT lower(phrase) RLIKE 'with or without|\\bno\\.?:?\\s*[0-9]|(contact|phone|mobile|tel) no|licen[cs]e no|reg(istration|d)?\\.? no|\\bno[- ](extra )?(cost|charge|stitch|scalpel|scar|pain|waiting|blade|needle|injection|eye patch|bandage)|not only|without (any )?(stitch|scar|pain|cuts?|bypass|incision|open surgery|blade|needle|injection|holidays?|break|disruption|interruption)|referral (hospital|cent(re|er)|institute)'
    THEN 'negated'
  -- affiliations, partnerships, publications ... unless the phrase names the facility itself
  -- ("Dr X is affiliated with <this hospital>", "ICU run through a partnership at <this hospital>")
  WHEN lower(phrase) RLIKE 'affiliat|\\bpapers?\\b|multicent|(prospective|retrospective|clinical|research|cohort) (study|trial)|partner(ed|ship| with)|tie[- ]?up|in association with|collaborat|journal|abstract|published|conference|consensus'
   AND NOT exists(split(lower(own_name), '[^a-z]+'), o -> length(o) >= 5 AND contains(lower(phrase), o)
          AND o NOT IN ('hospital', 'hospitals', 'medical', 'clinic', 'centre', 'center', 'super', 'speciality', 'specialty',
                        'multi', 'memorial', 'institute', 'sciences', 'research', 'general', 'district', 'government',
                        'civil', 'nursing', 'charitable', 'healthcare', 'international', 'college', 'trust', 'foundation'))
    THEN 'third_party'
  WHEN lower(phrase) RLIKE '\\b(appears?|appearing|likely|resembl\\w*|consistent with|suggests?|suggesting|possibly|probably|seems?|might|could be|may be|depicted|referenced|indicates?|presumably)\\b|visible in (the )?(facility )?photos?|in (the )?(facility )?photos?|photo(graph)?s? (show|depict)'
    THEN 'hedged'
  WHEN size(split(phrase, '[,;]')) >= 8
    OR lower(phrase) RLIKE '^\\s*(departments?|speciali[sz]ations?|specialit(y|ies)|specialt(y|ies)|super[- ]?specialit(y|ies)|services)( include| offered| available| such as| like|:)'
    THEN 'list_dump'
  WHEN workspace.datathon.mentions_other_facility(phrase, own_name) THEN 'third_party'
  ELSE 'direct'
END;

-- COMMAND ----------

-- Every claim phrase of every facility, one row each, with the field it came from and its position.
-- Specialties are included (field = 'specialties') for the evidence checklist; the service matcher ignores them.
CREATE OR REPLACE TABLE workspace.datathon.facility_phrases
COMMENT 'One row per verbatim phrase in a facility record (procedures, capabilities, equipment, description sentences, specialties)'
AS
SELECT facility_id, name, 'procedures' AS field, pos, text FROM workspace.datathon.silver_facilities LATERAL VIEW posexplode(procedures) t AS pos, text
UNION ALL
SELECT facility_id, name, 'capabilities', pos, text FROM workspace.datathon.silver_facilities LATERAL VIEW posexplode(capabilities) t AS pos, text
UNION ALL
SELECT facility_id, name, 'equipment', pos, text FROM workspace.datathon.silver_facilities LATERAL VIEW posexplode(equipment) t AS pos, text
UNION ALL  -- description, split into sentences
SELECT facility_id, name, 'description', pos, trim(text) FROM workspace.datathon.silver_facilities
LATERAL VIEW posexplode(split(coalesce(description, ''), '\\.(\\s|$)')) t AS pos, text
WHERE length(trim(text)) > 0
UNION ALL
SELECT facility_id, name, 'specialties', pos, text FROM workspace.datathon.silver_facilities LATERAL VIEW posexplode(specialties) t AS pos, text;

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.gold_facility_services
COMMENT 'Gold: one row per (facility, service) with evidence. Matched phrases are verbatim from the facility record for citation, each labelled with a claim type; trust_score components are stored separately for transparency.'
AS
WITH phrases AS (
  SELECT * FROM workspace.datathon.facility_phrases WHERE field <> 'specialties'
),
matched AS (  -- phrases that mention a service (regex hit, not excluded), classified by claim type
  SELECT p.facility_id, s.service_key, p.field, p.pos, p.text,
         workspace.datathon.claim_type(p.text, p.name) AS claim_type
  FROM phrases p
  JOIN workspace.datathon.ref_services s
    ON workspace.datathon.phrase_matches(p.text,
         CASE WHEN p.field = 'equipment' THEN concat(s.equipment_regex, '|', s.text_regex) ELSE s.text_regex END,
         s.exclude_regex, s.service_key)
),
matched_agg AS (
  SELECT facility_id, service_key,
    transform(array_sort(collect_list(CASE WHEN field <> 'description' THEN
        named_struct('k', concat(CASE field WHEN 'procedures' THEN '1' WHEN 'capabilities' THEN '2' ELSE '3' END, lpad(CAST(pos AS STRING), 4, '0')),
                     'text', text, 'field', field, 'claim_type', claim_type) END)),
      c -> named_struct('text', c.text, 'field', c.field, 'claim_type', c.claim_type)) AS claims_cited,
    array_sort(collect_list(CASE WHEN field = 'description' THEN named_struct('pos', pos, 'text', text, 'claim_type', claim_type) END)) AS desc_claims
  FROM matched
  GROUP BY facility_id, service_key
),
claims AS (
  SELECT
    f.facility_id, s.service_key, s.service_label, s.needs_hospital, s.equipment_alone_counts, s.text_regex,
    f.name, f.facility_type, f.operator_type, f.lat, f.lon, f.district, f.state, f.pincode, f.address_text,
    f.location_confidence, f.location_note, f.possible_merged_record, f.far_places_in_text, f.quality_flags,
    f.number_doctors, f.capacity_beds, f.year_established, f.n_source_domains, f.source_urls,
    f.official_phone, f.official_website, f.email, f.facebook_link, f.city_raw, f.scope_family,
    coalesce(m.claims_cited, array()) AS claims_cited,
    coalesce(m.desc_claims, array()) AS desc_claims,
    array_intersect(transform(f.specialties, x -> lower(x)), s.specialties) AS spec_hits
  FROM workspace.datathon.silver_facilities f
  CROSS JOIN workspace.datathon.ref_services s
  LEFT JOIN matched_agg m ON m.facility_id = f.facility_id AND m.service_key = s.service_key
  -- specialty scope gate: dental-only facilities match nothing here; eye-only facilities only match cataract
  WHERE NOT coalesce(f.scope_family = 'dental', false)
    AND NOT coalesce(f.scope_family = 'eye' AND s.service_key <> 'cataract', false)
),
counted AS (
  SELECT claims.*,
    transform(filter(claims_cited, c -> c.field = 'procedures'   AND c.claim_type IN ('direct', 'list_dump')), c -> c.text) AS procedures_cited,
    transform(filter(claims_cited, c -> c.field = 'capabilities' AND c.claim_type IN ('direct', 'list_dump')), c -> c.text) AS capabilities_cited,
    transform(filter(claims_cited, c -> c.field = 'equipment'    AND c.claim_type IN ('direct', 'list_dump')), c -> c.text) AS equip_hits,
    transform(filter(claims_cited, c -> c.claim_type = 'negated'), c -> c.text)     AS negated_hits,
    transform(filter(claims_cited, c -> c.claim_type = 'hedged'), c -> c.text)      AS hedged_hits,
    transform(filter(claims_cited, c -> c.claim_type = 'third_party'), c -> c.text) AS third_party_hits,
    size(filter(claims_cited, c -> c.field = 'procedures'   AND c.claim_type = 'direct')) AS n_proc,
    size(filter(claims_cited, c -> c.field = 'capabilities' AND c.claim_type = 'direct')) AS n_cap,
    size(filter(claims_cited, c -> c.field IN ('procedures', 'capabilities') AND c.claim_type = 'list_dump')) AS n_list,
    -- e.g. "NICU with 25 beds and incubators": an equipment line that itself names the service
    exists(claims_cited, c -> c.field = 'equipment' AND c.claim_type = 'direct' AND lower(c.text) RLIKE text_regex) AS equip_names_service,
    get(filter(desc_claims, d -> d.claim_type IN ('direct', 'list_dump')), 0).text AS desc_hit
  FROM claims
),
scored AS (
  SELECT counted.*,
    -- generic equipment only counts when the service itself is also mentioned
    CASE WHEN equipment_alone_counts OR equip_names_service OR n_proc + n_cap + n_list > 0 OR desc_hit IS NOT NULL
         THEN size(equip_hits) ELSE 0 END AS n_equip
  FROM counted
),
scored_kept AS (
  SELECT * FROM scored
  WHERE n_proc + n_cap + n_list + n_equip + size(spec_hits) + size(hedged_hits) > 0 OR desc_hit IS NOT NULL
),
tiers AS (
  SELECT scored_kept.*,
    CASE
      WHEN (n_proc > 0 OR n_cap > 0) AND n_equip > 0 THEN 'strong'
      WHEN n_proc > 0 AND n_cap > 0 AND n_source_domains >= 3 THEN 'strong'
      WHEN n_proc > 0 OR n_cap > 0 OR n_equip > 0 OR n_list > 0 THEN 'moderate'
      ELSE 'weak'
    END AS evidence_tier,
    -- score components
    least(60,
        CASE WHEN n_proc > 0 THEN 25 ELSE 0 END
      + CASE WHEN n_cap > 0 THEN 15 ELSE 0 END
      + CASE WHEN n_proc + n_cap = 0 AND n_list > 0 THEN 10 ELSE 0 END   -- named only inside a long department list
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
  -- citations (verbatim from the record); only claims that count are in *_cited, every hit is in claims_cited
  procedures_cited, capabilities_cited, CASE WHEN n_equip > 0 THEN equip_hits ELSE array() END AS equipment_cited, desc_hit AS description_cited, spec_hits AS specialties_cited,
  negated_hits AS negated_or_referral_mentions,
  concat_ws(' · ',
    CASE WHEN size(procedures_cited) > 0   THEN concat('Procedures: "', array_join(slice(procedures_cited, 1, 2), '"; "'), '"') END,
    CASE WHEN size(capabilities_cited) > 0 THEN concat('Capabilities: "', array_join(slice(capabilities_cited, 1, 2), '"; "'), '"') END,
    CASE WHEN n_equip > 0 THEN concat('Equipment: "', array_join(slice(equip_hits, 1, 2), '"; "'), '"') END,
    CASE WHEN n_proc + n_cap + n_list + n_equip = 0 AND desc_hit IS NOT NULL THEN concat('Description: "', trim(desc_hit), '"') END,
    CASE WHEN n_proc + n_cap + n_list + n_equip = 0 AND desc_hit IS NULL AND size(hedged_hits) > 0 THEN concat('Unconfirmed: "', get(hedged_hits, 0), '"') END,
    CASE WHEN n_proc + n_cap + n_list + n_equip = 0 AND size(spec_hits) > 0 THEN concat('Specialty listed: ', array_join(spec_hits, ', ')) END
  ) AS evidence_summary,
  array_compact(array(
    CASE WHEN n_proc + n_cap + n_list + n_equip = 0 AND desc_hit IS NULL AND size(hedged_hits) = 0 THEN 'Only a related specialty is listed; the service itself is never mentioned.' END,
    CASE WHEN n_proc + n_cap + n_list + n_equip = 0 AND desc_hit IS NOT NULL THEN 'Mentioned only in the general description, not in the listed procedures or capabilities.' END,
    CASE WHEN n_proc + n_cap = 0 AND n_list > 0 THEN 'The service is named only inside a long list of departments, not as a stated service.' END,
    CASE WHEN size(hedged_hits) > 0 THEN concat('Some evidence is a guess, not a statement (e.g. from photos): "', get(hedged_hits, 0), '". It does not count as confirmation.') END,
    CASE WHEN size(third_party_hits) > 0 THEN concat('Some mentions refer to another institution or a publication, not this facility''s own service: "', get(third_party_hits, 0), '".') END,
    CASE WHEN evidence_tier = 'moderate' AND n_equip = 0 THEN 'No supporting equipment is listed for this service.' END,
    CASE WHEN possible_merged_record THEN concat('This record may combine more than one facility (its text also mentions ', array_join(far_places_in_text, ', '), ').') END,
    CASE WHEN pen_facility_type < 0 THEN concat('Listed as a ', facility_type, '; this service normally requires a hospital.') END,
    CASE WHEN size(negated_hits) > 0 THEN concat('Some mentions are negative or referral-only: "', get(negated_hits, 0), '".') END,
    CASE WHEN location_confidence IN ('low', 'none') THEN location_note END,
    CASE WHEN n_source_domains <= 1 THEN 'Backed by a single source website.' END,
    CASE WHEN array_contains(quality_flags, 'implausible_doctor_count') THEN 'The reported doctor count is implausibly low for the bed count, so it is not shown.' END,
    CASE WHEN number_doctors IS NULL AND capacity_beds IS NULL THEN 'Facility size (doctors, beds) is not reported.' END
  )) AS caveats,
  number_doctors, capacity_beds, year_established, n_source_domains, source_urls,
  official_phone, official_website, email, facebook_link, city_raw,
  -- appended: every matched phrase with its field and claim type (direct, list_dump, hedged, third_party, negated)
  claims_cited, n_proc + n_cap AS n_direct_mentions, n_list AS n_list_mentions, scope_family, quality_flags
FROM tiers;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Evidence checklist for the headline services
-- MAGIC
-- MAGIC For dialysis, emergency C-section, NICU, trauma, cardiac surgery and MRI, the evidence points (≤60) come from a
-- MAGIC list of **evidence dimensions** instead of the generic keyword rule. These are things a record can say that make
-- MAGIC the service more credible; they are *not a clinical checklist* and not a standard of care.
-- MAGIC
-- MAGIC * a check is `found` when a direct (or department-list) phrase in the listed fields matches its regex, or when the
-- MAGIC   linked service (e.g. blood bank for C-section) has strong/moderate evidence at the same facility;
-- MAGIC * `contradicted` when the only matching phrase is negative ("no in-house CT scanner");
-- MAGIC * `unknown` otherwise. **Missing is unknown: 0 points, never a penalty.**
-- MAGIC
-- MAGIC Points per service sum to 60, so `pts_evidence` keeps its range.

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.ref_service_requirements
COMMENT 'Evidence dimensions per headline service (not a clinical checklist). Points per service sum to 60. Regexes are applied to lower-cased phrases.'
AS SELECT * FROM VALUES
  ('emergency_csection', 1, 'csection_named', 'C-section named explicitly',
   'c-section|c section|caesarean|cesarean|\\blscs\\b', array('procedures', 'capabilities', 'equipment', 'description'), 20, CAST(NULL AS STRING)),
  ('emergency_csection', 2, 'operating_theatre', 'Operating theatre',
   'operation theat|operating theat|\\bots?\\b|operating room|surgical suite', array('equipment', 'capabilities', 'description'), 10, NULL),
  ('emergency_csection', 3, 'anaesthesia', 'Anaesthesia',
   'ana?esthe', array('specialties', 'equipment', 'capabilities', 'procedures'), 10, NULL),
  ('emergency_csection', 4, 'blood', 'Blood available on site',
   'blood bank|blood storage|blood transfusion|blood cent(re|er)', array('capabilities', 'equipment', 'description'), 10, 'blood_bank'),
  ('emergency_csection', 5, 'obstetrics_dept', 'Obstetrics department',
   'obstetric|gyn(a)?ecolog|maternity', array('specialties', 'capabilities', 'procedures'), 5, NULL),
  ('emergency_csection', 6, 'round_the_clock', '24×7 / emergency cover',
   '24 ?[x/*] ?7|24 hours|round[- ]the[- ]clock|emergency obstetric|casualty|emergency (department|services?|care|ward|room|unit)', array('capabilities', 'procedures', 'description'), 5, 'emergency_24x7'),

  ('nicu', 1, 'nicu_named', 'NICU named explicitly',
   '\\bnicu\\b|neonatal intensive|newborn intensive|\\bsncu\\b|neonatal icu|level (ii|iii|2|3) neonatal', array('procedures', 'capabilities', 'equipment', 'description'), 20, NULL),
  ('nicu', 2, 'neonatal_equipment', 'Neonatal equipment (incubator, warmer, phototherapy, CPAP)',
   'incubator|radiant warmer|infant warmer|phototherapy|neonatal ventilator|bubble cpap|\\bcpap\\b', array('equipment', 'capabilities', 'procedures'), 15, NULL),
  ('nicu', 3, 'neonatology_dept', 'Neonatology department',
   'neonat|perinat', array('specialties', 'capabilities'), 10, NULL),
  ('nicu', 4, 'nicu_scale', 'NICU level or bed count stated',
   'level (ii|iii|iv|2|3|4)\\b|\\b[0-9]+[- ]?(bed(ded)?|cots?)\\b[^,;]{0,25}(nicu|neonatal)|(nicu|neonatal icu)[^,;]{0,25}\\b[0-9]+[- ]?(beds?|cots?)\\b', array('procedures', 'capabilities', 'equipment', 'description'), 5, NULL),
  ('nicu', 5, 'obstetrics_onsite', 'Deliveries on site',
   'obstetric|gyn(a)?ecolog|maternity|labou?r room|deliver', array('specialties', 'capabilities', 'procedures'), 5, NULL),
  ('nicu', 6, 'round_the_clock', '24×7 cover',
   '24 ?[x/*] ?7|24 hours|round[- ]the[- ]clock', array('capabilities', 'procedures', 'description'), 5, 'emergency_24x7'),

  ('dialysis', 1, 'dialysis_named', 'Dialysis named explicitly',
   'dialysis|haemodialysis|hemodialysis|renal replacement|\\bcrrt\\b', array('procedures', 'capabilities', 'description'), 20, NULL),
  ('dialysis', 2, 'dialysis_equipment', 'Dialysis machines / unit',
   'dialysis (machine|unit|cent(re|er)|station|chair|bed|ward)|dialy[sz]er|h(a)?emodialysis machine|\\bro (water|plant)|\\bcrrt\\b', array('equipment', 'capabilities'), 15, NULL),
  ('dialysis', 3, 'nephrology', 'Nephrology department',
   'nephrolog', array('specialties', 'capabilities', 'procedures'), 10, NULL),
  ('dialysis', 4, 'dialysis_scale', 'Number of machines / beds stated',
   '\\b[0-9]+[- ]?(dialysis )?(machines?|stations?|chairs?|beds?)\\b[^,;]{0,25}dialysis|dialysis[^,;]{0,30}\\b[0-9]+[- ]?(machines?|stations?|chairs?|beds?)\\b', array('procedures', 'capabilities', 'equipment', 'description'), 5, NULL),
  ('dialysis', 5, 'icu', 'ICU on site',
   NULL, array('capabilities'), 5, 'icu'),
  ('dialysis', 6, 'round_the_clock', '24×7 / emergency dialysis',
   '24 ?[x/*] ?7|24 hours|round[- ]the[- ]clock|emergency dialysis', array('capabilities', 'procedures', 'description'), 5, NULL),

  ('trauma', 1, 'trauma_named', 'Trauma / accident care named explicitly',
   '\\btrauma\\b|polytrauma|traumatolog|\\baccidents?\\b|road traffic', array('procedures', 'capabilities', 'description'), 20, NULL),
  ('trauma', 2, 'emergency_dept', 'Emergency department / casualty',
   'casualty|emergency (department|ward|room|unit|services?)|accident (and|&) emergency', array('capabilities', 'procedures', 'description'), 10, 'emergency_24x7'),
  ('trauma', 3, 'ct_scan', 'CT scanner',
   '\\bct\\b|ct scan|computed tomography', array('equipment', 'capabilities'), 10, 'ct_scan'),
  ('trauma', 4, 'blood', 'Blood bank',
   'blood bank|blood storage|blood transfusion', array('capabilities', 'equipment'), 5, 'blood_bank'),
  ('trauma', 5, 'icu', 'ICU',
   '\\bicu\\b|intensive care|critical care', array('capabilities', 'equipment'), 5, 'icu'),
  ('trauma', 6, 'surgical_specialties', 'Orthopaedic / neuro / general surgery',
   'orthop|neurosurg|traumasurg|trauma surg|generalsurg|general surg', array('specialties'), 5, NULL),
  ('trauma', 7, 'round_the_clock', '24×7 cover',
   '24 ?[x/*] ?7|24 hours|round[- ]the[- ]clock', array('capabilities', 'procedures', 'description'), 5, NULL),

  ('cardiac_surgery', 1, 'cardiac_surgery_named', 'Cardiac surgery named explicitly',
   '\\bcabg\\b|(coronary|cardiac|heart)[a-z ()-]{0,25}bypass|open[- ]heart|valve (replacement|repair|surgery)|cardiac surgery|cardiothoracic|heart surgery', array('procedures', 'capabilities', 'description'), 20, NULL),
  ('cardiac_surgery', 2, 'cardiac_ot_equipment', 'Heart-lung machine / cardiac OT',
   'heart[- ]lung|cardiopulmonary bypass|perfusion|\\biabp\\b|intra[- ]aortic|ecmo|cardiac (surgery )?(ot|operation theat)|cardiothoracic (ot|operation theat)|ctvs ot', array('equipment', 'capabilities'), 15, NULL),
  ('cardiac_surgery', 3, 'cath_lab', 'Cath lab',
   'cath ?lab|catheteri[sz]ation lab', array('equipment', 'capabilities'), 10, 'cath_lab'),
  ('cardiac_surgery', 4, 'cardiac_surgery_dept', 'Cardiac / cardiothoracic surgery department',
   'cardiacsurg|cardiothoracic|cardiovascular ?surg|\\bctvs\\b|cardiac surg', array('specialties', 'capabilities'), 5, NULL),
  ('cardiac_surgery', 5, 'cardiac_icu', 'Cardiac ICU / CCU',
   'iccu|\\bccu\\b|cardiac (icu|intensive)|cticu|cvtsicu|coronary care', array('capabilities', 'equipment'), 5, NULL),
  ('cardiac_surgery', 6, 'blood', 'Blood bank',
   'blood bank|blood storage|blood transfusion', array('capabilities', 'equipment'), 5, 'blood_bank'),

  ('mri', 1, 'mri_scanner', 'MRI scanner listed as equipment',
   '\\bmri\\b|magnetic resonance', array('equipment'), 25, NULL),
  ('mri', 2, 'mri_named', 'MRI offered as a service',
   '\\bmri\\b|magnetic resonance', array('procedures', 'capabilities', 'description'), 20, NULL),
  ('mri', 3, 'field_strength', 'Field strength stated (e.g. 1.5T, 3T)',
   '\\b(0\\.[0-9]+|1\\.5|3(\\.0)?) ?(t|tesla)\\b', array('equipment', 'capabilities', 'procedures'), 10, NULL),
  ('mri', 4, 'radiology_dept', 'Radiology department',
   'radiolog', array('specialties', 'capabilities'), 5, NULL)
AS t(service_key, check_order, check_key, check_label, regex, fields, points, links_service);

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.gold_facility_service_checks
COMMENT 'One row per (facility, headline service, evidence dimension): found / unknown / contradicted, with the verbatim phrase that decided it. Missing = unknown, never a penalty.'
AS
WITH cr AS (  -- every candidate facility x service, crossed with that service's checks
  SELECT g.facility_id, g.service_key, g.name, r.check_order, r.check_key, r.check_label, r.regex, r.fields,
         r.points, r.links_service, s.exclude_regex
  FROM workspace.datathon.gold_facility_services g
  JOIN workspace.datathon.ref_service_requirements r USING (service_key)
  JOIN workspace.datathon.ref_services s USING (service_key)
),
text_hits AS (
  SELECT cr.facility_id, cr.service_key, cr.check_key, p.field, p.pos, p.text,
         CASE WHEN p.field = 'specialties' THEN 'direct' ELSE workspace.datathon.claim_type(p.text, cr.name) END AS claim_type
  FROM cr
  JOIN workspace.datathon.facility_phrases p
    ON p.facility_id = cr.facility_id AND array_contains(cr.fields, p.field)
  WHERE cr.regex IS NOT NULL
    AND workspace.datathon.phrase_matches(p.text, cr.regex, cr.exclude_regex, cr.service_key)
),
best AS (  -- the most convincing phrase per check: direct > department list > negated > hedged > third party
  SELECT facility_id, service_key, check_key,
         min_by(named_struct('text', text, 'field', field, 'claim_type', claim_type),
                CASE claim_type WHEN 'direct' THEN 0 WHEN 'list_dump' THEN 1 WHEN 'negated' THEN 2 WHEN 'hedged' THEN 3 ELSE 4 END * 100000
              + CASE field WHEN 'procedures' THEN 0 WHEN 'capabilities' THEN 1 WHEN 'equipment' THEN 2 WHEN 'specialties' THEN 3 ELSE 4 END * 10000
              + pos) AS hit
  FROM text_hits
  GROUP BY facility_id, service_key, check_key
),
linked AS (  -- the supporting service has its own strong/moderate evidence at this facility
  SELECT cr.facility_id, cr.service_key, cr.check_key,
         l.service_label AS linked_label, l.evidence_tier AS linked_tier, l.evidence_summary AS linked_summary
  FROM cr
  JOIN workspace.datathon.gold_facility_services l
    ON l.facility_id = cr.facility_id AND l.service_key = cr.links_service AND l.evidence_tier IN ('strong', 'moderate')
),
decided AS (
  SELECT cr.*, b.hit, lk.linked_label, lk.linked_tier, lk.linked_summary,
    CASE WHEN b.hit.claim_type IN ('direct', 'list_dump') OR lk.linked_tier IS NOT NULL THEN 'found'
         WHEN b.hit.claim_type = 'negated' THEN 'contradicted'
         ELSE 'unknown' END AS status
  FROM cr
  LEFT JOIN best b USING (facility_id, service_key, check_key)
  LEFT JOIN linked lk USING (facility_id, service_key, check_key)
)
SELECT facility_id, service_key, check_order, check_key, check_label, status,
  CASE WHEN status = 'found' THEN points ELSE 0 END AS points,
  points AS max_points,
  CASE WHEN hit.claim_type IN ('direct', 'list_dump') OR linked_tier IS NULL THEN hit.text
       ELSE concat(linked_label, ' (', linked_tier, ' evidence): ', linked_summary) END AS cited_text,
  CASE WHEN hit.claim_type IN ('direct', 'list_dump') OR linked_tier IS NULL THEN hit.field
       ELSE concat('service:', links_service) END AS field,
  CASE WHEN hit.claim_type IN ('direct', 'list_dump') OR linked_tier IS NULL THEN hit.claim_type END AS claim_type,
  links_service
FROM decided;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Final gold: checklist points and the `probable` tier
-- MAGIC
-- MAGIC * Headline services: `pts_evidence` = sum of found checks (`evidence_method = 'checklist'`); the keyword-rule
-- MAGIC   points are kept as `pts_evidence_rules`. Other services keep the keyword rule.
-- MAGIC * **`probable`** (between moderate and weak): the procedure itself is never named, but the facility lists the
-- MAGIC   service's specialty **and** is large (100+ beds) or a teaching/district hospital (medical college, AIIMS,
-- MAGIC   institute of medical sciences, district hospital). Only where `ref_services.probable_if_specialty` (C-section, NICU,
-- MAGIC   ICU, trauma, cardiac surgery, neurosurgery, high-risk delivery), never for kit-dependent services like MRI, dialysis or cath lab.
-- MAGIC   Tier order: strong > moderate > probable > weak.

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.gold_facility_services
COMMENT 'Gold: one row per (facility, service) with evidence. Matched phrases are verbatim from the facility record for citation, each labelled with a claim type; trust_score components are stored separately for transparency. Tiers: strong > moderate > probable > weak.'
AS
WITH ck AS (
  SELECT facility_id, service_key,
         sum(points) AS pts_checklist,
         count_if(status = 'found') AS checks_found,
         count(*) AS checks_total,
         transform(array_sort(collect_list(named_struct(
             'o', check_order, 'check_key', check_key, 'check_label', check_label, 'status', status,
             'points', points, 'max_points', max_points, 'cited_text', cited_text, 'field', field, 'claim_type', claim_type))),
           c -> named_struct('check_key', c.check_key, 'check_label', c.check_label, 'status', c.status,
                             'points', c.points, 'max_points', c.max_points, 'cited_text', c.cited_text,
                             'field', c.field, 'claim_type', c.claim_type)) AS evidence_checks
  FROM workspace.datathon.gold_facility_service_checks
  GROUP BY facility_id, service_key
),
spec_label(spec, label) AS (VALUES
  ('gynecologyandobstetrics', 'Obstetrics & Gynaecology'), ('obstetrics', 'Obstetrics'),
  ('maternalfetalmedicineorperinatology', 'Maternal-Fetal Medicine'), ('neonatalperinatalmedicine', 'Neonatology'),
  ('neonatology', 'Neonatology'), ('criticalcaremedicine', 'Critical Care'), ('emergencymedicine', 'Emergency Medicine'),
  ('traumasurgery', 'Trauma Surgery'), ('cardiacsurgery', 'Cardiac Surgery'), ('cardiothoracicsurgery', 'Cardiothoracic Surgery'),
  ('cardiothoracicandvascularsurgery', 'Cardiothoracic & Vascular Surgery'), ('cardiology', 'Cardiology'),
  ('interventionalcardiology', 'Interventional Cardiology'), ('neurosurgery', 'Neurosurgery'),
  ('orthopedicspinesurgery', 'Spine Surgery'), ('plasticsurgery', 'Plastic Surgery'), ('burnsurgery', 'Burn Surgery'),
  ('plasticandreconstructivesurgery', 'Plastic & Reconstructive Surgery')
),
base AS (
  SELECT g.*, s.needs_hospital, ck.pts_checklist, ck.checks_found, ck.checks_total, ck.evidence_checks,
    coalesce(sl.label, get(g.specialties_cited, 0)) AS spec_pretty,
    g.evidence_tier = 'weak' AND s.probable_if_specialty AND size(g.specialties_cited) > 0
      AND coalesce(g.facility_type, '') NOT IN ('clinic', 'dentist', 'pharmacy', 'doctor')
      AND (coalesce(g.capacity_beds, 0) >= 100
           OR lower(g.name) RLIKE 'medical college|institute of medical sciences|\\baiims\\b|all india institute|medical university|district hospital')
      -- a name that declares a different focus rules it out ("... Cancer Hospital" for C-section), but a matching
      -- focus is fine ("... Children Hospital" for NICU, "... Heart Institute" for cardiac surgery)
      AND (name_focus IS NULL OR array_contains(CASE name_focus
            WHEN 'women'    THEN array('emergency_csection', 'high_risk_delivery', 'nicu')
            WHEN 'children' THEN array('nicu', 'icu')
            WHEN 'heart'    THEN array('cardiac_surgery', 'icu')
            WHEN 'neuro'    THEN array('neurosurgery', 'trauma', 'icu')
            WHEN 'ortho'    THEN array('trauma')
            ELSE array() END, g.service_key))
      AS is_probable
  FROM workspace.datathon.gold_facility_services g
  JOIN workspace.datathon.ref_services s USING (service_key)
  LEFT JOIN ck USING (facility_id, service_key)
  LEFT JOIN spec_label sl ON sl.spec = get(g.specialties_cited, 0)
  LEFT JOIN LATERAL (SELECT CASE
      WHEN lower(g.name) RLIKE 'women|maternity|mother|matru|obstetric|gyn(a)?ec|\\bivf\\b|fertility' THEN 'women'
      WHEN lower(g.name) RLIKE 'child|kids|paediatric|pediatric|shishu|neonat|newborn' THEN 'children'
      WHEN lower(g.name) RLIKE 'heart|cardiac|cardio' THEN 'heart'
      WHEN lower(g.name) RLIKE 'neuro|brain|spine' THEN 'neuro'
      WHEN lower(g.name) RLIKE 'ortho|\\bbone|joint|fracture|accident' THEN 'ortho'
      WHEN lower(g.name) RLIKE 'cancer|oncolog|\\beye\\b|netra|nethra|vision|kidney|nephro|urolog|dental|\\bskin\\b|derma|psychiatr|mental|rehab|\\bent\\b|diagnostic|imaging|\\bscan|\\blab(s|oratory)?\\b|ayurved|homoeo|homeo' THEN 'other'
    END AS name_focus) nf
),
pts AS (
  SELECT base.*,
    pts_evidence AS pts_evidence_rules,
    CASE WHEN pts_checklist IS NOT NULL THEN least(60, pts_checklist) ELSE pts_evidence END AS pts_evidence_final
  FROM base
)
SELECT
  facility_id, service_key, service_label, name, facility_type, operator_type,
  lat, lon, district, state, pincode, address_text, location_confidence, location_note,
  CASE WHEN is_probable THEN 'probable' ELSE evidence_tier END AS evidence_tier,
  greatest(0, least(100, pts_evidence_final + pts_sources + pts_scale + pts_location
                         + pen_merged + pen_facility_type + pen_negated + pen_numbers)) AS trust_score,
  pts_evidence_final AS pts_evidence, pts_sources, pts_scale, pts_location, pen_merged, pen_facility_type, pen_negated, pen_numbers,
  procedures_cited, capabilities_cited, equipment_cited, description_cited, specialties_cited,
  negated_or_referral_mentions,
  evidence_summary,
  CASE WHEN is_probable THEN concat(
         array(concat('Procedure not named in the record; ', name, ' lists ', spec_pretty,
                      CASE WHEN capacity_beds IS NOT NULL THEN concat(' and ', CAST(capacity_beds AS STRING), ' beds')
                           ELSE ' and is a teaching / district hospital' END,
                      '. Call to confirm.')),
         filter(caveats, c -> NOT c LIKE 'Only a related specialty%'))
       ELSE caveats END AS caveats,
  number_doctors, capacity_beds, year_established, n_source_domains, source_urls,
  official_phone, official_website, email, facebook_link, city_raw,
  claims_cited, n_direct_mentions, n_list_mentions, scope_family, quality_flags,
  -- appended in Phase 2
  CASE WHEN pts_checklist IS NOT NULL THEN 'checklist' ELSE 'keyword_rules' END AS evidence_method,
  pts_evidence_rules, checks_found, checks_total, evidence_checks
FROM pts;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Quality score (0–100), every component stored
-- MAGIC
-- MAGIC | component | max | rule |
-- MAGIC |---|---|---|
-- MAGIC | `q_evidence` | 50 | evidence points for this service (checklist or keyword rules, ≤60) scaled to 50 |
-- MAGIC | `q_facility_type` | 10 | hospital 10 · clinic 3 · doctor 2 · other/unknown 0 |
-- MAGIC | `q_beds` | 10 | 500+ beds 10 · 200+ 8 · 100+ 6 · 50+ 4 · 20+ 2 · 1–19 1 · not reported 0 (teaching hospital with no bed count 8) |
-- MAGIC | `q_support` | 10 | supporting services relevant to *this* service that the facility has with strong/moderate evidence (`ref_service_support`, e.g. ICU 4 + blood bank 4 + NICU 2 for C-section) |
-- MAGIC | `q_sources` | 8 | 1.6 per independent source website, up to 5 |
-- MAGIC | `q_location` | 6 | location confidence high 6 · medium 3 · low/none 0 |
-- MAGIC | `q_coherence` | 6 | `record_coherence_score` (silver, 0–100, named deductions) × 6 / 100 |
-- MAGIC | `q_penalties` | | the trust-score penalties (possible merged record, clinic for a hospital service, negative mentions, implausible numbers) |
-- MAGIC
-- MAGIC Readiness = facility type + beds + support (≤30); reliability = sources + location + coherence (≤20).

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.ref_service_support
COMMENT 'Supporting services that make a facility more ready to deliver a service (readiness part of Quality). Points per service sum to 10.'
AS SELECT * FROM VALUES
  ('emergency_csection', 'icu', 'ICU', 4), ('emergency_csection', 'blood_bank', 'blood bank', 4), ('emergency_csection', 'nicu', 'NICU', 2),
  ('high_risk_delivery', 'nicu', 'NICU', 4), ('high_risk_delivery', 'icu', 'ICU', 3), ('high_risk_delivery', 'blood_bank', 'blood bank', 3),
  ('nicu', 'emergency_csection', 'C-section', 3), ('nicu', 'icu', 'ICU', 3), ('nicu', 'blood_bank', 'blood bank', 2), ('nicu', 'emergency_24x7', '24×7 emergency', 2),
  ('trauma', 'emergency_24x7', '24×7 emergency', 3), ('trauma', 'ct_scan', 'CT', 3), ('trauma', 'icu', 'ICU', 2), ('trauma', 'blood_bank', 'blood bank', 2),
  ('dialysis', 'icu', 'ICU', 4), ('dialysis', 'emergency_24x7', '24×7 emergency', 3), ('dialysis', 'blood_bank', 'blood bank', 3),
  ('cardiac_surgery', 'cath_lab', 'cath lab', 4), ('cardiac_surgery', 'icu', 'ICU', 3), ('cardiac_surgery', 'blood_bank', 'blood bank', 3),
  ('cath_lab', 'icu', 'ICU', 4), ('cath_lab', 'emergency_24x7', '24×7 emergency', 3), ('cath_lab', 'cardiac_surgery', 'cardiac surgery', 3),
  ('mri', 'ct_scan', 'CT', 4), ('mri', 'emergency_24x7', '24×7 emergency', 3), ('mri', 'icu', 'ICU', 3),
  ('ct_scan', 'emergency_24x7', '24×7 emergency', 4), ('ct_scan', 'mri', 'MRI', 3), ('ct_scan', 'icu', 'ICU', 3),
  ('neurosurgery', 'icu', 'ICU', 4), ('neurosurgery', 'ct_scan', 'CT', 3), ('neurosurgery', 'emergency_24x7', '24×7 emergency', 3),
  ('burn_care', 'icu', 'ICU', 4), ('burn_care', 'blood_bank', 'blood bank', 3), ('burn_care', 'emergency_24x7', '24×7 emergency', 3),
  ('oncology', 'ct_scan', 'CT', 4), ('oncology', 'blood_bank', 'blood bank', 3), ('oncology', 'icu', 'ICU', 3),
  ('icu', 'emergency_24x7', '24×7 emergency', 4), ('icu', 'blood_bank', 'blood bank', 3), ('icu', 'ct_scan', 'CT', 3),
  ('emergency_24x7', 'icu', 'ICU', 4), ('emergency_24x7', 'ct_scan', 'CT', 3), ('emergency_24x7', 'blood_bank', 'blood bank', 3),
  ('blood_bank', 'emergency_24x7', '24×7 emergency', 4), ('blood_bank', 'icu', 'ICU', 3), ('blood_bank', 'emergency_csection', 'C-section', 3),
  ('orthopedic_surgery', 'blood_bank', 'blood bank', 4), ('orthopedic_surgery', 'icu', 'ICU', 3), ('orthopedic_surgery', 'ct_scan', 'CT', 3),
  ('cataract', 'emergency_24x7', '24×7 emergency', 0)
AS t(service_key, support_service, support_label, points);

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.gold_facility_services
COMMENT 'Gold: one row per (facility, service) with evidence. Matched phrases are verbatim from the facility record for citation, each labelled with a claim type; trust_score and quality_score components are stored separately for transparency. Tiers: strong > moderate > probable > weak.'
AS
WITH confirmed AS (  -- services each facility has with strong/moderate evidence
  SELECT facility_id, collect_set(service_key) AS confirmed_services
  FROM workspace.datathon.gold_facility_services
  WHERE evidence_tier IN ('strong', 'moderate')
  GROUP BY facility_id
),
sup AS (
  SELECT g.facility_id, g.service_key,
         sum(CASE WHEN array_contains(c.confirmed_services, r.support_service) THEN r.points ELSE 0 END) AS q_support,
         array_compact(collect_list(CASE WHEN array_contains(c.confirmed_services, r.support_service) AND r.points > 0
                                         THEN r.support_label END)) AS support_found,
         array_compact(collect_list(CASE WHEN r.points > 0 THEN r.support_label END)) AS support_considered
  FROM workspace.datathon.gold_facility_services g
  JOIN workspace.datathon.ref_service_support r USING (service_key)
  LEFT JOIN confirmed c USING (facility_id)
  GROUP BY g.facility_id, g.service_key
),
q AS (
  SELECT g.*,
    CAST(round(pts_evidence * 50.0 / 60) AS INT) AS q_evidence,
    CASE facility_type WHEN 'hospital' THEN 10 WHEN 'clinic' THEN 3 WHEN 'doctor' THEN 2 ELSE 0 END AS q_facility_type,
    CASE WHEN capacity_beds >= 500 THEN 10 WHEN capacity_beds >= 200 THEN 8 WHEN capacity_beds >= 100 THEN 6
         WHEN capacity_beds >= 50 THEN 4 WHEN capacity_beds >= 20 THEN 2 WHEN capacity_beds >= 1 THEN 1
         WHEN lower(name) RLIKE 'medical college|institute of medical sciences|\\baiims\\b|all india institute|medical university' THEN 8
         ELSE 0 END AS q_beds,
    CAST(coalesce(s.q_support, 0) AS INT) AS q_support,
    coalesce(s.support_found, array()) AS support_found,
    coalesce(s.support_considered, array()) AS support_considered,
    CAST(round(1.6 * least(coalesce(n_source_domains, 0), 5)) AS INT) AS q_sources,
    CASE location_confidence WHEN 'high' THEN 6 WHEN 'medium' THEN 3 ELSE 0 END AS q_location,
    CAST(round(coalesce(sf.record_coherence_score, 100) * 6.0 / 100) AS INT) AS q_coherence,
    pen_merged + pen_facility_type + pen_negated + pen_numbers AS q_penalties,
    -- identity / coherence context from silver (Phase 4)
    sf.record_coherence_score, sf.coh_coords_pin, sf.coh_city, sf.coh_state, sf.coh_located_in, sf.coh_other_facility,
    sf.coh_duplicate, coalesce(sf.identity_conflict, false) AS identity_conflict, sf.identity_conflict_reason,
    sf.possible_duplicate_names, sf.other_facilities_named
  FROM workspace.datathon.gold_facility_services g
  LEFT JOIN sup s USING (facility_id, service_key)
  LEFT JOIN (SELECT facility_id, record_coherence_score, coh_coords_pin, coh_city, coh_state, coh_located_in,
                    coh_other_facility, coh_duplicate, identity_conflict, identity_conflict_reason,
                    possible_duplicate_names, other_facilities_named
             FROM workspace.datathon.silver_facilities) sf USING (facility_id)
)
SELECT q.* EXCEPT (caveats),
  concat(caveats, array_compact(array(
    CASE WHEN size(possible_duplicate_names) > 0 THEN concat('A near-duplicate record is nearby (', array_join(possible_duplicate_names, ', '),
                                                             '); details may be split between the two records.') END,
    CASE WHEN size(other_facilities_named) > 0 THEN concat('The description names another facility: "', get(other_facilities_named, 0), '".') END,
    CASE WHEN identity_conflict THEN concat('Identity not fully settled (', identity_conflict_reason, '), so confidence is capped at Medium.') END
  ))) AS caveats,
  q_facility_type + q_beds + q_support AS q_readiness,
  q_sources + q_location + q_coherence AS q_reliability,
  greatest(0, least(100, q_evidence + q_facility_type + q_beds + q_support + q_sources + q_location + q_coherence + q_penalties)) AS quality_score
FROM q;

-- COMMAND ----------

-- Health check: evidence depth per service
SELECT service_key,
       count(*) AS facilities_with_any_evidence,
       count_if(evidence_tier = 'strong')   AS strong,
       count_if(evidence_tier = 'moderate') AS moderate,
       count_if(evidence_tier = 'probable') AS probable,
       count_if(evidence_tier = 'weak')     AS weak,
       round(avg(trust_score)) AS avg_trust,
       round(avg(quality_score)) AS avg_quality
FROM workspace.datathon.gold_facility_services
GROUP BY service_key ORDER BY facilities_with_any_evidence DESC;
