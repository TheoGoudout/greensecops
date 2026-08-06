#!/usr/bin/env python
"""Dump the schema SQLModel's metadata describes, as order-insensitive JSON.

Used to prove a pure-refactor of the model definitions (e.g. lifting shared
columns into mixins) changes no DDL. Raw ``CREATE TABLE`` text is unusable for
that: inheriting a mixin reorders the columns, which rewrites the statement
without changing the schema. This compares the things that actually matter —
column types, nullability, defaults, keys, constraints and indexes — with every
collection sorted.

    python scripts/schema_snapshot.py before.json
    # ...refactor...
    python scripts/schema_snapshot.py after.json
    diff before.json after.json
"""

import json
import sys
from typing import Any

from sqlalchemy.dialects import postgresql
from sqlmodel import SQLModel

import app.models  # noqa: F401  — importing registers every table on the metadata


def _default_repr(default: Any) -> str | None:
    if default is None:
        return None
    arg = default.arg
    return getattr(arg, "__qualname__", None) or repr(arg)


def _column(col: Any) -> dict[str, Any]:
    return {
        "type": str(col.type.compile(dialect=postgresql.dialect())),
        "nullable": col.nullable,
        "primary_key": col.primary_key,
        "unique": bool(col.unique),
        "index": bool(col.index),
        # Name, not repr: a callable default (uuid4, get_datetime_utc) reprs
        # with its memory address, which differs between two runs and would
        # swamp a real diff.
        "default": _default_repr(col.default),
        "server_default": (
            str(col.server_default.arg) if col.server_default is not None else None
        ),
        "autoincrement": col.autoincrement,
        "foreign_keys": sorted(
            f"{fk.target_fullname}|ondelete={fk.ondelete}" for fk in col.foreign_keys
        ),
    }


def snapshot() -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for name in sorted(SQLModel.metadata.tables):
        table = SQLModel.metadata.tables[name]
        tables[name] = {
            "columns": {
                c.name: _column(c) for c in sorted(table.columns, key=lambda c: c.name)
            },
            "primary_key": sorted(c.name for c in table.primary_key),
            "unique_constraints": sorted(
                f"{c.name}({','.join(sorted(col.name for col in c.columns))})"
                for c in table.constraints
                if c.__class__.__name__ == "UniqueConstraint"
            ),
            "indexes": sorted(
                f"{i.name}({','.join(sorted(col.name for col in i.columns))})"
                f"|unique={bool(i.unique)}"
                for i in table.indexes
            ),
        }
    return tables


if __name__ == "__main__":
    out = json.dumps(snapshot(), indent=2, sort_keys=True)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as handle:
            handle.write(out + "\n")
        print(f"wrote {len(snapshot())} tables to {sys.argv[1]}")
    else:
        print(out)
