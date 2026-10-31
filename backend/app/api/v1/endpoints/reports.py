"""Reports: a verified member reports published content (rate limited); admins list, inspect,
resolve and dismiss reports.

Mounted at ``/reports``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.v1.schemas.report import (
    PaginatedReports,
    ReportCreate,
    ReportCreated,
    ReportDetail,
    report_detail,
)
from app.core.deps import AdminUser, DbTx, VerifiedUser
from app.core.exceptions import AppError, error_body
from app.core.rate_limit import limit
from app.crud import reports as crud_reports
from app.db.enums import ContentType, ReportStatus
from app.db.models import Report

router = APIRouter()

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
CREATE_LIMIT = limit("reports.create", 20, 86400)

ReportId = Annotated[int, Path(ge=1, le=2**63 - 1)]


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


ACTION_ERRORS = _error_responses(401, 403, 404, 409, 422)


async def _detail(db: DbTx, report: Report) -> ReportDetail:
    contents = await crud_reports.load_contents(db, reports=[report])
    return report_detail(report, contents)


async def _get_or_404(db: DbTx, report_id: int) -> Report:
    report = await crud_reports.get_report(db, report_id=report_id)
    if report is None:
        raise AppError(404, "report.not_found", "Report not found.")
    return report


@router.post(
    "/",
    response_model=ReportCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(CREATE_LIMIT)],
    responses=_error_responses(400, 401, 403, 404, 409, 422, 429),
)
async def create_report(body: ReportCreate, user: VerifiedUser, db: DbTx) -> ReportCreated:
    """Report a published post, thread, reply or comment (once per item). Enough distinct
    reporters hide the content automatically (``auto_hidden`` in the response)."""
    report, auto_hidden = await crud_reports.create_report(
        db,
        reporter=user,
        content_type=body.content_type,
        content_id=body.content_id,
        reason=body.reason,
        details=body.details,
    )
    return ReportCreated(
        id=report.id,
        content_type=report.content_type,
        content_id=report.content_id,
        reason=report.reason,
        status=report.status,
        created_at=report.created_at,
        auto_hidden=auto_hidden,
    )


@router.get("/", response_model=PaginatedReports, responses=_error_responses(401, 403, 422))
async def list_reports(
    admin: AdminUser,
    db: DbTx,
    status_: Annotated[ReportStatus | None, Query(alias="status")] = None,
    content_type: Annotated[ContentType | None, Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PaginatedReports:
    """Reports, newest first, each with a summary of the reported content (admins)."""
    total, reports = await crud_reports.list_reports(
        db, status=status_, content_type=content_type, skip=skip, limit=limit_
    )
    contents = await crud_reports.load_contents(db, reports=reports)
    return PaginatedReports(total=total, items=[report_detail(r, contents) for r in reports])


@router.get("/{report_id}", response_model=ReportDetail, responses=_error_responses(401, 403, 404))
async def get_report(report_id: ReportId, admin: AdminUser, db: DbTx) -> ReportDetail:
    """One report with the reported content's summary (admins)."""
    return await _detail(db, await _get_or_404(db, report_id))


@router.post("/{report_id}/resolve", response_model=ReportDetail, responses=ACTION_ERRORS)
async def resolve_report(report_id: ReportId, admin: AdminUser, db: DbTx) -> ReportDetail:
    """Mark an open report as acted upon (admins). The content itself is moderated separately."""
    report = await _get_or_404(db, report_id)
    await crud_reports.resolve_report(db, report=report, actor=admin)
    return await _detail(db, await _get_or_404(db, report.id))


@router.post("/{report_id}/dismiss", response_model=ReportDetail, responses=ACTION_ERRORS)
async def dismiss_report(report_id: ReportId, admin: AdminUser, db: DbTx) -> ReportDetail:
    """Close an open report without action (admins)."""
    report = await _get_or_404(db, report_id)
    await crud_reports.dismiss_report(db, report=report, actor=admin)
    return await _detail(db, await _get_or_404(db, report.id))
