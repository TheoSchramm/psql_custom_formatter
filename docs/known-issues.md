# Known Issues & Potential Improvements

No open correctness bugs are known as of 2026-10-01. Every item that used to be
listed here (comment-handling gaps, word operators, psql meta-commands,
`CREATE VIEW` / `MERGE` / `COPY` / `EXPLAIN` / `WINDOW` and the other "limitations")
was fixed — see [CHANGELOG.md](CHANGELOG.md) for details.

What remains below is either **intentional** or a **cosmetic/coverage limit**:
none of it changes the meaning of your SQL or drops any of its text.

---

## Safety nets (so nothing is ever silently lost)

- **Comments are never dropped.** Each statement remembers the comments in its
  source; if the statement formatter did not render one of them, it is re-emitted on
  its own line above the statement (`ASTFormatter._rescue_lost_comments`). The test
  suite additionally checks that every edge case keeps all of its comments.
  Comments in unusual positions (e.g. inside a function-call argument list) may be
  relocated this way instead of staying exactly where they were.
- **A `--` comment can never swallow code.** `join_expr` starts a new line after a
  line comment, and statement terminators go through `ASTFormatter._semi()`, which
  moves a `;` onto its own line when the current line ends in a comment.
- **Unparseable input is returned unchanged.** `format_sql()` returns the original
  text if any statement raises, rather than emit a mangled best-effort parse.

## By design

- **PL/pgSQL inside `DO` blocks and `CREATE FUNCTION` bodies is passed through
  verbatim.** To SQL the body is an opaque string literal; reformatting it would risk
  changing things like `RAISE` format strings. Only the envelope is formatted
  (`DO [LANGUAGE x] $$ ... $$ [LANGUAGE x];`).
- **Table aliases are written without `AS`** (`FROM t x`), as before; column aliases keep it.
- **psql meta-commands are kept verbatim** on their own line (`\echo`, `\set`, ...).
  A meta-command written after a statement on the same line (`SELECT ... \gset`) stays
  attached to that statement.

## Limitations

- **Statements without a terminating semicolon.** Short one-liners (transaction
  control, `SET`, `DROP`, `TRUNCATE`, ...) end at the next DML keyword, so
  `ROLLBACK\nSELECT 1` still splits. Other utility statements (`ALTER`, `GRANT`,
  `COPY`, `CREATE FUNCTION`, ...) need their `;` to be separated from what follows,
  and `SELECT 1\nROLLBACK` reads `ROLLBACK` as a column alias — both are ambiguous
  without a semicolon.
- **`COPY ... FROM stdin` data rows** (the lines up to `\.`) are not recognised.
- **Utility statements are rendered on one line** (keywords uppercased), except
  `ALTER TABLE` with several actions (one action per line). No further structure is
  applied to `GRANT`, `CREATE FUNCTION`, `CREATE TRIGGER`, `CREATE SEQUENCE`, etc.
  Keyword uppercasing there is word-based: an unquoted identifier that happens to
  equal a keyword may be uppercased in an unusual position — harmless, since
  unquoted identifiers are case-insensitive in PostgreSQL.
- **`INSERT ... VALUES` rows are kept as raw tokens.** A comment inside a row is
  preserved (and can no longer comment out the rest of the row) but the row is not
  re-indented around it.
- **`CREATE TABLE`**: column definitions are aligned and table constraints are moved
  after the columns; `GENERATED`, `REFERENCES`, `CHECK`, ... clauses are kept as
  written (keywords uppercased) rather than structurally re-laid-out.
- **`MERGE`** supports `UPDATE`, `DELETE`, `INSERT` and `DO NOTHING` actions and
  `RETURNING`; `OVERRIDING ...` clauses in the `INSERT` action are not recognised.
- **Window functions**: frame clauses (`ROWS/RANGE/GROUPS BETWEEN ...`) are kept as
  written with keywords uppercased, not re-laid-out.
