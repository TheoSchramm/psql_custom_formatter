# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A custom Python SQL formatter for PostgreSQL, designed as an external formatter for DBeaver. Pure-Python package `pgfmt/` behind the entry point `psql_custom_formatter.py`, zero dependencies. See [README.md](README.md) for usage and examples.

## Quick Reference

```bash
# Format from stdin
echo "SELECT * FROM foo WHERE id = 1" | python3 psql_custom_formatter.py

# Format file in-place
python3 psql_custom_formatter.py ${file}

# Regression test
cat tests/fixtures/input.sql | python3 psql_custom_formatter.py | diff - tests/fixtures/expected.sql

# Full test suite (349 tests)
python3 tests/run_tests.py

# PostgreSQL 18 conformance: 3,249 statements from the official manual (examples + every
# command's Synopsis forms). With pglast installed (PG 18 parser) it also checks that input
# and output parse to the same tree: `pip install pglast` in a venv, then run with that python.
python3 tests/pg_conformance.py
# Same checks over PostgreSQL's own regression suite (~48,700 statements; needs pglast and a
# PG 18 source tree: postgresql-18.x/src/test/regress/sql)
python3 tests/pg_conformance.py --regress /path/to/postgresql-18.0/src/test/regress/sql
# Feature inventory: every keyword phrase of every SQL command Synopsis in the manual must
# occur in a verified statement of that command (needs pglast)
python3 tests/pg_conformance.py --inventory
```

## Where Things Live

`Parser` and `ASTFormatter` are mixins split by statement family; full map in [docs/architecture.md](docs/architecture.md#module-map). A fix usually touches the same family in both trees.

| Change | Files |
|---|---|
| keyword lists, operators/precedence, clause boundaries (what ends WHERE / GROUP BY / JOIN ON / ORDER BY / SET), layout limits | `pgfmt/constants.py` — shared or SQL-language tables go here; a table used by one method stays next to it |
| how text is split into tokens | `pgfmt/tokenizer.py` |
| a new AST node / field | `pgfmt/nodes.py` |
| expressions (operators, CASE, function calls) | `pgfmt/parser/expressions.py` + `pgfmt/formatter/expressions.py` |
| SELECT / FROM / JOIN / WITH | `pgfmt/parser/select.py` + `pgfmt/formatter/select.py` |
| INSERT / UPDATE / DELETE / MERGE | `pgfmt/parser/dml.py` + `pgfmt/formatter/dml.py` |
| CREATE*, ALTER, utility statements, DO | `pgfmt/parser/ddl.py` + `pgfmt/formatter/ddl.py` |
| statement loop, comment safety nets, error fallback | `pgfmt/parser/base.py` + `pgfmt/formatter/base.py` |
| exact-output regression cases | `tests/cases/syntax.py` (comment cases: `tests/cases/comment_*.py`) |

## Key Documentation

- [docs/CHANGELOG.md](docs/CHANGELOG.md) — All fix history and version changes
- [docs/known-issues.md](docs/known-issues.md) — Known issues, limitations, and improvements
- [docs/architecture.md](docs/architecture.md) — Internal architecture and test pipeline

## Formatting Style Rules

These rules define the formatter's output. Follow them exactly when modifying formatter behavior.

- **Indentation**: 4 spaces
- **Major clauses** (SELECT, FROM, WHERE, etc.): left-aligned on their own line
- **Column lists**: indented under clause, leading comma style (`, column`)
- **Comma-separated FROM tables**: each table on its own line, indented under FROM, with leading comma style (`, table_b`)
- **JOINs**: indented under FROM, ON conditions double-indented
- **AND/OR in ON conditions**: each on new line, double-indented under the JOIN
- **AND/OR in WHERE**: each on new line, indented under WHERE
- **CASE expressions**: WHEN/ELSE indented, THEN result on next line further indented
- **Subqueries**: wrapped in parens with increased indent level; AND/OR inlined in subquery WHERE/HAVING clauses, unless the inlined line would exceed `INLINE_WHERE_MAX_CHARS` (100 chars including indentation), in which case each AND/OR condition breaks onto its own line like a top-level WHERE clause
- **CREATE TABLE ... AS SELECT**: table name indented under CREATE TABLE, entire SELECT block indented one level
- **IN (...) lists**: expanded one per line with leading commas when more than 3 values; `IN (SELECT ...)` formats the subquery indented inside the parens
- **Keywords**: uppercased during formatting
- **Identifiers**: preserved as lowercase (common column names like `name`, `value`, `type` are intentionally excluded from the keyword list)
- **Cast operator** (`::`) : no spaces, type uppercased (e.g., `col::TEXT`)
- **psql variables** (`:var`, `:'var'`, `:"var"`): tokenized as a single unit and preserved as-is (e.g., `:my_var`, `:my_var::INT`)
- **Comments**: inline trailing comments (`--`) tab-aligned; standalone `--` comments on their own indented line within clauses; block comments (`/* */`) kept inline with the item they precede; the first comment after an expression is always treated as trailing (positional info is lost during tokenization)
- **Statement separation**: 3 blank lines between code blocks
- **Comment groups**: comments directly before a statement attach to it; blank lines in original source between comment groups are preserved as 3-blank-line gaps
- **Header comment blocks**: 3 blank lines before the first SQL statement when separated by blank lines in the original
- **ON CONFLICT**: `DO NOTHING` stays on the `ON CONFLICT` line; `DO UPDATE` puts `SET` / `WHERE` on their own lines like an `UPDATE`
- **Sign operators**: unary `-` / `+` are tight (`-a`); `*` in infix position is multiplication (`a * b`)
- **Row-locking clauses**: `FOR UPDATE [OF t] [NOWAIT | SKIP LOCKED]` on its own line after `LIMIT`/`OFFSET`, lock words uppercased
- **Utility statements** (ALTER, DROP, TRUNCATE, GRANT, COPY, SET, BEGIN/COMMIT/ROLLBACK, CREATE FUNCTION/TRIGGER/..., VACUUM, ...): one line, keywords uppercased, object names as written; `ALTER TABLE` with several actions puts one per line with leading commas
- **psql meta-commands** (`\echo`, `\set`, ...): kept verbatim on their own line; consecutive meta lines stay tight, `SELECT ... \gset` stays attached to its statement
- **Comments are never lost**: if a statement formatter doesn't render a comment it is re-emitted above the statement (`_rescue_lost_comments`); a `;` is never written onto a line that ends in a `--` comment (`_semi()`)
- **Operators**: lexed like PostgreSQL (longest run of operator chars), so custom operators (`<->`, `<<=`, `===`, `|/`) are never split; unknown infix operators get the "any other operator" precedence
- **Adjacent string literals** (`'a'` newline `'b'`): kept as one continued literal, one piece per line
- **CREATE OPERATOR / AGGREGATE / COLLATION definition lists**: one `KEY = value` per line, leading commas, `)` on its own line
- **Identifier case**: unquoted names are case-folded on ASCII letters only, as PostgreSQL does (`ascii_lower` / `ascii_upper` in `pgfmt/tokenizer.py`); a name containing non-ASCII characters is kept exactly as written. Never use `str.lower()` / `str.upper()` on an identifier: `DESCRIÇÃO` and `descrição` are different names
- **Safety net**: after formatting, each statement's significant tokens (case-folded, no whitespace/comments/`AS`) must equal its source's, otherwise the statement is emitted exactly as written (`_same_tokens` in `pgfmt/formatter/base.py`). Never weaken it to make a test pass: a hit means a formatter bug (or invalid input such as `SELECT a, FROM t`, which must not be silently repaired)
- **Unparseable statements** (invalid SQL, template placeholders like `<<PASTE_HERE>>`): kept verbatim up to their `;`; the rest of the file is still formatted
- **Bare fragments** (`CASE ... END AS x`, `func(...)` with no statement around them): formatted like a select list at column 0
- **Supported statements**: SELECT, INSERT, UPDATE, DELETE, MERGE, EXPLAIN, CREATE VIEW / MATERIALIZED VIEW, SELECT ... INTO, data-modifying CTEs, WINDOW clause, CREATE TABLE ... AS SELECT, WITH/CTE, DO blocks
