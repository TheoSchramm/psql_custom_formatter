# Changelog

All notable changes to this project are documented in this file.
Entries are in reverse chronological order.

---

## 2026-04-07 — Known Issues Fixed, Project Restructure & Sanitization

### All 9 known issues from code review resolved

- **BUG-1**: `BETWEEN...AND` no longer breaks when a comment separates
  them. The outer AND handler now leaves `between=True` so the expression
  collector consumes AND as a regular token.
- **PERF-1**: `_last_line()` now searches `self.out` in reverse — O(k)
  per call instead of O(n).
- **INCON-1**: `format_delete` now uses `INDENT` (4 spaces) via
  `self.nl()` instead of hardcoded `\t`.
- **FEAT-1**: `EXCEPT`, `EXCEPT ALL`, `INTERSECT`, and `INTERSECT ALL`
  are now supported as set operators. Added to keywords and all boundary
  checks throughout the formatter.
- **FRAG-1**: Alias detection exclusion list in `format_table_ref`
  expanded with `NOT`, `OFFSET`, `FETCH`, `UNION`, `EXCEPT`, `INTERSECT`,
  `RETURNING`, `LATERAL`, `INTO`.
- **FRAG-2**: `check_on_has_and` now explicitly skips `COMMENT` and
  `BLANK_LINE` tokens instead of relying on them not matching keywords.
- **EDGE-1**: `_collect_in_values` now detects `(SELECT ...)` subqueries
  within mixed value lists and collects them as complete value groups.
- **EDGE-2**: Accepted as-is — only affects malformed SQL, and
  `format_sql` already returns original SQL on error.
- **EDGE-3**: `join_expr` now uses a regular space before `/* */` block
  comments and tab-alignment only for `--` line comments.

`docs/known-issues.md` removed — all issues resolved.

### Renamed project from `pg_custom_formatter` to `psql_custom_formatter`

### Renamed project from `pg_custom_formatter` to `psql_custom_formatter`

Renamed the Python file, GitHub repository, local directory, and all
internal references across documentation and test runner.

### Folder structure reorganized

- Test fixtures (`example.sql`, `example_formatted.sql`) moved from
  `examples/` to `tests/fixtures/` as `input.sql` and `expected.sql`
- `examples/plain_sql/test_N.sql` flattened into `examples/` with
  descriptive names (`select_join_where.sql`, `create_and_update.sql`, etc.)
- `KNOWN_ISSUES.md` and `tests/TEST_DOCUMENTATION.md` moved to `docs/`
  as `known-issues.md` and `architecture.md`
- `fixes.md` deleted — content merged into `CHANGELOG.md`

### Documentation consolidated

Each `.md` file now has a single, non-overlapping responsibility:
- `README.md` — public-facing intro, usage, examples
- `CLAUDE.md` — AI assistant instructions, formatting rules
- `CHANGELOG.md` — all fix history (absorbed `fixes.md`)
- `docs/architecture.md` — internal architecture and test pipeline
- `docs/known-issues.md` — open bugs and improvements

Removed ~950 lines of duplicated content across files. Cross-references
replace duplicated sections.

### Sensitive data sanitized from all SQL files

Replaced production-specific identifiers with generic names:
- `erp.*`, `store.*`, `app.*`, `staging.*` schemas → `public.*`
- Company names, person names, email addresses, CPF numbers removed
- Real protocol/ticket IDs, login names, contract numbers replaced
- Git history rewritten to remove all prior versions containing
  sensitive data

### Code review findings documented

Created `docs/known-issues.md` with 9 findings from code review:
- BUG-1: `BETWEEN...AND` broken when comment separates them
- PERF-1: `_last_line()` O(n^2) performance
- INCON-1: DELETE uses `\t` instead of `INDENT`
- FEAT-1: No `EXCEPT`/`INTERSECT` support
- FRAG-1: Alias detection keyword exclusion list
- FRAG-2: `check_on_has_and` doesn't skip comments/blanks
- EDGE-1: Nested SELECT inside IN value list
- EDGE-2: Paren depth tracking with malformed SQL
- EDGE-3: Block comments tab-separated in `join_expr`

---

## 2026-04-06 — Comment Handling & Comma-Separated FROM

### Comment Handling Overhaul

Comprehensive rework of how comments interact with SELECT lists, JOIN/ON
clauses, and WHERE conditions. Previously, comments in these positions
caused token fusion, clause collapse, and idempotency failures (TEST 13).

**Standalone line comments in SELECT lists fused with identifiers**:
`format_select_list` now detects standalone `--` comments before items,
emits them on their own indented line, and tracks a `need_nl` flag.

**Block comments in SELECT lists fused with next token**:
`format_select_item`'s `collect_until` now only stops on `--` line
comments, not `/* */` block comments.

**Post-comma block comments treated as trailing comments**:
The post-comma trailing comment handler now only matches `--` line
comments, letting block comments pass through to the next item.

**Comments between JOIN table ref and ON caused collapse**:
`format_join` now handles trailing and standalone comments between the
table reference and `ON`. When comments precede ON, it renders ON on a
new line with multi-line condition layout forced.

**Comments in ON conditions absorbed into token list**:
`format_on_conditions` now breaks the expression collector on COMMENT
tokens, emits the first comment as trailing, and checks whether
subsequent comments precede a clause boundary before consuming them.

**Comments before clause boundaries consumed as trailing**:
The trailing comment handler in `format_conditions` now always consumes
the first comment after an expression as trailing. The standalone comment
handler checks whether subsequent comments precede clause boundaries and
breaks instead of consuming them.

**Comments in WHERE before first condition fused**:
`format_conditions` now emits a newline before the next expression when
`after_comment` is True.

### Test Runner Fix

`check_keywords_uppercased` was flagging words inside `/* */` block
comments. The regex cleaning step now strips block comments before
scanning for keywords.

### Formatter Fixes

**Comma-separated tables in FROM not handled**:
`FROM users a, orders b` was broken — the second table produced a spurious
3-blank-line gap and the WHERE clause collapsed. `format_from_clause` now
checks for comma tokens in its main loop and formats each additional table
on its own line with leading comma style. Subqueries in comma-separated
positions are also handled.

### Internal

- Added `_is_join_at(off)` helper for boundary detection in comment
  handlers. `is_join()` now delegates to `_is_join_at(0)`.

---

## 2026-03-23 — Edge Case Hardening

### Tokenizer Fixes

**E-string literals (`E'...'`) broken by space insertion**:
`E'\n'` was tokenized as keyword `E` + string `'\n'`. The tokenizer now
detects `E'`/`e'` prefixes and keeps the entire literal as one STR token.

**JSON operators (`->`, `->>`) split into separate characters**:
Added `->>` (3-char) and `->`, `#>` (2-char) to the operator tokenizer.

### Formatter Fixes

**LATERAL JOIN not recognized**:
Added `LATERAL` to the keyword set. `format_join` now consumes it after
`JOIN`.

**Subquery in JOIN position not formatted**:
`format_join` now detects `(SELECT ...)` after JOIN and delegates to
`format_from_subquery`.

**ON CONFLICT DO UPDATE mangled after UNION ALL**:
Added `ON CONFLICT` as a compound boundary in `format_item_list` and its
`collect_until` lambda. Also added `RETURNING`.

**Comments between clauses caused catastrophic collapse**:
Added `_skip_inter_clause()` helper that outputs standalone comments
properly while skipping between clauses.

**Blank lines in input causing broken output**:
Added `_skip_blank_lines()` calls before each clause check in
`format_select`, and blank-line skipping in `format_from_clause`,
`format_conditions`, and `format_item_list`.

**Commas inside function arguments had unwanted leading space**:
`join_expr` now suppresses the space before COMMA tokens.

**Nested CASE expressions mangled output**:
`format_case` now recursively calls itself when encountering a nested CASE.

**CASE expression in WHERE broke AND/OR parsing**:
The expression collector now tracks `case_depth` to avoid splitting on
AND/OR inside CASE.

**ON CONFLICT clause absorbed into WHERE**:
`format_conditions` now recognizes `ON CONFLICT` and `RETURNING` as
boundary keywords.

**OFFSET clause not handled**:
`format_select` now handles OFFSET and `FETCH FIRST/NEXT ... ONLY`.

### Internal

- Added `_skip_blank_lines()` and `_skip_inter_clause()` helpers.
- Added `_lookahead_has_select_in_parens()` for subquery detection in JOINs.
- Added `first_cond` tracking after expression output in `format_conditions`.
- Added `LATERAL` to keyword set.
- Added `->>`, `->`, `#>` to tokenizer operator list.
- Added E-string prefix detection to tokenizer.

---

## Pre-2026-03-23 — Initial Development

### Bug Fixes

**Fix 1 — Inline comments after commas swallow next column**:
After eating a COMMA in `format_select_list` and `format_item_list`, check
if the next token is a COMMENT and write it tab-aligned before the newline.

**Fix 2 — Comments between statements collapsed into ORDER BY**:
Added missing break conditions (`INSERT`, `UPDATE`, `DELETE`, `CREATE`,
`COMMENT`, `BLANK_LINE`). Added comment group handling in `format()`.

**Fix 3 — INSERT INTO was a stub**:
Rewrote `format_insert` with column list formatting, SELECT/VALUES
delegation, ON CONFLICT and RETURNING support.

**Fix 4 — Comment spacing between code blocks**:
Restructured `format()` to emit the 3-blank-line separator before comment
groups. Comments directly preceding a statement attach to it.

**Fix 5 — Comment groups not preserved across blank lines**:
Added `BLANK_LINE` token to the tokenizer. `format()` uses these to split
comments into separate groups, preserving original spacing.

**Fix 6 — Standalone comments in WHERE consumed as statement boundaries**:
`format_conditions` now breaks on `BLANK_LINE`. Standalone comments go on
their own indented line.

**Fix 7 — Standalone comments in SET clause placed inline**:
SET clause comments are now written on their own indented line.

**Fix 8 — UPDATE FROM clause not formatted**:
`format_update` now handles `FROM` clause after SET plus `RETURNING`.

**Fix 9 — CREATE TABLE ... AS SELECT not handled**:
Added `format_create` handler for `CREATE TABLE schema.name AS SELECT`.

**Fix 10 — Standalone comments in WHERE tab-aligned instead of indented**:
Standalone comments now use normal indentation (`nl(ci)`). A `first_cond`
flag prevents extra blank lines when comment is first thing after WHERE.

**Fix 11 — IN (SELECT ...) subquery collapsed to one line**:
Before calling `_collect_in_values`, check if token after `(` is `SELECT`.
If so, delegate to `format_select` with `is_subquery=True`.

### Formatting Enhancements

**Cast operator (`::`)**: No spaces, type uppercased: `value::TYPE`.

**ON conditions with AND/OR**: Multi-line layout with double indentation.

**IN (...) list expansion**: Auto-expand to one-per-line when >3 values.

**CREATE TABLE ... AS SELECT**: Table name and SELECT block indented.

**Subquery `is_subquery` flag refactor**: Now an explicit parameter on
`format_select`, only set to `True` for actual subqueries.
