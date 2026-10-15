"""Command-line entry point (stdin/stdout, in-place file, --check, --diff)."""

from __future__ import annotations
import sys
from . import format_sql


def main():
    import argparse
    import difflib

    parser = argparse.ArgumentParser(
        description='Custom PostgreSQL SQL formatter for DBeaver.')
    parser.add_argument('file', nargs='?', default=None,
                        help='SQL file to format (in-place unless --check or --diff)')
    parser.add_argument('--check', action='store_true',
                        help='Check if file is already formatted (exit 0=yes, 1=no)')
    parser.add_argument('--diff', action='store_true',
                        help='Show diff between original and formatted output')
    args = parser.parse_args()

    # Read SQL from file or stdin
    label = args.file or 'stdin'
    if args.file:
        with open(args.file, 'r') as f:
            sql = f.read()
    else:
        sql = sys.stdin.read()

    result = format_sql(sql)

    if args.check:
        sys.exit(0 if sql == result else 1)

    if args.diff:
        if sql == result:
            sys.exit(0)
        diff = difflib.unified_diff(
            sql.splitlines(keepends=True),
            result.splitlines(keepends=True),
            fromfile=label,
            tofile=label + ' (formatted)',
        )
        sys.stdout.writelines(diff)
        sys.exit(1)

    # Default: format in-place for files, stdout for stdin
    if args.file:
        with open(args.file, 'w') as f:
            f.write(result)
    else:
        sys.stdout.write(result)
