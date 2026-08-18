# Known Issues & Potential Improvements

No open issues at this time.

All 9 findings from the 2026-04-07 code review have been resolved — see [CHANGELOG.md](CHANGELOG.md) for details.

---

## Comment handling — remaining gaps

Most clause-boundary comment loss was fixed 2026-08-18 (SELECT-list, WHERE/HAVING
leading and trailing, JOIN...ON trailing, comments before GROUP BY/HAVING/ORDER BY).
A few narrower cases are still silently dropped, deliberately left out of that fix
to keep it scoped:

- A standalone comment on its own line between a table/JOIN and the next JOIN
  keyword in a `FROM` clause (e.g. `FROM t\n-- note\nJOIN u ON ...`) is discarded
  (`parse_from_clause`).
- A standalone comment between a joined table and its `ON` keyword
  (e.g. `JOIN u p\n-- note\nON ...`) is discarded (`parse_join`).
- A leading comment on the very first SELECT-list item (right after `SELECT`,
  before the first column) is discarded (`parse_select_list` / `parse_select`).
- `UPDATE`/`DELETE` statements' `WHERE` clauses don't get the same
  leading/trailing comment preservation as `SELECT`'s `WHERE` — they still use
  the older `skip_blanks_and_comments()` discard.

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
