#!/usr/bin/env python3
"""Custom PostgreSQL SQL formatter for DBeaver: command-line entry point.

The formatter lives in the `pgfmt/` package next to this file (see docs/architecture.md);
this script stays the path DBeaver calls: `python3 /path/to/psql_custom_formatter.py ${file}`.
"""

from pgfmt import ASTFormatter, Parser, SqlSyntaxError, format_sql, join_expr, tokenize  # noqa: F401
from pgfmt.cli import main

if __name__ == '__main__':
    main()
