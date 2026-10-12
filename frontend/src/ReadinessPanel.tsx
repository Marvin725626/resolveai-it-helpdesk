import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
type Checks = {
  database: { connected: boolean; backend: string };
  knowledge: { indexed_chunks: number; embedding_identity_matches: number };
  configuration: {
    mode: string;
    embedding: string;
    embedding_dimension: number;
    model_key_configured: boolean;
  };
  warnings: string[];
  checked_at: string;
};
export default function ReadinessPanel({
  api,
}: {
  api: <T>(path: string) => Promise<T>;
}) {
  const [data, setData] = useState<Checks>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api<Checks>("/helpdesk/readiness")
      .then((value) => {
        if (active) setData(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [revision]);
  return (
    <section className="panel readiness-panel">
      <div className="section-heading">
        <h2>
          <Activity size={18} />
          运行检查
        </h2>
        <button
          className="text-button"
          onClick={() => setRevision((value) => value + 1)}
        >
          重新检查
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {data && (
        <>
          <dl>
            <div>
              <dt>数据库实际查询</dt>
              <dd>
                {data.database.connected ? "已连接" : "不可用"} ·{" "}
                {data.database.backend}
              </dd>
            </div>
            <div>
              <dt>当前工作区知识片段</dt>
              <dd>{data.knowledge.indexed_chunks}</dd>
            </div>
            <div>
              <dt>与当前 embedding 身份一致</dt>
              <dd>
                {data.knowledge.embedding_identity_matches} /{" "}
                {data.knowledge.indexed_chunks}
              </dd>
            </div>
            <div>
              <dt>模型密钥配置</dt>
              <dd>
                {data.configuration.model_key_configured
                  ? "已配置 · 不显示内容"
                  : "未配置"}
              </dd>
            </div>
            <div>
              <dt>检索向量维度配置</dt>
              <dd>{data.configuration.embedding_dimension}</dd>
            </div>
          </dl>
          {data.warnings.length ? (
            <ul className="readiness-warnings">
              {data.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : (
            <p className="success-message">
              本次数据库与知识配置检查没有发现提示项。
            </p>
          )}
          <p className="panel-footnote">
            检查时间：
            {new Date(data.checked_at).toLocaleString("zh-CN", {
              timeZone: "Asia/Hong_Kong",
            })}
            。未检测外部模型连通性，也不验证向量列迁移或回答正确性。企业工具仍为模拟数据。
          </p>
        </>
      )}
    </section>
  );
}
