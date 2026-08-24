"""Declarative base and shared column helpers."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, MetaData, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def pk_column() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=False), primary_key=True)


def created_at_column() -> Mapped[datetime]:
    """TIMESTAMPTZ defaulted by the database, never by Python."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


def pg_enum(enum_cls: type, type_name: str):
    """A native PostgreSQL enum column type bound to a Python Enum.

    Enum types are created explicitly in the migration, so the ORM must never
    attempt to emit CREATE TYPE itself.
    """
    from sqlalchemy.dialects.postgresql import ENUM as PGEnum

    return PGEnum(
        enum_cls,
        name=type_name,
        create_type=False,
        values_callable=lambda e: [member.value for member in e],
    )
