# Known Issues & Potential Improvements

No open issues at this time.

All 9 findings from the 2026-04-07 code review have been resolved — see [CHANGELOG.md](CHANGELOG.md) for details.

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
