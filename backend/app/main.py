from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db, engine
from app.core.middleware import SecurityHeadersMiddleware, RateLimitMiddleware, AttachmentBodyLimitMiddleware
from app.api.auth import router as auth_router
from app.api.invitations import router as invitations_router
from app.api.tenants import router as tenants_router
from app.api.knowledge import router as knowledge_router
from app.api.chat import router as chat_router
from app.api.tickets import router as tickets_router
from app.api.analytics import router as analytics_router
from app.api.health import router as health_router
from app.api.audit import router as audit_router
from app.api.integrations import router as integrations_router
from app.api.portal import router as portal_router
from app.helpdesk.api import router as helpdesk_router
from app.helpdesk.knowledge_api import router as knowledge_router_v2
from app.helpdesk.operations_api import router as operations_router
from app.helpdesk.collaboration_api import router as collaboration_router
from app.helpdesk.notifications_api import router as notifications_router
from app.helpdesk.requester_api import router as requester_router
from app.helpdesk.attachments_api import router as attachments_router
from app.helpdesk.resolution_api import router as resolution_router
from app.helpdesk.knowledge_drafts_api import router as knowledge_drafts_router
from app.helpdesk.triage_api import router as triage_router
from app.helpdesk.team_metrics_api import router as team_metrics_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB schema
    await init_db()
    if settings.IT_DEMO_ENABLED and settings.APP_ENV == "development":
        from app.helpdesk.seed import seed_demo
        await seed_demo()
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "ResolveAI IT HelpDesk demo based on AI SupportPro. "
        "LangGraph diagnosis, hybrid retrieval, evidence, simulated read-only tools, and ticket handoff."
    ),
    version="1.7.0",
    lifespan=lifespan
)

# Security Middleware Stack
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AttachmentBodyLimitMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests_per_minute=200)

# CORS Middleware
origins = settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else ["http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins and "*" not in origins else ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router, prefix=settings.API_V1_STR)
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(invitations_router, prefix=settings.API_V1_STR)
app.include_router(tenants_router, prefix=settings.API_V1_STR)
app.include_router(knowledge_router, prefix=settings.API_V1_STR)
app.include_router(chat_router, prefix=settings.API_V1_STR)
app.include_router(tickets_router, prefix=settings.API_V1_STR)
app.include_router(analytics_router, prefix=settings.API_V1_STR)
app.include_router(audit_router, prefix=settings.API_V1_STR)
app.include_router(integrations_router, prefix=settings.API_V1_STR)
app.include_router(portal_router)
app.include_router(helpdesk_router, prefix=settings.API_V1_STR)
app.include_router(knowledge_router_v2, prefix=settings.API_V1_STR)
app.include_router(operations_router, prefix=settings.API_V1_STR)
app.include_router(collaboration_router, prefix=settings.API_V1_STR)
app.include_router(notifications_router, prefix=settings.API_V1_STR)
app.include_router(requester_router, prefix=settings.API_V1_STR)
app.include_router(attachments_router, prefix=settings.API_V1_STR)
app.include_router(resolution_router, prefix=settings.API_V1_STR)
app.include_router(knowledge_drafts_router, prefix=settings.API_V1_STR)
app.include_router(triage_router, prefix=settings.API_V1_STR)
app.include_router(team_metrics_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "tagline": "IT support with evidence and traceable handoff.",
        "version": "1.7.0",
        "docs_url": "/docs",
        "api_prefix": settings.API_V1_STR,
        "status": "operational"
    }
