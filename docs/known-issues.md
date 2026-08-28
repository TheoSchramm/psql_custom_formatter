# Known Issues & Potential Improvements

No open issues at this time.

All 9 findings from the 2026-04-07 code review have been resolved — see [CHANGELOG.md](CHANGELOG.md) for details.

---

## Comment handling — remaining gaps

Most clause-boundary comment loss was fixed 2026-08-18 (SELECT-list, WHERE/HAVING
leading and trailing, JOIN...ON trailing, comments before GROUP BY/HAVING/ORDER BY)
and 2026-08-28 (WHERE/HAVING leading comments rendering before the keyword instead
of after it, `UPDATE` SET-clause and WHERE-clause comments, JOIN...ON leading
comments, INSERT/RETURNING column-list indentation — see CHANGELOG.md). A few
narrower cases are still silently dropped, deliberately left out of those fixes
to keep them scoped:

- A standalone comment on its own line between a table/JOIN and the next JOIN
  keyword in a `FROM` clause (e.g. `FROM t\n-- note\nJOIN u ON ...`) is discarded
  (`parse_from_clause`).
- A standalone comment between a joined table and its `ON` keyword
  (e.g. `JOIN u p\n-- note\nON ...`) is discarded (`parse_join`). Note this is
  distinct from the comment-after-`ON` case, which is now preserved.
- A leading comment on the very first SELECT-list item (right after `SELECT`,
  before the first column) is discarded (`parse_select_list` / `parse_select`).
- `DELETE`'s `WHERE` clause is parsed as raw tokens (not a structured
  expression), so it doesn't get the same leading/trailing comment handling as
  `SELECT`/`UPDATE`'s `WHERE` — a comment there survives (raw tokens aren't
  dropped) but may not land on its own line the way a structured WHERE's does.

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
