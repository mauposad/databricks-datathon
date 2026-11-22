"""Load the hand-labelled eval set into Databricks and report precision/recall per service.

    python eval/run_eval.py                 # evaluate workspace.datathon
    python eval/run_eval.py --schema datathon_dev
    python eval/run_eval.py --freeze v1     # save the current tiers as eval/predictions_v1.csv (frozen baseline)

Uses the Databricks CLI (profile `datathon`) and the Serverless Starter Warehouse; writes only
`<schema>.eval_labels` and `<schema>.eval_predictions_frozen`. Needs no Python packages.
"""
import csv, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
WAREHOUSE = os.environ.get("DATABRICKS_WAREHOUSE_ID", "ce4eb527f62e5ff7")
PROFILE = os.environ.get("DATABRICKS_PROFILE", "datathon")


def api(method, path, body=None):
    cmd = ["databricks", "api", method, path, "-p", PROFILE]
    tmp = None
    if body is not None:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(body, tmp)
        tmp.close()
        cmd += ["--json", "@" + tmp.name]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    finally:
        if tmp:
            os.unlink(tmp.name)
    if out.returncode != 0:
        raise RuntimeError(out.stderr or out.stdout)
    return json.loads(out.stdout)


def sql(stmt):
    r = api("post", "/api/2.0/sql/statements", {
        "warehouse_id": WAREHOUSE, "statement": stmt, "wait_timeout": "50s",
        "on_wait_timeout": "CONTINUE", "format": "JSON_ARRAY", "disposition": "INLINE"})
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = api("get", f"/api/2.0/sql/statements/{r['statement_id']}")
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(json.dumps(r["status"])[:2000])
    cols = [c["name"] for c in r.get("manifest", {}).get("schema", {}).get("columns", [])]
    return cols, r.get("result", {}).get("data_array", []) or []


def q(s):
    return "NULL" if s is None or s == "" else "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def load_csv(path, table, cols):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    values = ",\n".join("(" + ", ".join(q(r[c]) for c in cols) + ")" for r in rows)
    sql(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM VALUES {values} AS t({', '.join(cols)})")
    return len(rows)


def cells(path, schema):
    text = open(path, encoding="utf-8").read().replace("workspace.datathon.", f"workspace.{schema}.")
    for cell in text.split("-- COMMAND ----------"):
        body = "\n".join(l for l in cell.splitlines() if not l.startswith("-- MAGIC") and "notebook source" not in l).strip()
        stripped = "\n".join(l for l in body.splitlines() if not l.strip().startswith("--")).strip()
        if stripped:
            yield body.rstrip(";")


def main():
    args = sys.argv[1:]
    schema = args[args.index("--schema") + 1] if "--schema" in args else "datathon"
    ws = f"workspace.{schema}"
    n = load_csv(os.path.join(HERE, "labels.csv"), f"{ws}.eval_labels",
                 ["facility_id", "service_key", "label", "note", "facility_name", "why_sampled"])
    print(f"loaded {n} labels into {ws}.eval_labels", file=sys.stderr)

    if "--freeze" in args:
        version = args[args.index("--freeze") + 1]
        cols, rows = sql(f"""SELECT l.facility_id, l.service_key, coalesce(g.evidence_tier, 'none') AS evidence_tier
                              FROM {ws}.eval_labels l LEFT JOIN {ws}.gold_facility_services g USING (facility_id, service_key)
                              ORDER BY 2, 1""")
        out = os.path.join(HERE, f"predictions_{version}.csv")
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["version"] + cols)
            for r in rows:
                w.writerow([version] + r)
        print(f"froze {len(rows)} predictions to {out}", file=sys.stderr)
        return

    frozen = [os.path.join(HERE, f) for f in sorted(os.listdir(HERE)) if f.startswith("predictions_") and f.endswith(".csv")]
    allrows = []
    for p in frozen:
        allrows += list(csv.DictReader(open(p, encoding="utf-8")))
    values = ",\n".join(f"({q(r['version'])}, {q(r['facility_id'])}, {q(r['service_key'])}, {q(r['evidence_tier'])})" for r in allrows)
    sql(f"CREATE OR REPLACE TABLE {ws}.eval_predictions_frozen AS SELECT * FROM VALUES {values} AS t(version, facility_id, service_key, evidence_tier)")

    for stmt in cells(os.path.join(HERE, "evaluate.sql"), schema):
        cols, rows = sql(stmt)
        if not cols:
            continue
        print("\n| " + " | ".join(cols) + " |")
        print("|" + "---|" * len(cols))
        for r in rows:
            print("| " + " | ".join("" if v is None else str(v) for v in r) + " |")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
