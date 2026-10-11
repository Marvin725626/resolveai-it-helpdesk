# ResolveAI 功能展示

以下图片由浏览器访问本地 FastAPI + React 服务生成。演示账号、模拟服务状态和离线 SOP 回答均为开发数据。

## 运营看板

![运营看板](resolveai-dashboard.png)

从保存的运行数据统计每日诊断量、问题分类、转人工比例、证据门控通过比例与响应耗时。支持 7 / 30 / 90 天切换、刷新与 JSON 下载。图表附有可展开数据表。

诊断数据仅限当前账号。工单分布覆盖当前工作区全部时间，不随着诊断日期筛选改变。失败 / 运行中记录计入请求总量，不计入完成诊断比例的分母。零样本比例和耗时显示为空。

## 有证据的诊断与人工交接

![VPN 诊断、知识引用、节点轨迹和模拟工具](resolveai-diagnosis.png)

VPN 问题从 SOP 检索到模拟服务降级结果，最终创建附完整诊断上下文的人工工单。工作台显示已完成的 LangGraph 节点、耗时、引用原文和工具实际输出。

## 工单筛选与导出

![工单组合筛选](resolveai-tickets.png)

组合关键词、状态、优先级过滤最近 100 张工单。CSV 下载当前筛选结果，包括 ID、问题、状态、优先级、升级原因和 UTC 创建时间；不导出完整上下文。中文 BOM、双引号转义与公式前缀处理经过独立校验。

## 手机布局

<img src="resolveai-mobile.png" alt="390px 手机运营看板" width="390" />

已实测 390px 视口，无页面横向溢出。长时间窗口的每日图表在图表区域内横向滚动。

## 阅读代码

| 功能 | 关键代码 |
| --- | --- |
| 图工作流与人工交接 | `backend/app/helpdesk/workflow.py` |
| 混合检索与证据来源 | `backend/app/helpdesk/retrieval.py` |
| API 鉴权、窗口查询与工单范围 | `backend/app/helpdesk/api.py` |
| 指标分母、日期桶与 P95 | `backend/app/helpdesk/analytics.py` |
| 运营看板 | `frontend/src/AnalyticsPanel.tsx` |
| 工单工作台与筛选 | `frontend/src/ResolveApp.tsx` |
| CSV 格式与公式前缀 | `frontend/src/csv.ts` |

验证结果见 [VALIDATION.md](VALIDATION.md)，复现流程见 [DEMO.md](DEMO.md)。未验证真实 LLM、Docker 或 PostgreSQL 集成，不声称生产部署效果。
