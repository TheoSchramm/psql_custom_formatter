# Changelog

All notable changes to this project are documented in this file.
Entries are in reverse chronological order.

---

## 2026-06-18 — Refactor: tokenize → parse (AST) → format pipeline

- **Architecture overhaul**: replaced the monolithic streaming `Formatter` class with a proper three-layer pipeline: `tokenize() → Parser → ASTFormatter`.
- **`Parser` class** (recursive-descent + Pratt expression parser): converts the token list into typed AST nodes. Each SQL construct is now a `@dataclass` with named fields (`SelectStatement`, `JoinClause`, `BinaryOp`, `CaseExpr`, `InExpr`, `BetweenExpr`, `FunctionCall`, `WindowSpec`, etc.). The parser handles all 8 supported statement types plus CTEs, subqueries, window functions, and `FROM (VALUES ...)`.
- **`ASTFormatter` class**: walks the AST and produces formatted output. Formatting decisions are now structurally driven — `AND`/`OR` line-breaking walks a `BinaryOp` tree via `_flatten_conditions()`, `IN` list expansion reads `len(InExpr.values)`, subquery detection checks `TableRef.subquery is not None`, and `BETWEEN…AND` is a `BetweenExpr` node (no special-casing in the AND handler).
- **Eliminated heuristics** that were fragile and hard to maintain:
  - `check_on_has_and()` — replaced by `isinstance(on_condition, BinaryOp)`
  - `_on_paren_is_wrapper()` — replaced by `SubqueryExpr` vs `Parenthesized` node types
  - `_lookahead_has_select_in_parens()` / `_lookahead_has_values_in_parens()` — replaced by `TableRef.subquery` / `TableRef.values` fields
  - `_collect_in_values()` — replaced by `InExpr.values` / `InExpr.subquery`
  - `_collect_case_expr()` — replaced by `CaseExpr.branches` list
  - `between_depth` counter — replaced by `BetweenExpr` structural node
  - `paren_depth` tracking in `format_conditions` — implicit in AST nesting
  - Alias-detection exclusion list in `format_table_ref` — replaced by `alias` field on `TableRef`
- **No behavior changes**: all 75 tests continue to pass; fixture regression is identical.
- **File size**: grew from 1,935 to 2,681 lines.

---

## 2026-06-09 — Expand ANY (ARRAY[...]) values across multiple lines

- **Enhancement**: `ANY (ARRAY[val1, val2, ...])` expressions with more than 3 values are now expanded one value per line using leading-comma style, consistent with `IN (...)` list expansion.
- **Implementation**: added `_collect_bracket_values()` to collect comma-separated tokens inside `[...]`, `format_array_expanded()` to write the expanded layout, and a detection block in the WHERE expression collector that looks ahead for the `ANY ( ARRAY [` token sequence before consuming it.
- **Output style**: the `ARRAY[` opens on the same line as `ANY (`, values are indented at `ci + 1`, and `])` closes at the base indent level `ci`.
- **Test**: idempotency and round-trip verified; all 75 tests pass.

---

## 2026-06-09 — Fix simple CASE in UPDATE SET collapsing to one line

- **Bug fix**: `CASE expr WHEN val THEN result ... END` in an `UPDATE SET` assignment was collapsed to a single line instead of being expanded with `WHEN`/`ELSE`/`END` each on their own indented line.
- **Root cause**: `format_set_clause` used `collect_until` to consume the entire right-hand side of each assignment as a flat token list. It had no special handling for `CASE`, so the `CASE ... END` block was passed to `join_expr` and written inline.
- **Fix**: the `collect_until` stop predicate in `format_set_clause` now also stops at a top-level `CASE` token. When the token after the collected LHS is `CASE`, `format_case(1)` is called directly, giving the same multi-line `WHEN`/`ELSE`/`END` expansion that `SELECT` items already produce. Both simple-CASE (`CASE expr WHEN ...`) and searched-CASE (`CASE WHEN condition ...`) forms are handled correctly.
- **Test**: added edge case TEST 24.

---

## 2026-05-29 — Add ILIKE, ANY, ARRAY to keyword uppercase list

- **Enhancement**: `ILIKE`, `ANY`, and `ARRAY` are now uppercased during formatting, consistent with other SQL operators and keywords.
- **Change**: added all three to the `KEYWORDS` set in `psql_custom_formatter.py`. No structural formatting changes — only casing is affected.

---

## 2026-05-20 — Add FROM (VALUES ...) AS alias(cols) support

- **New feature**: `FROM (VALUES (...), ...) AS alias(col1, col2)` table constructors are now formatted correctly. Previously the formatter treated any parenthesized `FROM` expression as a subquery, unconditionally calling `format_select()` on the contents. `VALUES` was misread as a SELECT column list, the column-list alias `(col1, col2)` was orphaned, and subsequent `JOIN`/`WHERE` clauses collapsed onto a single line.
- **Fix**: added `_lookahead_has_values_in_parens()` (parallel to the existing `_lookahead_has_select_in_parens()`). `format_from_subquery()` now branches on this check before writing anything. The new `format_from_values()` method handles `VALUES` subqueries: it emits `(\nVALUES` at the current indent level, formats each row tuple at the next indent level with leading-comma style, writes the closing `)`, and then consumes the `AS alias(cols)` column-list alias.
- **Output style**: consistent with the existing `(SELECT ...)` subquery layout — opening `(` on the `FROM` line, content indented, closing `) AS alias(cols)` at the FROM indent level.

---

## 2026-05-18 — Fix CREATE TABLE AS WITH producing spurious blank lines

- **Bug fix**: `CREATE TABLE ... AS WITH cte AS (...) SELECT ...` emitted 3 blank lines between the `AS` keyword and `WITH`. `format_create` only checked for `SELECT` after consuming `AS` and returned without consuming `WITH`, so the main `format()` loop picked it up as a new top-level statement (inserting the inter-statement separator).
- **Fix**: added a `WITH` branch in `format_create` immediately after the `AS` block. When the token after `AS` is `WITH`, it writes a single newline and delegates to `format_with()`, which handles the entire CTE + SELECT + `;` chain.

---

## 2026-05-18 — Fix standalone comment before semicolon being merged with last expression

- **Bug fix**: A `--` comment on its own line immediately before the statement terminator `;` was being incorrectly consumed as a trailing inline comment on the last expression. The comment was tab-aligned onto the same line as the preceding AND condition, and the `;` was then appended immediately after it with no newline, producing e.g. `AND expr\t-- comment;`.
- **Root cause**: `format_on_conditions` and `format_conditions` both had an unconditional "trailing inline comment" grab after each expression that ignored the `tok_preceded_by_newline` flag on COMMENT tokens.
- **Fix 1**: `format_on_conditions` — when the comment after an expression is standalone (`tok_preceded_by_newline = True`) and precedes a boundary (`is_on_boundary`, `)`, or JOIN), all pending comments are output at `ci` indentation and the ON-conditions loop breaks cleanly.
- **Fix 2**: `format_conditions` — standalone comments after an expression are left unconsumed so the loop's own COMMENT handler (which already checks for boundary and uses `self.nl(ci)`) processes them correctly.
- **Fix 3**: `format_select` — before writing `;`, detects if the last output line is a comment and inserts a `\n` so the semicolon lands on its own line rather than being appended to the comment text.

---

## 2026-05-14 — Fix trailing inline comment on JOIN ON line merged with expression

- **Bug fix**: A `--` comment placed on the same line as `ON` (e.g. `JOIN t ap ON -- comment`) was being concatenated directly with the ON condition expression. The comment fell through to `format_on_conditions`, which wrote it with tab-alignment but emitted no newline before the next expression, producing a fused line like `\t\t-- commentregexp_replace(...)`.
- **Fix**: `format_join` now intercepts an inline trailing comment (COMMENT token with `preceded_by_newline = False`) immediately after the `ON` keyword, writes it tab-aligned on the `ON` line, then proceeds with the normal newline and `format_on_conditions` call.

---

## 2026-04-23 — Fix ON condition mangling with parenthesized function expressions

- **Bug fix**: `JOIN ... ON (func(col, pat))[1]::int = ...` was being mangled — the formatter incorrectly treated the leading `(` as a syntactic wrapper around the entire ON condition, consumed it, then stopped collecting tokens at the first `)` at depth 0 (which was actually the close of the function call's outer paren). Everything after — the subscript `[1]`, the cast, and the right-hand side — was orphaned on its own line with spurious blank lines.
- **Fix**: added `_on_paren_is_wrapper()` lookahead method. Before consuming a leading `(` after `ON`, it scans forward to the matching `)` and checks what follows. Only if the next token is `AND`/`OR`, a clause boundary, or a JOIN keyword is the `(` treated as a wrapper; otherwise it's left as part of the expression.

---

## 2026-04-20 — psql Variable Template Support

- **psql `:variable` syntax**: tokenizer now recognizes `:ident`, `:'quoted'`, and `:"quoted"` as single tokens. Previously the colon was emitted as a bare `SYM` and the identifier as a separate token, producing `SELECT : my_var` instead of `SELECT :my_var`. Combinations like `:x::INT` (variable + cast) also work correctly.

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
