import { useEffect, useState } from "react";
import { Activity, ArrowDownToLine, Check } from "lucide-react";
type Case = {
  id: string;
  expected_source: string | null;
  rank: number | null;
  category: string;
  escalate: boolean;
  supported: boolean;
  latency_ms: number;
  checks: Record<string, boolean>;
  passed: boolean;
};
type Report = {
  generated_at: string;
  software_version?: string;
  scope: string;
  case_count: number;
  passed_cases: number;
  recall_at_4: number;
  mrr: number;
  escalation_accuracy: number;
  category_accuracy: number;
  latency_ms_mean: number;
  cases: Case[];
};
const checkLabel: Record<string, string> = {
  category: "分类匹配",
  escalation: "转人工决策",
  support_gate: "证据门控",
  citation_format: "引用格式",
  retrieval: "召回来源",
  bounded_retry: "检索次数有界",
  redaction: "文本脱敏",
};
export default function EvaluationPanel({
  api,
}: {
  api: <T>(path: string) => Promise<T>;
}) {
  const [report, setReport] = useState<Report>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api<{ report: Report }>("/helpdesk/evaluation-report")
      .then((value) => {
        if (active) setReport(value.report);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [revision]);
  function download() {
    if (!report) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "resolveai-offline-evaluation.json";
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="evaluation-view">
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <section className="panel">
        <div className="section-heading">
          <h2>
            <Activity size={18} />
            离线场景评估
          </h2>
          <div className="knowledge-toolbar">
            <button
              className="secondary"
              onClick={() => setRevision((value) => value + 1)}
            >
              重新读取报告
            </button>
            <button className="secondary" disabled={!report} onClick={download}>
              <ArrowDownToLine size={15} />
              下载评估报告
            </button>
          </div>
        </div>
        <p className="evaluation-notice">
          这是仓库中的固定开发样本报告，使用隔离数据库、规则分类、本地 hash
          向量和模拟工具。未使用真实模型；小样本通过率不能代表真实业务准确率，也没有验证语义
          Faithfulness。
        </p>
        {report && (
          <>
            <div className="analytics-kpis">
              <article className="panel">
                <span>场景检查通过</span>
                <strong>
                  {report.passed_cases} / {report.case_count}
                </strong>
                <small>人工标注 fixture</small>
              </article>
              <article className="panel">
                <span>Recall@4</span>
                <strong>{(report.recall_at_4 * 100).toFixed(1)}%</strong>
                <small>有标注来源的样本</small>
              </article>
              <article className="panel">
                <span>MRR</span>
                <strong>{report.mrr.toFixed(3)}</strong>
                <small>来源排序</small>
              </article>
              <article className="panel">
                <span>转人工决策匹配</span>
                <strong>
                  {(report.escalation_accuracy * 100).toFixed(1)}%
                </strong>
                <small>本次 fixture 口径</small>
              </article>
            </div>
            <p className="panel-footnote">
              生成时间：
              {new Date(report.generated_at).toLocaleString("zh-CN", {
                timeZone: "Asia/Hong_Kong",
              })}{" "}
              · 运行版本 {report.software_version || "未记录"} ·
              平均节点流程耗时 {report.latency_ms_mean} ms（离线环境）
            </p>
          </>
        )}
      </section>
      {report && (
        <section className="panel">
          <div className="section-heading">
            <h2>逐场景结果</h2>
            <span className="micro-label">不包含用户运行记录</span>
          </div>
          <div className="evaluation-cases">
            {report.cases.map((item) => (
              <article key={item.id}>
                <div>
                  <span
                    className={
                      item.passed ? "small-pill green" : "small-pill amber"
                    }
                  >
                    {item.passed ? <Check size={13} /> : null}
                    {item.passed ? "通过" : "需检查"}
                  </span>
                  <strong>{item.id}</strong>
                  <small>
                    来源 {item.expected_source || "无适用 SOP"} · 排名{" "}
                    {item.rank ?? "—"} · {item.category} ·{" "}
                    {item.escalate ? "转人工" : "排查建议"} · {item.latency_ms}{" "}
                    ms
                  </small>
                </div>
                <details>
                  <summary>检查项</summary>
                  <ul>
                    {Object.entries(item.checks).map(([key, passed]) => (
                      <li key={key}>
                        <span>{checkLabel[key] || key}</span>
                        <strong>{passed ? "通过" : "失败"}</strong>
                      </li>
                    ))}
                  </ul>
                </details>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
