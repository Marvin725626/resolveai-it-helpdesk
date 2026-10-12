# ResolveAI 当前开发与验证说明

当前开发范围位于 backend/app/helpdesk 与 ResolveAI 前端模块。安装步骤见 README，来源与版权见 NOTICE.md / LICENSE。

提交前验证：

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_resolveai.py -q
cd ..\frontend
npm run format:check
npm run test:csv
npm run build
npm audit --audit-level high
cd ..
.\.venv\Scripts\python.exe scripts\evaluate_isolated.py --strict
```

指定的 ResolveAI 测试与离线评估均使用独立数据库。真实浏览器脚本会访问开发服务；核心及知识脚本会新增开发数据。运行资料、备份、密钥和依赖目录不得提交。请使用实际验收结果，不引用上游主观招聘评分作为当前证据。

## 原上游贡献说明（保留参考）

# Contributing to AI SupportPro

First off, thank you for considering contributing to **AI SupportPro**! It's people like you that make the open-source AI community amazing.

---

## Code of Conduct

We expect all contributors to adhere to a respectful, harassment-free environment for everyone regardless of level of experience, gender, identity, or background.

---

## How Can I Contribute?

### 1. Reporting Bugs
- Check the [Issues tab](https://github.com/theclevertrader/ai-supportpro/issues) to ensure the bug hasn't already been reported.
- Open a new Issue using the **Bug Report** template.
- Provide detailed reproduction steps, expected vs. actual behavior, and environment details (Python version, OS, browser).

### 2. Suggesting Enhancements
- Open a feature request under [Issues](https://github.com/theclevertrader/ai-supportpro/issues).
- Describe the motivation, use case, and proposed implementation details.

### 3. Submitting Pull Requests (PRs)
1. Fork the repo and create your branch from `main`:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. Set up your local environment:
   ```bash
   # Backend
   cd backend
   pip install -r requirements.txt
   
   # Frontend
   cd ../frontend
   npm install
   ```
3. Run tests to ensure all tests pass:
   ```bash
   cd ../backend
   pytest tests/ -v
   ```
4. Commit your changes with a clear commit message:
   ```bash
   git commit -m "feat(rag): add support for hybrid bm25 + vector search"
   ```
5. Push to your fork and submit a Pull Request to `main`.

---

## Development Guidelines

- **Clean Architecture:** Keep business logic separated from API route handlers.
- **Security First:** Never hardcode API keys or secrets. Always use environment variables.
- **Test Coverage:** Any new core backend feature should include unit/integration tests in `backend/tests/`.

---

Thank you for helping make AI SupportPro better! ⭐
