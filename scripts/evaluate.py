"""Small labelled smoke evaluation, not a production quality benchmark."""
import argparse
import json
import statistics
import urllib.request
from pathlib import Path
from uuid import uuid4

CASES = [
    ("VPN 连不上提示认证超时", "VPN-001", True),
    ("账号锁定无法登录怎么办", "IAM-001", False),
    ("如何安装公司批准的软件", "APP-001", False),
    ("GitLab 返回 503 错误", "SVC-001", False),
    ("Outlook 邮箱无法同步", "MAIL-001", False),
    ("如何购买潜水艇发动机？", None, True),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8104")
    parser.add_argument("--output", default="docs/evaluation.local.json")
    args = parser.parse_args()
    def post(path, payload, token=""):
        req = urllib.request.Request(args.base_url + "/api/v1" + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
        with urllib.request.urlopen(req, timeout=110) as response:
            return json.load(response)
    token = post("/auth/login", {"email": "demo@resolveai.example.com", "password": "ResolveAI123!"})["access_token"]
    results = []
    for question, expected, escalation in CASES:
        run = post("/helpdesk/runs", {"question": question, "request_id": str(uuid4())}, token)
        sources = [e["code"] for e in run["evidence"]]
        rank = sources.index(expected) + 1 if expected in sources else None
        results.append({"question": question, "expected_source": expected, "sources": sources,
            "recall_at_4": int(rank is not None) if expected else None, "reciprocal_rank": 1 / rank if rank else 0,
            "citation_present": f"[{expected}]" in run["answer"] if expected else None,
            "expected_escalation": escalation, "actual_escalation": run["escalate"],
            "latency_ms": run["latency_ms"], "run_id": run["run_id"]})
    relevant = [r for r in results if r["expected_source"]]
    report = {"scope": "6 manually labelled local demo cases; not a production benchmark",
        "faithfulness": "not measured; citation presence is only a format check",
        "recall_at_4": statistics.mean(r["recall_at_4"] for r in relevant),
        "mrr": statistics.mean(r["reciprocal_rank"] for r in relevant),
        "escalation_accuracy": statistics.mean(r["actual_escalation"] == r["expected_escalation"] for r in results),
        "latency_ms_mean": round(statistics.mean(r["latency_ms"] for r in results), 2), "cases": results}
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
