"""Shared JSON error output for CLI commands."""

from __future__ import annotations

import json
from typing import Any

import typer

from hyperscaled.exceptions import RuleViolationError


def json_error(exc: Exception) -> None:
    """Print a structured JSON error to stdout and raise ``typer.Exit(1)``.

    The envelope always contains ``error`` and ``message``.  For
    :class:`RuleViolationError` subclasses the output also includes
    ``rule_id``, ``current_value``, and ``limit``.
    """
    payload: dict[str, Any] = {"error": type(exc).__name__, "message": str(exc)}

    if isinstance(exc, RuleViolationError):
        payload["rule_id"] = exc.rule_id
        payload["current_value"] = exc.current_value
        payload["limit"] = exc.limit

    typer.echo(json.dumps(payload, indent=2, default=str))
    raise typer.Exit(code=1)
