"""Thin wrapper over the Databricks SQL Statement Execution API.

Auth comes from the environment: the app's service principal on Databricks Apps,
or DATABRICKS_CONFIG_PROFILE locally.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

from . import config


@lru_cache(maxsize=1)
def client() -> WorkspaceClient:
    return WorkspaceClient()


def _convert(value: str | None, type_name: str) -> Any:
    if value is None:
        return None
    t = type_name.upper()
    if t in ("INT", "LONG", "BIGINT", "SHORT", "BYTE", "INTEGER"):
        return int(value)
    if t in ("DOUBLE", "FLOAT", "DECIMAL"):
        return float(value)
    if t == "BOOLEAN":
        return value.lower() == "true"
    if t in ("ARRAY", "MAP", "STRUCT"):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def query(statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a parameterised statement (use :name markers) and return rows as dicts."""
    items = [StatementParameterListItem(name=k, value=None if v is None else str(v)) for k, v in (params or {}).items()]
    resp = client().statement_execution.execute_statement(
        statement=statement,
        warehouse_id=config.WAREHOUSE_ID,
        parameters=items or None,
        wait_timeout="50s",
    )
    state = resp.status.state if resp.status else None
    if state != StatementState.SUCCEEDED:
        msg = resp.status.error.message if resp.status and resp.status.error else str(state)
        raise RuntimeError(f"SQL failed: {msg}")
    cols = [(c.name, c.type_name.value if c.type_name else "STRING") for c in resp.manifest.schema.columns]
    rows = (resp.result.data_array if resp.result else None) or []
    return [{name: _convert(v, t) for (name, t), v in zip(cols, row)} for row in rows]


def fq(name: str) -> str:
    """Fully qualified object name in the configured catalog/schema."""
    return f"{config.CATALOG}.{config.SCHEMA}.{config.OBJECT_PREFIX}{name}"
