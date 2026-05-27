"""Safe-expression compiler exception types."""

from __future__ import annotations


class SafeExpressionCompileError(ValueError):
    """Raised when a parsed expression is outside the supported compiler subset."""
