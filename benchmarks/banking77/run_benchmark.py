import csv
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import scipy
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline
from sklearn.pipeline import FeatureUnion
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
DATA = ROOT / ".local" / "data"
PROTOCOL = ROOT / "protocol.json"
EXPECTED_REV = "57ec275d8078af65b7731c2a98be812d844a6d6b"

def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def canon_hash(obj):
    return hashlib.sha256(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

def load_csv_once(path):
    # Explicitly one read of each CSV into memory.
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def make_model(name):
    word = TfidfVectorizer(analyzer="word", ngram_range=(1, 2))
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
    if name == "word":
        vec = word
    elif name == "char":
        vec = char
    else:
        vec = FeatureUnion([("word", word), ("char", char)])
    return Pipeline([("tfidf", vec), ("svc", LinearSVC(C=1, dual="auto", random_state=42))])

def score_margin(model, texts):
    scores = model.decision_function(texts)
    top = np.partition(scores, -2, axis=1)[:, -2:]
    return top.max(axis=1) - top.min(axis=1)

def choose_threshold(margins, y_true, y_pred):
    candidates = np.unique(margins)
    valid = []
    for t in candidates:
        accepted = margins >= t
        n = int(accepted.sum())
        if n < 100:
            continue
        errors = int(np.count_nonzero(y_true[accepted] != y_pred[accepted]))
        rate = errors / n
        if rate <= 0.05:
            valid.append((n, float(t), errors, rate))
    if not valid:
        return {"threshold": None, "accepted": 0, "errors": None, "error_rate": None, "coverage": 0.0}
    # Max coverage, and for equal coverage choose larger threshold.
    n, t, errors, rate = max(valid, key=lambda x: (x[0], x[1]))
    return {"threshold": t, "accepted": n, "errors": errors, "error_rate": rate, "coverage": n / len(margins)}

def metrics(y, pred, margins, threshold):
    if threshold is None:
        accepted = np.zeros(len(y), dtype=bool)
    else:
        accepted = margins >= threshold
    n = int(accepted.sum())
    errors = int(np.count_nonzero(y[accepted] != pred[accepted])) if n else 0
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "coverage": n / len(y),
        "accepted": n,
        "accepted_error": (errors / n) if n else None,
        "accepted_correct_fraction_of_all": ((n - errors) / len(y)),
    }, accepted

def typo(text):
    chars = list(text)
    # First ASCII-letter token of length >= 5. Exchange its two middle adjacent positions.
    import re
    for m in re.finditer(r"[A-Za-z]{5,}", text):
        start, end = m.span()
        mid_left = (end - start - 1) // 2
        i = start + mid_left
        chars[i], chars[i + 1] = chars[i + 1], chars[i]
        return "".join(chars)
    return text

def latency(model, texts, repeats=200):
    # One warmup, then individual transform plus classifier calls on first 200 rows.
    _ = model.predict([texts[0]])
    ms = []
    for text in texts[:repeats]:
        start = time.perf_counter()
        x = model.named_steps["tfidf"].transform([text])
        _ = model.named_steps["svc"].predict(x)
        ms.append((time.perf_counter() - start) * 1000)
    return {"n": len(ms), "p50_ms": float(np.percentile(ms, 50)), "p95_ms": float(np.percentile(ms, 95))}

protocol_hash = sha256_file(PROTOCOL)
protocol = json.loads(PROTOCOL.read_text(encoding="utf-8-sig"))
manifest_path = DATA / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
assert manifest["revision"] == EXPECTED_REV
assert manifest["repository"].endswith("task-specific-datasets")
train_path = DATA / "train.csv"
train_hash = sha256_file(train_path)
assert train_hash == manifest["files"]["train.csv"]["sha256"], (train_hash, manifest["files"]["train.csv"]["sha256"])
train_df = load_csv_once(train_path)
assert train_df and set(train_df[0]) == {"text", "category"}
X = np.array([row["text"] for row in train_df], dtype=object)
y = np.array([row["category"] for row in train_df], dtype=object)
indices = np.arange(len(y))
train_idx, dev_idx = train_test_split(indices, test_size=0.2, random_state=42, stratify=y)
split_hash = canon_hash({"train_indices": train_idx.tolist(), "validation_indices": dev_idx.tolist()})

models = {}
training_seconds = {}
dev_results = {}
thresholds = {}
with threadpool_limits(limits=1):
    for name in ("word", "char", "word_char"):
        model = make_model(name)
        started = time.perf_counter()
        model.fit(X[train_idx], y[train_idx])
        training_seconds[name] = time.perf_counter() - started
        dev_pred = model.predict(X[dev_idx])
        dev_margin = score_margin(model, X[dev_idx])
        threshold_info = choose_threshold(dev_margin, y[dev_idx], dev_pred)
        thresholds[name] = threshold_info
        summary, accepted = metrics(y[dev_idx], dev_pred, dev_margin, threshold_info["threshold"])
        dev_results[name] = {"metrics": summary, "threshold_selection": threshold_info}
        models[name] = model
        print(f"TRAINED {name}: train_s={training_seconds[name]:.3f} dev_accuracy={summary['accuracy']:.6f} threshold={threshold_info['threshold']} accepted={threshold_info['accepted']} dev_accepted_error={threshold_info['error_rate']}", flush=True)

# Freeze all model thresholds before the sole official test CSV read.
test_path = DATA / "test.csv"
test_hash = sha256_file(test_path)
assert test_hash == manifest["files"]["test.csv"]["sha256"], (test_hash, manifest["files"]["test.csv"]["sha256"])
test_df = load_csv_once(test_path)
assert test_df and set(test_df[0]) == {"text", "category"}
Xt = np.array([row["text"] for row in test_df], dtype=object)
yt = np.array([row["category"] for row in test_df], dtype=object)
Xtypo = np.array([typo(t) for t in Xt], dtype=object)

results = {"clean": {}, "synthetic_typo": {}}
prediction_rows = []
latency_results = {}
batch_results = {}
clean_preds = {}
with threadpool_limits(limits=1):
    for name, model in models.items():
        for scenario, texts in (("clean", Xt), ("synthetic_typo", Xtypo)):
            pred = model.predict(texts)
            margins = score_margin(model, texts)
            summary, accepted = metrics(yt, pred, margins, thresholds[name]["threshold"])
            results[scenario][name] = summary
            if scenario == "clean":
                clean_preds[name] = pred
                latency_results[name] = latency(model, Xt, 200)
                start = time.perf_counter()
                batch_matrix = model.named_steps["tfidf"].transform(Xt)
                _ = model.named_steps["svc"].predict(batch_matrix)
                batch_seconds = time.perf_counter() - start
                batch_results[name] = {"n": len(Xt), "batch_vectorize_plus_classify_seconds": float(batch_seconds), "samples_per_second": float(len(Xt) / batch_seconds)}
            for i, (gold, predicted, margin, ok) in enumerate(zip(yt, pred, margins, accepted)):
                prediction_rows.append({"scenario": scenario, "model": name, "index": i, "gold_label": gold,
                                        "predicted_label": predicted, "margin": float(margin), "accept": bool(ok)})

rng = np.random.default_rng(42)
correct_wc = (clean_preds["word_char"] == yt).astype(np.int8)
correct_word = (clean_preds["word"] == yt).astype(np.int8)
diffs = correct_wc - correct_word
boot = np.empty(2000, dtype=float)
for b in range(2000):
    sample = rng.integers(0, len(yt), size=len(yt))
    boot[b] = diffs[sample].mean()
point_diff = float(diffs.mean())

report = {
    "study": protocol["study"],
    "interpretation": "Independent prototype benchmark; it does not represent performance improvements to an existing ResolveAI system.",
    "protocol_sha256": protocol_hash,
    "dataset": {"repository": manifest["repository"], "revision": manifest["revision"], "license": manifest["license"],
                "files": {"train.csv": {"sha256": train_hash, "bytes": train_path.stat().st_size},
                          "test.csv": {"sha256": test_hash, "bytes": test_path.stat().st_size}},
                "train_rows": len(train_df), "test_rows": len(test_df), "classes_in_train": len(set(y)),
                "classes_in_test": len(set(yt)), "normalized_exact_text_overlap_count": len({" ".join(x.lower().split()) for x in X} & {" ".join(x.lower().split()) for x in Xt})},
    "split": {"method": "stratified 80/20", "random_state": 42, "train_rows": len(train_idx), "validation_rows": len(dev_idx), "indices_sha256": split_hash},
    "environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__, "scipy": scipy.__version__, "scikit_learn": sklearn.__version__, "threadpool_limit": 1},
    "models": {name: {"specification": protocol["models"][name], "fit_rows": len(train_idx), "training_seconds": float(training_seconds[name]),
                      "validation": dev_results[name], "frozen_threshold": thresholds[name]["threshold"],
                      "clean_test": results["clean"][name], "synthetic_typo_test": results["synthetic_typo"][name],
                      "clean_test_latency_ms": latency_results[name], "clean_test_batch_timing": batch_results[name]} for name in models},
    "paired_bootstrap": {"comparison": "word_char accuracy minus word accuracy", "point_estimate": point_diff,
                         "ci_95_percentile": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                         "resamples": 2000, "random_state": 42},
    "limitations": protocol["limitations"],
    "audit_note": "The test set was evaluated in multiple executions: an initial run, a fixed-seed/dependency correction, an export-failure retry, and report-file recovery. Hyperparameters and the split were not chosen from test performance. The last complete fixed-protocol execution is published, not the best of the runs. Timing is from that execution. Initial artifacts are archived privately."
}
(ROOT / "results").mkdir(exist_ok=True)
report_temp = ROOT / "results" / "report.json.tmp"
report_temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

prediction_temp = ROOT / "results" / "predictions.csv.tmp"
with prediction_temp.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["scenario", "model", "index", "gold_label", "predicted_label", "margin", "accept"])
    writer.writeheader()
    writer.writerows(prediction_rows)
prediction_temp.replace(ROOT / "results" / "predictions.csv")
report_temp.replace(ROOT / "results" / "report.json")
print(json.dumps({"protocol_sha256": protocol_hash, "split_sha256": split_hash, "train_rows": len(train_idx), "dev_rows": len(dev_idx), "test_rows": len(yt),
                  "thresholds": thresholds, "clean": results["clean"], "synthetic_typo": results["synthetic_typo"], "bootstrap": report["paired_bootstrap"], "latency": latency_results}, indent=2))
