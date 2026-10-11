"""Operational metrics from persisted runs, with explicit scope and denominators."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import ceil

DISPLAY_ZONE = timezone(timedelta(hours=8))


def summarize_runs(rows, days, now):
    today = now.astimezone(DISPLAY_ZONE).date()
    dates = [(today - timedelta(days=offset)).isoformat() for offset in reversed(range(days))]
    daily = {date: {"date": date, "runs": 0, "escalated": 0} for date in dates}
    categories = Counter()
    statuses = Counter()
    latencies = []
    completed = escalated = supported = 0
    feedback_helpful = feedback_unhelpful = 0
    for row in rows:
        result = row.result or {}
        status = result.get("status", "unknown")
        statuses[status] += 1
        stamp = row.created_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        day = daily.get(stamp.astimezone(DISPLAY_ZONE).date().isoformat())
        if day is not None:
            day["runs"] += 1
        if status != "completed":
            continue
        completed += 1
        feedback = result.get("feedback")
        if isinstance(feedback, dict):
            if feedback.get("helpful") is True:
                feedback_helpful += 1
            elif feedback.get("helpful") is False:
                feedback_unhelpful += 1
        categories[result.get("category", "unknown")] += 1
        if result.get("escalate"):
            escalated += 1
            if day is not None:
                day["escalated"] += 1
        supported += bool(result.get("supported"))
        latency = result.get("latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool) and latency >= 0:
            latencies.append(latency)
    latencies.sort()
    return {
        "feedback": {"helpful": feedback_helpful, "unhelpful": feedback_unhelpful,
                     "responses": feedback_helpful + feedback_unhelpful},
        "days": days, "timezone": "Asia/Hong_Kong", "total_runs": len(rows),
        "completed_runs": completed, "escalated_runs": escalated,
        "escalation_rate": round(escalated / completed, 4) if completed else None,
        "supported_rate": round(supported / completed, 4) if completed else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "p95_latency_ms": round(latencies[ceil(len(latencies) * .95) - 1], 2) if latencies else None,
        "latency_samples": len(latencies), "statuses": dict(statuses),
        "categories": [{"category": key, "count": count} for key, count in categories.most_common()],
        "daily": list(daily.values()),
    }
