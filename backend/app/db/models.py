"""Explicit declarative models (SQLAlchemy 2 style: ``DeclarativeBase`` + ``Mapped[]``)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
