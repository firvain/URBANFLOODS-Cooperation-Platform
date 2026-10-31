"""FAIR exports (CC BY 4.0): published posts and threads as JSON, posts as CSV, and a
Frictionless Data Package descriptor listing them. Public; published content only; never an
email address (``crud/export.py``, ``schemas/export.py``).

The JSON and CSV bodies are streamed: the rows are read in keyset chunks while the response is
written. A streaming body outlives the request's ``DbTx`` (committed before the response
starts), so the body opens its own read-only session. The ``ETag`` / ``Last-Modified``
validators are computed up front on ``DbTx``; a matching ``If-None-Match`` gets a 304.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from email.utils import format_datetime

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.export import (
    LICENSE_ID,
    LICENSE_TITLE,
    CsvDialect,
    DataPackage,
    DataPackageContributor,
    DataPackageLicense,
    DataPackageSource,
    DataResource,
    ExportAuthor,
    ExportPost,
    ExportThread,
    TableField,
    TableSchema,
    frontend_url,
    post_url,
)
from app.core.config import settings
from app.core.deps import DbTx
from app.crud import export as crud_export
from app.db.session import AsyncSessionLocal
from app.services.csv_cells import csv_cell

router = APIRouter()

FILENAME_PREFIX = "urbanfloods-cooperation"
JSON_MEDIA_TYPE = "application/json"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
CSV_FIELDS = [
    TableField(name="id", type="integer", description="Post id."),
    TableField(name="slug", type="string", description="URL slug."),
    TableField(name="title", type="string", description="Title."),
    TableField(name="locale", type="string", description="Language code of the post."),
    TableField(name="category", type="string", description="Category name."),
    TableField(name="tags", type="string", description="Tag names separated by ';'."),
    TableField(
        name="author",
        type="string",
        description="Author display name ('Deleted user' for erased accounts).",
    ),
    TableField(name="organisation", type="string", description="Author's organisation."),
    TableField(name="published_at", type="datetime", description="Publication time (UTC)."),
    TableField(name="url", type="string", format="uri", description="Canonical page URL."),
]
CSV_NOTE = (
    "Text cells starting with =, +, -, @, tab or carriage return are prefixed with an "
    "apostrophe so spreadsheet applications do not run them as formulas."
)
PROGRAMME_URL = "https://www.interreg-ipa-adrion.eu/"


def _license() -> DataPackageLicense:
    return DataPackageLicense(
        name=LICENSE_ID, path=settings.CONTENT_LICENSE_URL, title=LICENSE_TITLE
    )


def _attachment(kind: str, extension: str) -> str:
    today = datetime.now(UTC).date().isoformat()
    return f'attachment; filename="{FILENAME_PREFIX}-{kind}-{today}.{extension}"'


def _validators(version: crud_export.ExportVersion) -> dict[str, str]:
    headers = {"ETag": version.etag}
    if version.last_modified is not None:
        headers["Last-Modified"] = format_datetime(
            version.last_modified.astimezone(UTC), usegmt=True
        )
    return headers


def _not_modified(request: Request, headers: dict[str, str]) -> Response | None:
    tags = {tag.strip() for tag in request.headers.get("if-none-match", "").split(",")}
    if headers["ETag"] in tags or "*" in tags:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return None


async def _json_array(
    chunks: Callable[[AsyncSession], AsyncIterator[list[str]]],
) -> AsyncIterator[bytes]:
    """``[item, item, ...]`` written chunk by chunk, on a session of its own."""
    async with AsyncSessionLocal() as db:
        yield b"["
        first = True
        async for items in chunks(db):
            if not items:
                continue
            body = ",".join(items)
            yield (body if first else f",{body}").encode()
            first = False
        yield b"]"


async def _post_items(db: AsyncSession) -> AsyncIterator[list[str]]:
    async for chunk in crud_export.iter_posts(db):
        yield [ExportPost.of(item).model_dump_json() for item in chunk]


async def _thread_items(db: AsyncSession) -> AsyncIterator[list[str]]:
    async for chunk in crud_export.iter_threads(db):
        yield [ExportThread.of(item).model_dump_json() for item in chunk]


def _csv_line(cells: list[object]) -> bytes:
    buffer = io.StringIO()
    csv.writer(buffer).writerow([csv_cell(cell) for cell in cells])
    return buffer.getvalue().encode()


async def _posts_csv() -> AsyncIterator[bytes]:
    async with AsyncSessionLocal() as db:
        yield _csv_line([field.name for field in CSV_FIELDS])
        async for chunk in crud_export.iter_posts(db, with_children=False):
            lines = []
            for item in chunk:
                post = item.post
                author = ExportAuthor.of(post.author)
                lines.append(
                    _csv_line(
                        [
                            post.id,
                            post.slug,
                            post.title,
                            post.locale,
                            post.category.name,
                            ";".join(tag.name for tag in post.tags),
                            author.display_name,
                            author.organisation.name if author.organisation else None,
                            post.published_at.isoformat() if post.published_at else None,
                            post_url(post.slug),
                        ]
                    )
                )
            yield b"".join(lines)


async def _streamed(
    request: Request,
    version: crud_export.ExportVersion,
    body: Callable[[], AsyncIterator[bytes]],
    *,
    media_type: str,
    disposition: str,
) -> Response:
    headers = _validators(version)
    not_modified = _not_modified(request, headers)
    if not_modified is not None:
        return not_modified
    headers["Content-Disposition"] = disposition
    return StreamingResponse(body(), media_type=media_type, headers=headers)


@router.get(
    "/posts.json",
    response_model=list[ExportPost],
    responses={304: {"description": "Not modified (If-None-Match)"}},
)
async def export_posts_json(request: Request, db: DbTx) -> Response:
    """Every published post with its published comments and KNOWBASE links, oldest id first."""
    version = await crud_export.posts_version(db)
    return await _streamed(
        request,
        version,
        lambda: _json_array(_post_items),
        media_type=JSON_MEDIA_TYPE,
        disposition=_attachment("posts", "json"),
    )


@router.get(
    "/threads.json",
    response_model=list[ExportThread],
    responses={304: {"description": "Not modified (If-None-Match)"}},
)
async def export_threads_json(request: Request, db: DbTx) -> Response:
    """Every published thread with its published replies and KNOWBASE links, oldest id first."""
    version = await crud_export.threads_version(db)
    return await _streamed(
        request,
        version,
        lambda: _json_array(_thread_items),
        media_type=JSON_MEDIA_TYPE,
        disposition=_attachment("threads", "json"),
    )


@router.get(
    "/posts.csv",
    response_class=Response,
    responses={
        200: {"description": "One row per published post (no bodies)", "content": {"text/csv": {}}},
        304: {"description": "Not modified (If-None-Match)"},
    },
)
async def export_posts_csv(request: Request, db: DbTx) -> Response:
    """One row per published post, no bodies; columns as in the data package schema."""
    version = await crud_export.posts_csv_version(db)
    return await _streamed(
        request,
        version,
        _posts_csv,
        media_type=CSV_MEDIA_TYPE,
        disposition=_attachment("posts", "csv"),
    )


@router.get("/datapackage.json", response_model=DataPackage)
async def datapackage() -> JSONResponse:
    """Frictionless Data Package (v2) descriptor of the three exports."""
    licenses = [_license()]
    export_base = frontend_url(f"{settings.API_V1_PREFIX}/export")
    package = DataPackage(
        name="urbanfloods-cooperation-platform",
        title="URBANFLOODS Cooperation Platform: blog posts and forum threads",
        description=(
            "Published blog posts (with comments) and forum threads (with replies) of the "
            "URBANFLOODS Cooperation Platform, a hub for flood-management stakeholders "
            "(deliverable D.5.1.1). Only publicly visible content is included; author email "
            "addresses never are. Contributions are licensed under CC BY 4.0."
        ),
        homepage=frontend_url(),
        created=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        keywords=["urban flooding", "flood risk management", "nature-based solutions", "forum"],
        licenses=licenses,
        sources=[
            DataPackageSource(
                title="URBANFLOODS (IPA-ADRION00374), Interreg IPA ADRION Programme",
                path=PROGRAMME_URL,
            ),
            DataPackageSource(title="URBANFLOODS Cooperation Platform", path=frontend_url()),
        ],
        contributors=[
            DataPackageContributor(
                title="URBANFLOODS project partnership",
                path=frontend_url("/about#partnership"),
                roles=["publisher"],
            ),
            DataPackageContributor(
                title="Cooperation Platform members (content authors)", roles=["author"]
            ),
        ],
        resources=[
            DataResource(
                name="posts-json",
                path=f"{export_base}/posts.json",
                title="Blog posts (JSON)",
                description="Published blog posts with published comments and KNOWBASE links.",
                format="json",
                mediatype="application/json",
                licenses=licenses,
            ),
            DataResource(
                name="threads-json",
                path=f"{export_base}/threads.json",
                title="Forum threads (JSON)",
                description="Published forum threads with published replies and KNOWBASE links.",
                format="json",
                mediatype="application/json",
                licenses=licenses,
            ),
            DataResource(
                name="posts-csv",
                path=f"{export_base}/posts.csv",
                title="Blog posts (CSV)",
                description=f"One row per published blog post, without bodies. {CSV_NOTE}",
                format="csv",
                mediatype="text/csv",
                licenses=licenses,
                type="table",
                dialect=CsvDialect(),
                table_schema=TableSchema(fields=CSV_FIELDS, primary_key=["id"]),
            ),
        ],
    )
    return JSONResponse(package.model_dump(mode="json", by_alias=True, exclude_none=True))
