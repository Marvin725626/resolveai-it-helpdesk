"""Versioned service catalog administration and structured requester intake."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.sanitizer import sanitize_text_input
from app.helpdesk.catalog_models import CatalogRevision, ServiceCatalogItem
from app.helpdesk.models import HelpdeskTicketEvent, ManualTicketSubmission
from app.helpdesk.workflow import redact
from app.models.customer import Customer
from app.models.ticket import Ticket, TicketCategory, TicketPriority, TicketStatus
from app.models.tenant import Tenant
from app.models.user import UserRole

router = APIRouter(prefix="/helpdesk", tags=["Service catalog"])
_CODE = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_CATEGORIES = {"network", "account", "software", "hardware", "other"}


class FieldInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=2, max_length=80)
    type: str
    required: bool
    options: list[str] | None = None


class CatalogContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=120)
    summary: str = Field(default="", max_length=1000)
    category: str
    fields: list[FieldInput] = Field(default_factory=list, max_length=6)
    status: str


class CreateCatalogInput(CatalogContent):
    request_id: uuid.UUID = Field(strict=False)


class UpdateCatalogInput(CatalogContent):
    expected_version: int = Field(ge=1)


class SubmitCatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: uuid.UUID = Field(strict=False)
    expected_version: int = Field(ge=1)
    answers: dict[str, str]


def _clean(value: str, limit: int) -> str:
    return redact(sanitize_text_input(value, limit)).strip()


def _clean_content(data: CatalogContent, *, creating: bool) -> dict:
    code = data.code.strip().lower()
    title, summary = _clean(data.title, 120), _clean(data.summary, 1000)
    if not _CODE.fullmatch(code):
        raise HTTPException(422, "code must start with a lowercase letter and contain 2–40 lowercase letters, digits, _ or -")
    if not 2 <= len(title) <= 120 or len(summary) > 1000:
        raise HTTPException(422, "Invalid title or summary after sanitization")
    if data.category not in _CATEGORIES:
        raise HTTPException(422, "Invalid catalog category")
    allowed_status = {"draft", "published"} if creating else {"draft", "published", "archived"}
    if data.status not in allowed_status:
        raise HTTPException(422, "Invalid catalog status")
    fields = []
    seen = set()
    total = 0
    for field in data.fields:
        if not _KEY.fullmatch(field.key) or field.key in seen:
            raise HTTPException(422, "Field keys must be unique lowercase identifiers")
        if field.type not in {"text", "textarea", "select"} or type(field.required) is not bool:
            raise HTTPException(422, "Invalid field type or required flag")
        label = _clean(field.label, 80)
        if not 2 <= len(label) <= 80:
            raise HTTPException(422, "Field labels must contain 2–80 characters")
        item = {"key": field.key, "label": label, "type": field.type, "required": field.required}
        if field.type == "select":
            opts = field.options
            if not isinstance(opts, list) or not 2 <= len(opts) <= 10:
                raise HTTPException(422, "Select fields need 2–10 options")
            if any(not isinstance(x, str) or len(x) > 100 for x in opts):
                raise HTTPException(422, "Select options must be strings up to 100 characters")
            clean_opts = [_clean(x, 100) for x in opts]
            if any(not x or len(x) > 100 for x in clean_opts) or len(set(clean_opts)) != len(clean_opts):
                raise HTTPException(422, "Select options must be unique non-empty strings up to 100 characters")
            item["options"] = clean_opts
        elif field.options is not None:
            raise HTTPException(422, "Only select fields may define options")
        total += len(json.dumps(item, ensure_ascii=False))
        fields.append(item)
        seen.add(field.key)
    if total > 5000:
        raise HTTPException(422, "Catalog field templates are too large")
    return {"code": code, "title": title, "summary": summary, "category": data.category,
            "fields": fields, "status": data.status}


def _snapshot(item):
    return {"id": item.id, "code": item.code, "title": item.title, "summary": item.summary,
            "category": item.category, "fields": item.fields, "status": item.status,
            "version": item.version}


def _admin_view(item):
    return {**_snapshot(item), "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat()}


def _require_admin(user):
    if user.role not in (UserRole.TENANT_OWNER, UserRole.TENANT_ADMIN):
        raise HTTPException(403, "Workspace administrator role is required")


async def _revision(db, item, user):
    db.add(CatalogRevision(item_id=item.id, version=item.version, snapshot=_snapshot(item),
        actor_id=user.id, actor_name=user.full_name))


@router.get("/service-catalog")
async def list_public_catalog(user=Depends(get_current_user), db=Depends(get_db)):
    rows = (await db.scalars(select(ServiceCatalogItem).where(
        ServiceCatalogItem.tenant_id == user.tenant_id, ServiceCatalogItem.status == "published")
        .order_by(ServiceCatalogItem.title, ServiceCatalogItem.id))).all()
    return {"items": [{k: v for k, v in _snapshot(row).items() if k != "fields" and k != "status"} for row in rows]}


@router.get("/service-catalog/{item_id}")
async def public_catalog_item(item_id: uuid.UUID, user=Depends(get_current_user), db=Depends(get_db)):
    item = await db.scalar(select(ServiceCatalogItem).where(ServiceCatalogItem.id == str(item_id),
        ServiceCatalogItem.tenant_id == user.tenant_id, ServiceCatalogItem.status == "published"))
    if item is None:
        raise HTTPException(404, "Service not found")
    return {"item": _snapshot(item)}


@router.get("/service-catalog-admin")
async def admin_catalog(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    rows = (await db.scalars(select(ServiceCatalogItem).where(ServiceCatalogItem.tenant_id == user.tenant_id)
        .order_by(ServiceCatalogItem.updated_at.desc(), ServiceCatalogItem.id).limit(50))).all()
    return {"items": [_admin_view(row) for row in rows]}


@router.post("/service-catalog-admin", status_code=201)
async def create_catalog(data: CreateCatalogInput, user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    content = _clean_content(data, creating=True)
    fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    identity, tenant_id, actor_id, actor_name = str(data.request_id), user.tenant_id, user.id, user.full_name
    prior = await db.scalar(select(ServiceCatalogItem).where(ServiceCatalogItem.creation_request_id == identity))
    if prior:
        if prior.tenant_id != tenant_id:
            raise HTTPException(404, "Request not found")
        if prior.creation_fingerprint != fingerprint:
            raise HTTPException(409, "Request ID already belongs to another catalog item")
        return {"item": _admin_view(prior), "replayed": True}
    tenant_lock = await db.execute(update(Tenant).where(Tenant.id == tenant_id).values(updated_at=Tenant.updated_at))
    if tenant_lock.rowcount != 1:
        await db.rollback()
        raise HTTPException(404, "Workspace not found")
    from sqlalchemy import func
    count = await db.scalar(select(func.count()).select_from(ServiceCatalogItem).where(
        ServiceCatalogItem.tenant_id == tenant_id, ServiceCatalogItem.status != "archived")) or 0
    if count >= 20:
        await db.rollback()
        raise HTTPException(409, "At most 20 non-archived services are allowed")
    now = datetime.now(timezone.utc)
    item = ServiceCatalogItem(tenant_id=tenant_id, creation_request_id=identity,
        creation_fingerprint=fingerprint, version=1, created_at=now, updated_at=now, **content)
    db.add(item)
    item_id = item.id
    try:
        await db.flush()
        await _revision(db, item, user)
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        prior = await db.scalar(select(ServiceCatalogItem).where(ServiceCatalogItem.creation_request_id == identity))
        if prior and prior.tenant_id == tenant_id and prior.creation_fingerprint == fingerprint:
            return {"item": _admin_view(prior), "replayed": True}
        raise HTTPException(409, "Catalog code or request ID already exists")
    return {"item": _admin_view(item), "replayed": False}


@router.put("/service-catalog-admin/{item_id}")
async def update_catalog(item_id: uuid.UUID, data: UpdateCatalogInput, user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    content = _clean_content(data, creating=False)
    item = await db.scalar(select(ServiceCatalogItem).where(ServiceCatalogItem.id == str(item_id),
        ServiceCatalogItem.tenant_id == user.tenant_id))
    if item is None:
        raise HTTPException(404, "Service not found")
    if item.version != data.expected_version:
        raise HTTPException(409, "Catalog item was updated; refresh before saving")
    if content["code"] != item.code:
        raise HTTPException(422, "Service code is stable and cannot be changed after creation")
    if item.status == "archived" and content["status"] != "archived":
        tenant_lock = await db.execute(update(Tenant).where(Tenant.id == user.tenant_id).values(updated_at=Tenant.updated_at))
        if tenant_lock.rowcount != 1:
            await db.rollback()
            raise HTTPException(404, "Workspace not found")
        from sqlalchemy import func
        count = await db.scalar(select(func.count()).select_from(ServiceCatalogItem).where(
            ServiceCatalogItem.tenant_id == user.tenant_id, ServiceCatalogItem.status != "archived")) or 0
        if count >= 20:
            await db.rollback()
            raise HTTPException(409, "At most 20 non-archived services are allowed")
    result = await db.execute(update(ServiceCatalogItem).where(ServiceCatalogItem.id == item.id,
        ServiceCatalogItem.tenant_id == user.tenant_id, ServiceCatalogItem.version == data.expected_version)
        .values(**content, version=data.expected_version + 1, updated_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Catalog item was updated; refresh before saving")
    try:
        await db.refresh(item)
        await _revision(db, item, user)
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Catalog item could not be updated")
    return {"item": _admin_view(item)}


@router.get("/service-catalog-admin/{item_id}/revisions")
async def catalog_revisions(item_id: uuid.UUID, user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    item = await db.scalar(select(ServiceCatalogItem.id).where(ServiceCatalogItem.id == str(item_id),
        ServiceCatalogItem.tenant_id == user.tenant_id))
    if not item:
        raise HTTPException(404, "Service not found")
    rows = (await db.scalars(select(CatalogRevision).where(CatalogRevision.item_id == str(item_id))
        .order_by(CatalogRevision.version.desc()).limit(50))).all()
    return {"revisions": [{"version": r.version, "snapshot": r.snapshot, "actor_id": r.actor_id,
        "actor_name": r.actor_name, "created_at": r.created_at.isoformat()} for r in rows]}


def _submission_replay(prior, tenant_id, user_id, item_id, expected_version, answers):
    if prior.tenant_id != tenant_id or prior.user_id != user_id:
        raise HTTPException(404, "Request not found")
    saved = prior.payload.get("service_input", {})
    if saved.get("item_id") != str(item_id) or saved.get("expected_version") != expected_version or saved.get("request_answers") != answers:
        raise HTTPException(409, "Request ID already belongs to another ticket")
    return {"ticket_id": prior.ticket_id, "request_id": prior.request_id, "replayed": True}


def _submission_replay_values(values, tenant_id, user_id, item_id, expected_version, answers):
    if values is None:
        return None
    saved_tenant, saved_user, ticket_id, saved_payload, request_id = values
    if saved_tenant != tenant_id or saved_user != user_id:
        raise HTTPException(404, "Request not found")
    saved = (saved_payload or {}).get("service_input", {})
    if saved.get("item_id") != str(item_id) or saved.get("expected_version") != expected_version or saved.get("request_answers") != answers:
        raise HTTPException(409, "Request ID already belongs to another ticket")
    return {"ticket_id": ticket_id, "request_id": request_id, "replayed": True}


async def _find_submission_values(db, request_id):
    return (await db.execute(select(ManualTicketSubmission.tenant_id, ManualTicketSubmission.user_id,
        ManualTicketSubmission.ticket_id, ManualTicketSubmission.payload, ManualTicketSubmission.request_id).where(
            ManualTicketSubmission.request_id == request_id))).one_or_none()


@router.post("/service-catalog/{item_id}/submit", status_code=201)
async def submit_catalog(item_id: uuid.UUID, data: SubmitCatalogInput, user=Depends(get_current_user), db=Depends(get_db)):
    tenant_id, user_id, actor_name = user.tenant_id, user.id, user.full_name
    identity = str(data.request_id)
    request_answers = {key: _clean(value, 4000) for key, value in data.answers.items()}
    prior = await db.get(ManualTicketSubmission, identity)
    if prior:
        return _submission_replay(prior, tenant_id, user_id, item_id, data.expected_version, request_answers)
    # The no-op UPDATE serializes template edits against submissions on databases with row locks.
    locked = await db.execute(update(ServiceCatalogItem).where(ServiceCatalogItem.id == str(item_id),
        ServiceCatalogItem.tenant_id == tenant_id, ServiceCatalogItem.status == "published",
        ServiceCatalogItem.version == data.expected_version).values(updated_at=ServiceCatalogItem.updated_at)
        .execution_options(synchronize_session=False))
    if locked.rowcount != 1:
        await db.rollback()
        replay = _submission_replay_values(await _find_submission_values(db, identity), tenant_id,
            user_id, item_id, data.expected_version, request_answers)
        if replay:
            return replay
        raise HTTPException(409, "Service changed or is unavailable; refresh and try again")
    item = await db.scalar(select(ServiceCatalogItem).where(ServiceCatalogItem.id == str(item_id),
        ServiceCatalogItem.tenant_id == tenant_id, ServiceCatalogItem.status == "published"))
    if item is None:
        await db.rollback()
        raise HTTPException(404, "Service not found")
    # Recheck idempotency after acquiring the catalog row lock.
    prior = await db.get(ManualTicketSubmission, identity)
    if prior:
        await db.rollback()
        replay = _submission_replay_values(await _find_submission_values(db, identity), tenant_id,
            user_id, item_id, data.expected_version, request_answers)
        if replay:
            return replay
    if item.version != data.expected_version:
        await db.rollback()
        raise HTTPException(409, "Service template changed; refresh before submitting")
    fields = item.fields or []
    by_key = {f["key"]: f for f in fields}
    if set(data.answers) - set(by_key):
        raise HTTPException(422, "Unknown answer field")
    answers = {}
    answer_snapshot = []
    for field in fields:
        raw_value = data.answers.get(field["key"], "")
        max_answer = 1000 if field["type"] == "text" else 4000
        if len(raw_value) > max_answer:
            raise HTTPException(422, f"Answer for {field['label']} is too long")
        value = request_answers.get(field["key"], "")
        if field["required"] and not value:
            raise HTTPException(422, f"{field['label']} is required")
        if field["type"] == "select" and value and value not in field.get("options", []):
            raise HTTPException(422, f"Invalid selection for {field['label']}")
        answers[field["key"]] = value
        answer_snapshot.append({"key": field["key"], "label": field["label"], "type": field["type"], "answer": value})
    if sum(len(x["answer"]) for x in answer_snapshot) > 8000:
        raise HTTPException(422, "Answers are too large")
    service_input = {"item_id": item.id, "code": item.code, "title": item.title,
        "version": item.version, "expected_version": data.expected_version,
        "fields": [{k: f[k] for k in ("key", "label", "type", "options") if k in f} for f in fields],
        "answers": answers, "request_answers": request_answers}
    payload = {"subject": _clean(item.title, 200), "description": f"服务申请：{item.title}（v{item.version}）\n" + "\n".join(
        f"{field['label']}: {field['answer'] or '（未填写）'}" for field in answer_snapshot),
        "category": item.category, "service_input": service_input}
    customer = await db.scalar(select(Customer).where(Customer.tenant_id == tenant_id,
        Customer.email == user.email).order_by(Customer.created_at).limit(1))
    if customer is None:
        customer = Customer(tenant_id=tenant_id, name=user.full_name, email=user.email)
        db.add(customer)
        await db.flush()
    ticket_category = TicketCategory.GENERAL if item.category == "other" else TicketCategory.TECHNICAL
    ticket = Ticket(tenant_id=tenant_id, customer_id=customer.id, subject=payload["subject"],
        description=payload["description"], category=ticket_category, priority=TicketPriority.MEDIUM, status=TicketStatus.OPEN)
    db.add(ticket)
    await db.flush()
    submission = ManualTicketSubmission(request_id=identity, tenant_id=tenant_id, user_id=user_id,
        ticket_id=ticket.id, payload=payload)
    db.add(submission)
    event = HelpdeskTicketEvent(id=identity, tenant_id=tenant_id, ticket_id=ticket.id,
        author_id=user_id, author_name=actor_name, event_type="created",
        payload={"source": "manual", "category": item.category, "service_code": item.code})
    db.add(event)
    ticket_id = ticket.id
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = _submission_replay_values(await _find_submission_values(db, identity), tenant_id,
            user_id, item_id, data.expected_version, request_answers)
        if replay:
            return replay
        raise HTTPException(409, "Request conflict; retry with the same request ID")
    return {"ticket_id": ticket_id, "request_id": identity, "replayed": False}
