# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A custom Python SQL formatter for PostgreSQL, designed as an external formatter for DBeaver. Single file, zero dependencies. See [README.md](README.md) for usage and examples.

## Quick Reference

```bash
# Format from stdin
echo "SELECT * FROM foo WHERE id = 1" | python3 psql_custom_formatter.py

# Format file in-place
python3 psql_custom_formatter.py ${file}

# Regression test
cat tests/fixtures/input.sql | python3 psql_custom_formatter.py | diff - tests/fixtures/expected.sql

# Full test suite (63 tests)
python3 tests/run_tests.py
```

## Key Documentation

- [CHANGELOG.md](CHANGELOG.md) — All fix history and version changes
- [docs/known-issues.md](docs/known-issues.md) — Open bugs and improvement opportunities
- [docs/architecture.md](docs/architecture.md) — Internal architecture and test pipeline

## Formatting Style Rules

These rules define the formatter's output. Follow them exactly when modifying formatter behavior.

- **Indentation**: 4 spaces
- **Major clauses** (SELECT, FROM, WHERE, etc.): left-aligned on their own line
- **Column lists**: indented under clause, leading comma style (`, column`)
- **Comma-separated FROM tables**: each table on its own line with leading comma style (`, table_b`)
- **JOINs**: indented under FROM, ON conditions double-indented
- **AND/OR in ON conditions**: each on new line, double-indented under the JOIN
- **AND/OR in WHERE**: each on new line, indented under WHERE
- **CASE expressions**: WHEN/ELSE indented, THEN result on next line further indented
- **Subqueries**: wrapped in parens with increased indent level; AND/OR inlined in subquery WHERE clauses
- **CREATE TABLE ... AS SELECT**: table name indented under CREATE TABLE, entire SELECT block indented one level
- **IN (...) lists**: expanded one per line with leading commas when more than 3 values; `IN (SELECT ...)` formats the subquery indented inside the parens
- **Keywords**: uppercased during formatting
- **Identifiers**: preserved as lowercase (common column names like `name`, `value`, `type` are intentionally excluded from the keyword list)
- **Cast operator** (`::`) : no spaces, type uppercased (e.g., `col::TEXT`)
- **Comments**: inline trailing comments (`--`) tab-aligned; standalone `--` comments on their own indented line within clauses; block comments (`/* */`) kept inline with the item they precede; the first comment after an expression is always treated as trailing (positional info is lost during tokenization)
- **Statement separation**: 3 blank lines between code blocks
- **Comment groups**: comments directly before a statement attach to it; blank lines in original source between comment groups are preserved as 3-blank-line gaps
- **Header comment blocks**: 3 blank lines before the first SQL statement when separated by blank lines in the original
- **Supported statements**: SELECT, INSERT, UPDATE, DELETE, CREATE TABLE ... AS SELECT, WITH/CTE, DO blocks
