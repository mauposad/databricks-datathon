-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 06 · Service groups: broad, user-friendly care terms
-- MAGIC
-- MAGIC People ask for "childbirth" or "heart care", not "Emergency C-section" or "cath lab". This notebook builds the
-- MAGIC layer between the words people use and the specific services in `ref_services` (notebook 03):
-- MAGIC
-- MAGIC * `ref_service_groups`: one row per broad group, with its member services. The first member listed is the
-- MAGIC   default for a search that names only the group. `default_service` is NULL where no member is a fair stand-in
-- MAGIC   for the others (MRI vs CT): the app then asks `refine_question` instead of guessing.
-- MAGIC * `ref_service_terms`: everyday words, symptoms and common Hindi / Hinglish words, each mapped to a group and,
-- MAGIC   where the word points at one member, to that service ("chest pain" -> Heart care / cath lab).
-- MAGIC
-- MAGIC Search itself is unchanged: the app resolves a group or a term to **one** service key and calls `find_care`
-- MAGIC once, as before. Both tables are small, read once by the app, cached, and shipped in its reference snapshot.
-- MAGIC
-- MAGIC Requires notebook 03 (`ref_services`). The health check at the end must return no rows.

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.datathon.ref_service_groups
COMMENT 'Broad care groups shown to users. services[0] is the default unless default_service is NULL, in which case the app asks refine_question.'
AS SELECT * FROM VALUES
  ('emergency', 'Emergency & accidents', 'Accidents, injuries, burns and anything that cannot wait', 1,
   array('emergency_24x7', 'trauma', 'burn_care'), 'emergency_24x7', 'What kind of emergency?'),
  ('maternity', 'Pregnancy & childbirth', 'Delivery, high-risk pregnancy and C-section', 2,
   array('high_risk_delivery', 'emergency_csection'), 'high_risk_delivery', 'Do you need a C-section specifically?'),
  ('child', 'Newborn & child care', 'Child specialists, vaccination and newborn intensive care', 3,
   array('paediatrics', 'nicu'), 'paediatrics', 'Does the baby need intensive care (NICU)?'),
  ('heart', 'Heart care', 'Heart attack, angioplasty and heart surgery', 4,
   array('cath_lab', 'cardiac_surgery'), 'cath_lab', 'Angioplasty or heart surgery?'),
  ('cancer', 'Cancer care', 'Chemotherapy and radiotherapy', 5,
   array('oncology'), 'oncology', NULL),
  ('kidney', 'Kidney care & dialysis', 'Dialysis for kidney failure', 6,
   array('dialysis'), 'dialysis', NULL),
  ('critical', 'Intensive care (ICU)', 'Critical care and ventilator support', 7,
   array('icu'), 'icu', NULL),
  ('imaging', 'Scans & imaging', 'MRI and CT scans', 8,
   array('mri', 'ct_scan'), NULL, 'Which scan do you need: MRI or CT?'),
  ('bones', 'Bones & joints', 'Fractures, joint replacement and orthopaedic care', 9,
   array('orthopedic_surgery', 'physiotherapy'), 'orthopedic_surgery', 'Surgery or physiotherapy?'),
  ('rehab', 'Physiotherapy & rehab', 'Physiotherapy and recovery after injury, stroke or surgery', 10,
   array('physiotherapy'), 'physiotherapy', NULL),
  ('brain', 'Brain & spine', 'Brain and spine surgery, head injuries', 11,
   array('neurosurgery'), 'neurosurgery', NULL),
  ('eyes', 'Eye care', 'Cataract and eye surgery', 12,
   array('cataract'), 'cataract', NULL),
  ('mental', 'Mental health', 'Psychiatry, counselling and de-addiction', 13,
   array('mental_health'), 'mental_health', NULL),
  ('general', 'General doctor visit', 'Fever, diabetes, blood pressure and everyday illness', 14,
   array('general_medicine'), 'general_medicine', NULL),
  ('dental', 'Dental care', 'Teeth, gums and braces', 15,
   array('dental'), 'dental', NULL),
  ('ent', 'Ear, nose & throat', 'Hearing, sinus and throat problems', 16,
   array('ent'), 'ent', NULL),
  ('skin', 'Skin & hair', 'Rashes, acne, allergies and hair loss', 17,
   array('dermatology'), 'dermatology', NULL),
  ('blood', 'Blood bank', 'Blood transfusion and blood donors', 18,
   array('blood_bank'), 'blood_bank', NULL)
AS t(group_key, group_label, description, sort_order, services, default_service, refine_question);

-- COMMAND ----------

-- Everyday words -> group (and service, when the word points at one member). Matched as whole words, case-insensitive;
-- the longest matching term wins, so "heart surgery" beats "heart". Group labels, service labels and ref_services
-- aliases are matched too, so they are not repeated here. Keep terms specific: "pain" alone would match everything.
CREATE OR REPLACE TABLE workspace.datathon.ref_service_terms
COMMENT 'Everyday words, symptoms and common Hindi/Hinglish words mapped to a service group and optionally one service. Longest match wins.'
AS SELECT * FROM VALUES
  -- emergency & accidents
  ('emergency', 'emergency', NULL), ('urgent', 'emergency', NULL), ('casualty', 'emergency', 'emergency_24x7'),
  ('emergency room', 'emergency', 'emergency_24x7'), ('unconscious', 'emergency', 'emergency_24x7'),
  ('fainted', 'emergency', 'emergency_24x7'), ('snake bite', 'emergency', 'emergency_24x7'), ('poisoning', 'emergency', 'emergency_24x7'),
  ('heavy bleeding', 'emergency', 'emergency_24x7'), ('aapatkalin', 'emergency', 'emergency_24x7'),
  ('accident', 'emergency', 'trauma'), ('road accident', 'emergency', 'trauma'), ('injury', 'emergency', 'trauma'),
  ('injured', 'emergency', 'trauma'), ('hit by a car', 'emergency', 'trauma'), ('fell from', 'emergency', 'trauma'),
  ('durghatna', 'emergency', 'trauma'), ('chot', 'emergency', 'trauma'),
  ('burn', 'emergency', 'burn_care'), ('burns', 'emergency', 'burn_care'), ('burned', 'emergency', 'burn_care'),
  ('burnt', 'emergency', 'burn_care'), ('scald', 'emergency', 'burn_care'), ('jal gaya', 'emergency', 'burn_care'),
  -- pregnancy & childbirth
  ('pregnancy', 'maternity', NULL), ('pregnant', 'maternity', NULL), ('childbirth', 'maternity', NULL),
  ('child birth', 'maternity', NULL), ('giving birth', 'maternity', NULL), ('labour', 'maternity', NULL),
  ('labor', 'maternity', NULL), ('labour pain', 'maternity', NULL), ('in labour', 'maternity', NULL),
  ('water broke', 'maternity', NULL), ('maternity', 'maternity', NULL), ('maternity care', 'maternity', NULL),
  ('paternity', 'maternity', NULL), ('antenatal', 'maternity', NULL), ('prenatal', 'maternity', NULL),
  ('gynaecologist', 'maternity', NULL), ('gynecologist', 'maternity', NULL), ('obstetrician', 'maternity', NULL),
  ('baby delivery', 'maternity', NULL), ('prasav', 'maternity', NULL), ('garbhavastha', 'maternity', NULL),
  ('caesarean', 'maternity', 'emergency_csection'), ('cesarean', 'maternity', 'emergency_csection'),
  ('c-section', 'maternity', 'emergency_csection'), ('c section', 'maternity', 'emergency_csection'),
  ('operation delivery', 'maternity', 'emergency_csection'), ('obstructed labour', 'maternity', 'emergency_csection'),
  -- newborn & child care
  ('child', 'child', NULL), ('children', 'child', NULL), ('kid', 'child', NULL), ('kids', 'child', NULL),
  ('baby', 'child', NULL), ('infant', 'child', NULL), ('toddler', 'child', NULL), ('child doctor', 'child', 'paediatrics'),
  ('children''s doctor', 'child', 'paediatrics'), ('vaccine', 'child', 'paediatrics'), ('vaccines', 'child', 'paediatrics'),
  ('bachcha', 'child', 'paediatrics'), ('baccha', 'child', 'paediatrics'), ('shishu', 'child', 'paediatrics'),
  ('newborn', 'child', 'nicu'), ('premature', 'child', 'nicu'), ('premature baby', 'child', 'nicu'),
  ('preterm', 'child', 'nicu'), ('low birth weight', 'child', 'nicu'), ('baby not breathing', 'child', 'nicu'),
  ('newborn jaundice', 'child', 'nicu'), ('incubator', 'child', 'nicu'),
  -- heart
  ('heart', 'heart', NULL), ('cardiac', 'heart', NULL), ('cardiologist', 'heart', NULL), ('cardiology', 'heart', NULL),
  ('dil', 'heart', NULL), ('chest pain', 'heart', 'cath_lab'), ('heart attack', 'heart', 'cath_lab'),
  ('blocked artery', 'heart', 'cath_lab'), ('blockage', 'heart', 'cath_lab'), ('seene mein dard', 'heart', 'cath_lab'),
  ('bypass', 'heart', 'cardiac_surgery'), ('valve', 'heart', 'cardiac_surgery'), ('hole in the heart', 'heart', 'cardiac_surgery'),
  -- cancer
  ('cancer', 'cancer', 'oncology'), ('tumour', 'cancer', 'oncology'), ('tumor', 'cancer', 'oncology'),
  ('oncologist', 'cancer', 'oncology'), ('chemo', 'cancer', 'oncology'), ('radiation', 'cancer', 'oncology'),
  ('lump', 'cancer', 'oncology'), ('kark rog', 'cancer', 'oncology'),
  -- kidney
  ('kidney', 'kidney', 'dialysis'), ('kidneys', 'kidney', 'dialysis'), ('kidney failure', 'kidney', 'dialysis'),
  ('renal failure', 'kidney', 'dialysis'), ('nephrologist', 'kidney', 'dialysis'), ('gurda', 'kidney', 'dialysis'),
  -- intensive care
  ('critical', 'critical', 'icu'), ('critically ill', 'critical', 'icu'), ('very sick', 'critical', 'icu'),
  ('on a ventilator', 'critical', 'icu'), ('life support', 'critical', 'icu'), ('breathing problem', 'critical', 'icu'),
  -- scans
  ('scan', 'imaging', NULL), ('scans', 'imaging', NULL), ('imaging', 'imaging', NULL), ('radiology', 'imaging', NULL),
  ('mri', 'imaging', 'mri'), ('ct', 'imaging', 'ct_scan'), ('cat scan', 'imaging', 'ct_scan'),
  -- bones & joints
  ('bone', 'bones', NULL), ('bones', 'bones', NULL), ('joint', 'bones', NULL), ('joints', 'bones', NULL),
  ('orthopaedic', 'bones', NULL), ('orthopedic', 'bones', NULL), ('orthopedics', 'bones', NULL),
  ('orthopaedics', 'bones', NULL), ('orthopaedic care', 'bones', NULL), ('orthopedic care', 'bones', NULL),
  ('haddi', 'bones', NULL), ('fracture', 'bones', 'orthopedic_surgery'), ('broken bone', 'bones', 'orthopedic_surgery'),
  ('broken leg', 'bones', 'orthopedic_surgery'), ('broken arm', 'bones', 'orthopedic_surgery'),
  ('knee replacement', 'bones', 'orthopedic_surgery'), ('hip replacement', 'bones', 'orthopedic_surgery'),
  ('haddi toot', 'bones', 'orthopedic_surgery'),
  -- physiotherapy & rehab
  ('physical therapy', 'rehab', 'physiotherapy'), ('physio', 'rehab', 'physiotherapy'), ('physiotherapist', 'rehab', 'physiotherapy'),
  ('rehab', 'rehab', 'physiotherapy'), ('back pain', 'rehab', 'physiotherapy'), ('neck pain', 'rehab', 'physiotherapy'),
  ('knee pain', 'rehab', 'physiotherapy'), ('joint pain', 'rehab', 'physiotherapy'), ('sports injury', 'rehab', 'physiotherapy'),
  ('paralysis', 'rehab', 'physiotherapy'), ('stroke recovery', 'rehab', 'physiotherapy'), ('frozen shoulder', 'rehab', 'physiotherapy'),
  -- brain & spine
  ('brain', 'brain', 'neurosurgery'), ('spine', 'brain', 'neurosurgery'), ('head injury', 'brain', 'neurosurgery'),
  ('brain tumor', 'brain', 'neurosurgery'), ('slipped disc', 'brain', 'neurosurgery'), ('stroke', 'brain', 'neurosurgery'),
  ('brain haemorrhage', 'brain', 'neurosurgery'), ('brain hemorrhage', 'brain', 'neurosurgery'),
  -- eyes
  ('eye', 'eyes', 'cataract'), ('eyes', 'eyes', 'cataract'), ('vision', 'eyes', 'cataract'), ('blurry vision', 'eyes', 'cataract'),
  ('eye doctor', 'eyes', 'cataract'), ('ophthalmologist', 'eyes', 'cataract'), ('aankh', 'eyes', 'cataract'),
  ('motiyabind', 'eyes', 'cataract'),
  -- mental health
  ('stress', 'mental', 'mental_health'), ('depressed', 'mental', 'mental_health'), ('anxious', 'mental', 'mental_health'),
  ('panic attacks', 'mental', 'mental_health'), ('alcohol', 'mental', 'mental_health'), ('drinking problem', 'mental', 'mental_health'),
  ('drug addiction', 'mental', 'mental_health'), ('psychologist', 'mental', 'mental_health'), ('therapist', 'mental', 'mental_health'),
  ('suicidal', 'mental', 'mental_health'), ('nasha mukti', 'mental', 'mental_health'), ('sleep problem', 'mental', 'mental_health'),
  -- general doctor visit
  ('doctor', 'general', 'general_medicine'), ('physician', 'general', 'general_medicine'), ('checkup', 'general', 'general_medicine'),
  ('check-up', 'general', 'general_medicine'), ('cough', 'general', 'general_medicine'), ('cold', 'general', 'general_medicine'),
  ('sugar', 'general', 'general_medicine'), ('bp', 'general', 'general_medicine'), ('high blood pressure', 'general', 'general_medicine'),
  ('typhoid', 'general', 'general_medicine'), ('malaria', 'general', 'general_medicine'), ('dengue', 'general', 'general_medicine'),
  ('vomiting', 'general', 'general_medicine'), ('diarrhoea', 'general', 'general_medicine'), ('diarrhea', 'general', 'general_medicine'),
  ('bukhar', 'general', 'general_medicine'),
  -- dental
  ('toothache', 'dental', 'dental'), ('tooth pain', 'dental', 'dental'), ('gums', 'dental', 'dental'),
  ('cavity', 'dental', 'dental'), ('daant', 'dental', 'dental'), ('dant', 'dental', 'dental'),
  -- ENT
  ('ear pain', 'ent', 'ent'), ('ear infection', 'ent', 'ent'), ('hearing loss', 'ent', 'ent'), ('deaf', 'ent', 'ent'),
  ('sore throat', 'ent', 'ent'), ('throat', 'ent', 'ent'), ('nose', 'ent', 'ent'), ('sinusitis', 'ent', 'ent'),
  ('kaan', 'ent', 'ent'), ('gala', 'ent', 'ent'),
  -- skin & hair
  ('rash', 'skin', 'dermatology'), ('itching', 'skin', 'dermatology'), ('itchy', 'skin', 'dermatology'),
  ('pimples', 'skin', 'dermatology'), ('hair fall', 'skin', 'dermatology'), ('fungal infection', 'skin', 'dermatology'),
  ('skin allergy', 'skin', 'dermatology'), ('khujli', 'skin', 'dermatology'), ('twacha', 'skin', 'dermatology'),
  -- blood
  ('blood', 'blood', 'blood_bank'), ('blood donor', 'blood', 'blood_bank'), ('transfusion', 'blood', 'blood_bank'),
  ('khoon', 'blood', 'blood_bank')
AS t(term, group_key, service_key);

-- COMMAND ----------

-- Health check: must return no rows. Unknown service keys, a service in no group, a term pointing at a service outside
-- its group, a default that is not a member, or a term listed twice.
SELECT 'unknown service in group' AS problem, g.group_key AS item, m AS detail
FROM workspace.datathon.ref_service_groups g LATERAL VIEW explode(g.services) t AS m
WHERE m NOT IN (SELECT service_key FROM workspace.datathon.ref_services)
UNION ALL
SELECT 'service in no group', s.service_key, s.service_label FROM workspace.datathon.ref_services s
WHERE NOT exists(SELECT 1 FROM workspace.datathon.ref_service_groups g WHERE array_contains(g.services, s.service_key))
UNION ALL
SELECT 'default not a member', group_key, default_service FROM workspace.datathon.ref_service_groups
WHERE default_service IS NOT NULL AND NOT array_contains(services, default_service)
UNION ALL
SELECT 'no default and no refine question', group_key, NULL FROM workspace.datathon.ref_service_groups
WHERE default_service IS NULL AND refine_question IS NULL
UNION ALL
SELECT 'term outside its group', t.term, concat(t.group_key, ' / ', t.service_key)
FROM workspace.datathon.ref_service_terms t LEFT JOIN workspace.datathon.ref_service_groups g USING (group_key)
WHERE g.group_key IS NULL OR (t.service_key IS NOT NULL AND NOT array_contains(g.services, t.service_key))
UNION ALL
SELECT 'duplicate term', term, CAST(count(*) AS STRING) FROM workspace.datathon.ref_service_terms
GROUP BY term HAVING count(*) > 1;
