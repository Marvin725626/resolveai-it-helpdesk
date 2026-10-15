"""Reproducible, offline-only fixture evaluation in a disposable database."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import statistics
import sys
import tempfile
from uuid import uuid4

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--strict",action="store_true");parser.add_argument("--output",default="docs/evaluation.offline.json");args=parser.parse_args()
    # This disposable database has its own throwaway account; never reuse a real demo password.
    demo_password = "Eval-" + secrets.token_hex(12) + "aA1!"
    root=Path(__file__).resolve().parents[1]
    cases=json.loads((root/"backend/data/eval_cases.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="resolveai-eval-") as directory:
        os.environ.update({"DATABASE_URL":"sqlite+aiosqlite:///"+(Path(directory)/"eval.db").as_posix(),
            "DEFAULT_LLM_PROVIDER":"mock","IT_EMBEDDING_PROVIDER":"local","IT_EMBEDDING_DIMENSION":"256",
            "APP_ENV":"development","IT_DEMO_ENABLED":"true","IT_DEMO_PASSWORD":demo_password,"AUTH_SECRET":uuid4().hex+uuid4().hex})
        os.environ.pop("OPENAI_API_KEY",None)
        sys.path.insert(0,str(root/"backend"))
        from fastapi.testclient import TestClient
        from app.main import app
        rows=[]
        with TestClient(app) as client:
            login=client.post("/api/v1/auth/login",json={"email":"demo@resolveai.example.com","password":demo_password});login.raise_for_status()
            headers={"Authorization":"Bearer "+login.json()["access_token"]}
            for case in cases:
                response=client.post("/api/v1/helpdesk/runs",headers=headers,json={"request_id":str(uuid4()),"question":case["question"]});response.raise_for_status();run=response.json()
                sources=[item["code"] for item in run["evidence"]];source=case["source"]
                rank=sources.index(source)+1 if source and source in sources else None
                checks={"category":run["category"]==case["category"],"escalation":run["escalate"]==case["escalate"],"support_gate":run["supported"]==case["supported"],
                    "citation_format":source is None or f"[{source}]" in run["answer"],"retrieval":source is None or rank is not None,
                    "bounded_retry":run["attempts"]<=2,"redaction":"sample-test-value" not in json.dumps(run)}
                rows.append({"id":case["id"],"expected_source":source,"actual_sources":sources,"rank":rank,"reciprocal_rank":1/rank if rank else 0,
                    "category":run["category"],"escalate":run["escalate"],"supported":run["supported"],"latency_ms":run["latency_ms"],"checks":checks,"passed":all(checks.values())})
        relevant=[row for row in rows if row["expected_source"]]
        report={"software_version":app.version,"generated_at":datetime.now(timezone.utc).isoformat(),"scope":"16 manually labelled offline development fixtures; isolated SQLite database, rule routing, hash embeddings and simulated tools",
            "real_model_calls":False,"production_business_impact":"not measured","semantic_faithfulness":"not measured; citation checks only verify format",
            "case_count":len(rows),"passed_cases":sum(row["passed"] for row in rows),"recall_at_4":statistics.mean(int(row["rank"] is not None) for row in relevant),
            "mrr":statistics.mean(row["reciprocal_rank"] for row in relevant),"escalation_accuracy":statistics.mean(row["checks"]["escalation"] for row in rows),
            "category_accuracy":statistics.mean(row["checks"]["category"] for row in rows),"latency_ms_mean":round(statistics.mean(row["latency_ms"] for row in rows),2),"cases":rows}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({key:value for key,value in report.items() if key!="cases"},ensure_ascii=False,indent=2))
    if args.strict and report["passed_cases"]!=len(cases):raise SystemExit(1)

if __name__=="__main__":main()
