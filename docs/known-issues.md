# Known Issues & Potential Improvements

Last reviewed: 2026-04-07.

All issues from the initial code review have been resolved.

---

## Resolved Issues

| ID | Type | What was fixed |
|----|------|---------------|
| BUG-1 | Bug | `BETWEEN...AND` no longer breaks when a comment separates them. The outer AND handler now leaves `between=True` so the expression collector consumes AND as a regular token. |
| PERF-1 | Performance | `_last_line()` now searches `self.out` in reverse instead of joining the entire output — O(k) per call instead of O(n). |
| INCON-1 | Inconsistency | `format_delete` now uses `INDENT` (4 spaces) via `self.nl()` instead of hardcoded `\t`. |
| FEAT-1 | Feature | `EXCEPT`, `EXCEPT ALL`, `INTERSECT`, and `INTERSECT ALL` are now supported as set operators, same as `UNION`/`UNION ALL`. Added to keywords and all boundary checks. |
| FRAG-1 | Fragile code | Alias detection exclusion list in `format_table_ref` expanded to include `NOT`, `OFFSET`, `FETCH`, `UNION`, `EXCEPT`, `INTERSECT`, `RETURNING`, `LATERAL`, `INTO`. |
| FRAG-2 | Fragile code | `check_on_has_and` now explicitly skips `COMMENT` and `BLANK_LINE` tokens instead of relying on them not matching any keyword. |
| EDGE-1 | Edge case | `_collect_in_values` now detects `(SELECT ...)` subqueries within mixed value lists and collects them as complete value groups with balanced parens. |
| EDGE-2 | Edge case | N/A — only affects malformed SQL, and `format_sql` already returns original SQL on error. Accepted as-is. |
| EDGE-3 | Cosmetic | `join_expr` now uses a regular space before `/* */` block comments and tab-alignment only for `--` line comments. |

---

## Remaining Limitations

These are architectural limitations, not bugs. They represent unsupported SQL features that fall through to `format_raw_statement()`:

- `CREATE TABLE (col TYPE, ...)` — only `CREATE TABLE ... AS SELECT` is formatted
- `ALTER TABLE`, `DROP TABLE`, `CREATE INDEX`, `CREATE VIEW` — no dedicated formatters
- `MERGE` — not recognized
- `WINDOW` clause — tokens collected inline, no special formatting
- `GROUPING SETS / CUBE / ROLLUP` — not handled specially
- `MATERIALIZED` CTEs — `WITH x AS MATERIALIZED (...)` not recognized
- `ARRAY[...]` syntax — brackets are `SYM` tokens, commas treated as list separators
- PL/pgSQL inside `DO` blocks — passed through verbatim
- `COPY`, `VACUUM`, `EXPLAIN` — not recognized
