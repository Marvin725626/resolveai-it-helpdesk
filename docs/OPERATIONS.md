# 本地运维与数据备份

## 生命周期

启动 `.\start.ps1`，停止 `.\stop.ps1`。后台进程保持隐藏，日志位于 `.local/logs/`，进程记录包含 PID、端口；停止前校验命令行是否属于本项目。

工作台 http://127.0.0.1:5174，API http://127.0.0.1:8104/docs。本地使用独立 SQLite 库 `backend/resolveai.db`。主工作流、知识版本和处理事件均在同一项目数据范围内。

## SQLite 数据库在线快照

```powershell
.\.venv\Scripts\python.exe scripts\backup_sqlite.py
```

使用 SQLite backup API 从只读连接生成一致快照，再运行 quick_check。默认保存到 `.local/backups/`，输出文件大小与 SHA-256；文件名包含 UTC 时间。脚本拒绝覆盖已有快照、覆盖原库或离开项目范围；CLI 输出还必须留在私有 `.local` 中。

备份包含用户、工单、运行和内部处理记录，可能含认证哈希与内部资料。它被 `.gitignore` 排除，项目发布不上传备份。此脚本只备份 SQLite 数据库，不包含私有附件；它不负责 PostgreSQL 备份或自动恢复现有库。

## SQLite 数据库与附件离线 bundle

数据库与附件需要共同演练时，先停止所有可能写入两者的应用进程，再运行明确确认过的离线备份。工具不自动停止服务，也不声称在线多文件一致快照：

```powershell
.\.venv\Scripts\python.exe scripts\recovery_bundle.py backup --offline-confirmed
```

它使用 SQLite backup API，并对数据库完整性、外键以及数据库列出的活跃附件 UUID 路径、大小和 SHA-256 做校验。bundle 放在私有 `.local/backups/`，可能包含敏感业务数据；不要提交、上传或通过不可信渠道传输。删除 tombstone 的附件文件不要求继续存在。

恢复前会验证清单白名单、数据库及附件校验和、SQLite 完整性和外键。只能恢复到新的 `.local/restores/<目录名>`，目标必须不存在；不覆盖已有数据库或附件。建议只在新的隔离配置中启动恢复副本并确认数据，生产切换不属于该工具：

```powershell
.\.venv\Scripts\python.exe scripts\recovery_bundle.py restore --bundle .local\backups\<bundle目录> --destination .local\restores\<新目录名>
```

PostgreSQL/Docker 本地部署及合成 dump/restore 演练请参阅[部署说明](DEPLOYMENT.md)。两种数据库的备份路径互不兼容；SQLite bundle 不支持 PostgreSQL。

## 运行检查

![实际配置检查](resolveai-readiness.png)

`GET /helpdesk/readiness` 验证数据库查询可执行，统计当前工作区知识片段和 embedding 身份匹配数，检查所选模式是否缺少密钥。只返回密钥是否存在，不返回密钥、地址中的凭据或完整环境变量。

这些检查不连接外部模型、不验证向量列迁移、不证明答案正确性；企业账号与服务工具仍使用明确标注的 fixture。

## 查询与结构

工单与运行的作用域 / 时间复合索引在本地启动时以 checkfirst 创建，包括已存在的表。分页读取摘要，详情按需读取。知识版本与工单事件新增表通过本地 bootstrap 初始化；共享部署仍需要版本化迁移。

## 常见处理

- 交接响应丢失：选择“重试原请求”，不要修改交接内容；版本冲突则先刷新并确认当前接手人，再重新提交。
- 端口被占用：先用 stop.ps1 停止本项目，或指定新的 ApiPort / WebPort。
- 问题已提交但连接中断：保留同一标签页并查看运行记录；前端会查询原请求结果，不会自动重复提交。
- 长时间 running：刷新运行记录，超过三分钟后可标记中断，再使用新请求诊断。
- 模型 / embedding 身份改变：确认维度与库结构，再重新索引；不要混用不同身份的向量。
- 知识保存失败：查看提示和日志；事务回滚保留原知识及索引。

## 构建依赖维护

本次发现并处理了实际 npm 审计问题：Vite 从 7.3.2 更新到 7.3.7，移除不需要的 singlefile 插件及 braces/micromatch 链，更新可兼容修复依赖。当前 npm audit 为 0 个已知报告项；这不代表完整安全审计。标准生产构建现在输出 index.html 与 assets/，开发工作台和 Docker 静态目录使用方式保持适配。

相关来源：[Vite Windows 路径问题](https://github.com/advisories/GHSA-fx2h-pf6j-xcff)、[braces 深度模式问题](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)。

CI 包含格式检查、CSV 检查、类型检查、生产构建和高等级 npm 审计检查。
