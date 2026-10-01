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

## Word operators that are still mangled

Found 2026-10-01 while auditing context-dependent tokens. These are multi-word or
bare-word operators the expression parser does not know, so the words are
mistaken for aliases or clause boundaries and the SQL is **changed**, not just
left unformatted (same class of bug as `SIMILAR TO`, which is now handled):

- `ts AT TIME ZONE 'UTC'` → `ts AS at`, `time AS zone`, `'UTC'` (three columns)
- `a COLLATE "C"` → `a AS collate`, `"C"`
- `b ISNULL` / `b NOTNULL` → breaks out of the WHERE clause (3 blank lines)
- `c OVERLAPS d` → breaks out of the WHERE clause

Each needs an infix/postfix branch in `parse_expression` like
`_at_similar_to`.

## psql meta-commands (`\echo`, `\set`, ...) are not supported

The tokenizer has no concept of a backslash command, so `\` becomes a bare
`SYM` token and the rest of the line is treated as SQL. Worse, a meta-command
followed by a trailing `--` comment is glued onto *one line* with the comment,
which can comment out real code after it. Reproduction (pre-existing, not
caused by any recent change):

```sql
\echo '=== QUERY PLAN ==='
-- note
ROLLBACK;
```

formats to `\ echo '=== QUERY PLAN ==='	-- note	; rollback ;`, i.e. the
`ROLLBACK` ends up inside the comment. Found while comparing old vs. new output
over a folder of real scripts (`pg_otimization/tools/quick_compare.sql`). Fix idea:
treat a line starting with `\` as an opaque one-line statement and emit it
verbatim on its own line.

Related: bare transaction statements (`BEGIN`, `ROLLBACK`, `COMMIT`) take the
raw-statement path and come out lowercase with a space before the `;`
(`rollback ;`).

## Remaining Limitations

These are architectural limitations, not bugs. They represent unsupported SQL features that fall through to `format_raw_statement()`:

- `CREATE TABLE (col TYPE, ...)` — only `CREATE TABLE ... AS SELECT` is formatted
- `ALTER TABLE`, `DROP TABLE`, `CREATE INDEX`, `CREATE VIEW` — no dedicated formatters
- `MERGE` — not recognized
- `WINDOW` clause — tokens collected inline, no special formatting
- `GROUPING SETS / CUBE / ROLLUP` — not handled specially
- PL/pgSQL inside `DO` blocks — passed through verbatim
- `COPY`, `VACUUM`, `EXPLAIN` — not recognized
