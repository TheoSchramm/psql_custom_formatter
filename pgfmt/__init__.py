"""Custom PostgreSQL SQL formatter for DBeaver.

Reads SQL from stdin or a file, formats it, and outputs the result.
File mode formats in-place (for DBeaver temp file integration)."""

from __future__ import annotations
from .constants import SqlSyntaxError
from .formatter import ASTFormatter
from .parser import Parser
from .tokenizer import join_expr, tokenize


def format_sql(sql):
    """Format SQL, returning original unchanged if any error occurs."""
    try:
        spans = []
        tokens = tokenize(sql, spans)
        parser = Parser(tokens, sql, spans)
        results = parser.parse_all()
        formatter = ASTFormatter()
        return formatter.format_all(results)
    except Exception:
        return sql


__all__ = ['format_sql', 'tokenize', 'join_expr', 'Parser', 'ASTFormatter', 'SqlSyntaxError']
