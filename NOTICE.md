# Source and modifications

ResolveAI is a derivative development project based on [AI SupportPro](https://github.com/theclevertrader/ai-supportpro).

- Upstream commit: `944c4dc3bd5ff019b6c261cd656ede7b49a0f200` (see UPSTREAM.json).
- Original copyright and MIT License are retained in LICENSE.
- Original README is retained in README.upstream.md.
- Original authentication, tenant, ticket, database models, provider adapters and API modules are retained.
- New ResolveAI work: `backend/app/helpdesk`, IT knowledge and service fixtures, LangGraph workflow, actual PostgreSQL pgvector path, regression tests, evaluation runner, Chinese React workbench, local lifecycle scripts and Docker configuration.
- Repaired a missing upstream storage adapter and added database pool cleanup on shutdown.

The presence of inherited code or generated changes does not establish personal authorship or real-world deployment experience. Describe your own contribution and verified behavior accurately.
