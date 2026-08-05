"""Shared helpers for the ORM → public-schema mappers.

The per-engine mappers were field-for-field copies of each other: a scan mapper
that listed the same ten attributes three times, a finding mapper the same
again. Since the public schemas now share bases (see ``models/schemas.py``),
the copying can go too — :func:`to_public` reads which fields the target schema
declares and lifts exactly those off the ORM row.
"""

from typing import Any, TypeVar

from sqlmodel import SQLModel

from app.models import ScanStatus

P = TypeVar("P", bound=SQLModel)


def to_public(source: Any, schema: type[P], **overrides: Any) -> P:
    """Build ``schema`` from the same-named attributes of ``source``.

    Only fields the schema declares are read, so a column added to a table is
    not accidentally exposed — a public schema stays an explicit allow-list.
    ``overrides`` supply anything that isn't a plain attribute copy (a rule's
    slug, a fix's PR URL, a computed badge signature) and win over the source.
    """
    values: dict[str, Any] = {
        name: getattr(source, name)
        for name in schema.model_fields
        if name not in overrides and hasattr(source, name)
    }
    return schema(**values, **overrides)


def latest_completed_scan(container: Any) -> Any:
    """The most recent successfully completed scan of a target, or ``None``.

    A target's grade *is* its latest completed scan's grade — there is no
    separate aggregation to keep in sync — so this is the single definition
    the mappers and the badge routes both use. Deliberately ignores failed and
    in-flight scans: a target whose latest scan errored still has the grade its
    last good scan produced.
    """
    return max(
        (s for s in container.scans if s.status == ScanStatus.completed),
        key=lambda s: s.created_at or 0,
        default=None,
    )
