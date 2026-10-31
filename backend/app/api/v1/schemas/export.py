"""FAIR export schemas: posts and threads with their public children, licensed CC BY 4.0.

Never an email address: authors are ``{id, display_name, organisation}``, and an anonymised or
removed author is ``{id: null, display_name: "Deleted user", organisation: null}``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.crud.export import PostExport, ThreadExport
from app.crud.user import DELETED_DISPLAY_NAME
from app.db.enums import KbType
from app.db.models import Category, KnowbaseLink, Tag, User

LICENSE_ID = "CC-BY-4.0"
LICENSE_TITLE = "Creative Commons Attribution 4.0"


def frontend_url(path: str = "") -> str:
    """Absolute URL of a frontend path (the site is same-origin: the API and the feeds are
    served under ``FRONTEND_URL`` too)."""
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}"


def post_url(slug: str) -> str:
    return frontend_url(f"/blog/{slug}")


def thread_url(slug: str) -> str:
    return frontend_url(f"/forum/t/{slug}")


class ExportOrganisation(BaseModel):
    id: int
    name: str
    short_name: str
    country: str


class ExportAuthor(BaseModel):
    id: int | None
    display_name: str
    organisation: ExportOrganisation | None

    @classmethod
    def of(cls, user: User | None) -> ExportAuthor:
        if user is None or user.deleted_at is not None:
            return cls(id=None, display_name=DELETED_DISPLAY_NAME, organisation=None)
        organisation = user.organisation
        return cls(
            id=user.id,
            display_name=user.display_name,
            organisation=(
                ExportOrganisation(
                    id=organisation.id,
                    name=organisation.name,
                    short_name=organisation.short_name,
                    country=organisation.country,
                )
                if organisation is not None
                else None
            ),
        )


def author_name(user: User | None) -> str:
    return ExportAuthor.of(user).display_name


class ExportCategory(BaseModel):
    slug: str
    name: str

    @classmethod
    def of(cls, category: Category) -> ExportCategory:
        return cls(slug=category.slug, name=category.name)


class ExportTag(BaseModel):
    slug: str
    name: str

    @classmethod
    def of(cls, tag: Tag) -> ExportTag:
        return cls(slug=tag.slug, name=tag.name)


class ExportKnowbaseLink(BaseModel):
    kb_type: KbType
    kb_id: int
    title: str

    @classmethod
    def of(cls, link: KnowbaseLink) -> ExportKnowbaseLink:
        return cls(kb_type=link.kb_type, kb_id=link.kb_id, title=link.cached_title_en)


class ExportComment(BaseModel):
    id: int
    author: ExportAuthor
    body_text: str
    created_at: datetime


class ExportReply(BaseModel):
    id: int
    parent_reply_id: int | None
    author: ExportAuthor
    body_text: str
    created_at: datetime


class _ExportContent(BaseModel):
    id: int
    slug: str
    title: str
    locale: str
    category: ExportCategory
    tags: list[ExportTag]
    author: ExportAuthor
    published_at: datetime | None
    updated_at: datetime
    body_text: str
    body_html: str
    url: str
    knowbase_links: list[ExportKnowbaseLink]
    license: Literal["CC-BY-4.0"] = LICENSE_ID
    license_url: str


class ExportPost(_ExportContent):
    excerpt: str | None
    event_at: datetime | None
    event_url: str | None
    comments: list[ExportComment]

    @classmethod
    def of(cls, item: PostExport) -> ExportPost:
        post = item.post
        return cls(
            id=post.id,
            slug=post.slug,
            title=post.title,
            locale=post.locale,
            category=ExportCategory.of(post.category),
            tags=[ExportTag.of(tag) for tag in post.tags],
            author=ExportAuthor.of(post.author),
            published_at=post.published_at,
            updated_at=post.updated_at,
            excerpt=post.excerpt,
            body_text=post.body_text,
            body_html=post.body_html,
            url=post_url(post.slug),
            knowbase_links=[ExportKnowbaseLink.of(link) for link in item.links],
            event_at=post.event_at,
            event_url=post.event_url,
            comments=[
                ExportComment(
                    id=comment.id,
                    author=ExportAuthor.of(comment.author),
                    body_text=comment.body_text,
                    created_at=comment.created_at,
                )
                for comment in item.comments
            ],
            license_url=settings.CONTENT_LICENSE_URL,
        )


class ExportThread(_ExportContent):
    replies: list[ExportReply]

    @classmethod
    def of(cls, item: ThreadExport) -> ExportThread:
        thread = item.thread
        return cls(
            id=thread.id,
            slug=thread.slug,
            title=thread.title,
            locale=thread.locale,
            category=ExportCategory.of(thread.category),
            tags=[ExportTag.of(tag) for tag in thread.tags],
            author=ExportAuthor.of(thread.author),
            published_at=thread.published_at,
            updated_at=thread.updated_at,
            body_text=thread.body_text,
            body_html=thread.body_html,
            url=thread_url(thread.slug),
            knowbase_links=[ExportKnowbaseLink.of(link) for link in item.links],
            replies=[
                ExportReply(
                    id=reply.id,
                    parent_reply_id=reply.parent_reply_id,
                    author=ExportAuthor.of(reply.author),
                    body_text=reply.body_text,
                    created_at=reply.created_at,
                )
                for reply in item.replies
            ],
            license_url=settings.CONTENT_LICENSE_URL,
        )


# --- datapackage ------------------------------------------------------------------------------
# Field names follow the Data Package v2 spec (https://datapackage.org); serialise with
# ``by_alias=True, exclude_none=True``.

DATAPACKAGE_PROFILE = "https://datapackage.org/profiles/2.0/datapackage.json"
DATARESOURCE_PROFILE = "https://datapackage.org/profiles/2.0/dataresource.json"
TABLESCHEMA_PROFILE = "https://datapackage.org/profiles/2.0/tableschema.json"


class DataPackageLicense(BaseModel):
    name: str
    path: str
    title: str


class DataPackageSource(BaseModel):
    title: str
    path: str | None = None


class DataPackageContributor(BaseModel):
    title: str
    path: str | None = None
    roles: list[str]


class TableField(BaseModel):
    name: str
    type: str
    format: str | None = None
    description: str


class TableSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    profile: str = Field(default=TABLESCHEMA_PROFILE, alias="$schema")
    fields: list[TableField]
    primary_key: list[str] = Field(alias="primaryKey")


class CsvDialect(BaseModel):
    delimiter: str = ","
    header: bool = True


class DataResource(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    profile: str = Field(default=DATARESOURCE_PROFILE, alias="$schema")
    name: str
    path: str
    title: str
    description: str
    format: Literal["json", "csv"]
    mediatype: str
    encoding: str = "utf-8"
    licenses: list[DataPackageLicense]
    type: Literal["table"] | None = None
    dialect: CsvDialect | None = None
    table_schema: TableSchema | None = Field(default=None, alias="schema")


class DataPackage(BaseModel):
    """A Frictionless Data Package (v2) descriptor."""

    model_config = ConfigDict(populate_by_name=True)

    profile: str = Field(default=DATAPACKAGE_PROFILE, alias="$schema")
    name: str
    title: str
    description: str
    homepage: str
    created: str
    keywords: list[str]
    licenses: list[DataPackageLicense]
    sources: list[DataPackageSource]
    contributors: list[DataPackageContributor]
    resources: list[DataResource]
