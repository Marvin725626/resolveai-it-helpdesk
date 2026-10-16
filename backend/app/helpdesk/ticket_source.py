"""Shared SQL expressions for ticket provenance without multiplying rows."""
from sqlalchemy import case, exists, select

from app.helpdesk.models import HelpdeskRun, ManualTicketSubmission
from app.models.ticket import Ticket


def ticket_source_expression():
    manual = exists(select(ManualTicketSubmission.request_id).where(
        ManualTicketSubmission.tenant_id == Ticket.tenant_id,
        ManualTicketSubmission.ticket_id == Ticket.id,
    ))
    ai = exists(select(HelpdeskRun.id).where(
        HelpdeskRun.tenant_id == Ticket.tenant_id,
        HelpdeskRun.result["ticket_id"].as_string() == Ticket.id,
    ))
    return case((manual, "manual"), (ai, "ai"), else_="legacy")
