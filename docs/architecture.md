# Architecture & Test Pipeline — psql_custom_formatter

This document covers the formatter's internal architecture and test pipeline.

For fix history, see [CHANGELOG.md](CHANGELOG.md).
For known issues and limitations, see [known-issues.md](known-issues.md).
For formatting rules, see [CLAUDE.md](../CLAUDE.md).

---

## 1. Formatter Architecture

### Overview

The formatter is a single-file Python program (`psql_custom_formatter.py`) with no external dependencies. It follows a three-stage pipeline:

```
Raw SQL string --> tokenize() --> Formatter class --> Formatted SQL string
```

The public entry point is `format_sql(sql)`, which wraps the pipeline in a try/except and returns the original SQL unchanged if any error occurs.

### Tokenizer

`tokenize(sql)` scans the raw SQL character-by-character and produces a flat list of `(type, value)` tuples. Token types:

| Token Type    | Description                                      | Example Value         |
|---------------|--------------------------------------------------|-----------------------|
| `KW`          | SQL keyword (uppercased)                         | `SELECT`, `FROM`      |
| `ID`          | Identifier (lowercased)                          | `table1`, `col_name`  |
| `QUOTED_ID`   | Double-quoted identifier                         | `"MyTable"`           |
| `STR`         | String literal (single-quoted)                   | `'hello'`             |
| `NUM`         | Numeric literal                                  | `42`, `3.14`          |
| `COMMENT`     | Single-line `--` or block `/* */` comment        | `-- note`             |
| `BLANK_LINE`  | Two or more consecutive newlines in source        | (empty string)        |
| `COMMA`       | `,`                                              | `,`                   |
| `SEMI`        | `;`                                              | `;`                   |
| `LPAR`        | `(`                                              | `(`                   |
| `RPAR`        | `)`                                              | `)`                   |
| `DOT`         | `.`                                              | `.`                   |
| `STAR`        | `*`                                              | `*`                   |
| `OP`          | Operators: `<=`, `>=`, `<>`, `!=`, `::`, `+`, etc. | `::`               |
| `WORD`        | psql variable: `:ident`, `:'quoted'`, `:"quoted"`  | `:my_var`          |
| `DOLLAR_BODY` | Dollar-quoted block (`$$...$$` or `$tag$...$tag$`) | `$$BEGIN ... END$$` |
| `SYM`         | Any other single character                       | `@`, `#`              |

Key tokenizer behaviors:

- Words matching `KEYWORDS` are emitted as `KW` tokens **unless** the lowercase form is in `IDENTIFIER_WORDS` (`name`, `value`, `type`, `status`, `id`, `number`, `amount`), in which case they are emitted as `ID`.
- `BLANK_LINE` tokens are synthesized when 2+ newlines appear in a row. These drive statement separation and comment group logic.
- Escaped single quotes (`''`) inside string literals are handled correctly.
- psql variable forms (`:ident`, `:'quoted'`, `:"quoted"`) are consumed as single `WORD` tokens so they are never split or space-padded.

### Formatter Class

`Formatter.__init__(tokens)` stores the token list and initializes:
- `self.pos` -- current position in the token list
- `self.out` -- list of output string fragments (joined at the end)

Core navigation methods:

| Method               | Purpose                                                |
|----------------------|--------------------------------------------------------|
| `pk(off=0)`          | Peek at token at `pos + off` without consuming         |
| `eat()`              | Consume and return the current token, advance `pos`    |
| `done()`             | True if `pos >= len(tokens)`                           |
| `w(s)`               | Append string `s` to output                            |
| `nl(level)`          | Append newline + indentation at `level`                |
| `ind(level)`         | Return indentation string for `level`                  |
| `_skip_blank_lines()`| Consume and discard any `BLANK_LINE` tokens            |

Key helper methods:

| Method                     | Purpose                                                       |
|----------------------------|---------------------------------------------------------------|
| `is_join()`                | Look ahead to check if current position starts a JOIN clause (delegates to `_is_join_at(0)`) |
| `_is_join_at(off)`         | Check if a JOIN starts at offset `off` from current position  |
| `is_clause_boundary()`     | Check if current token starts a major clause                  |
| `collect_until(stop_fn)`   | Collect tokens into a list until `stop_fn` matches, respecting paren nesting |
| `check_on_has_and()`       | Look ahead past ON to decide if conditions need multi-line layout |
| `join_expr(toks)`          | (module-level) Join token list into a properly spaced string  |

### Formatting Pipeline

```
format()                    -- top-level loop: separates statements, handles comment groups
  +-- format_stmt()         -- dispatches by first keyword
        +-- format_select()     -- SELECT ... FROM ... WHERE ... GROUP BY ... ORDER BY ...
        +-- format_update()     -- UPDATE ... SET ... WHERE ...
        +-- format_delete()     -- DELETE FROM ... WHERE ...
        +-- format_insert()     -- INSERT INTO ... VALUES / SELECT ... ON CONFLICT ...
        +-- format_with()       -- WITH cte AS ( SELECT ... ) SELECT ...
        +-- format_create()     -- CREATE TABLE ... AS SELECT ...
        +-- format_do_block()   -- DO $$ ... $$
        +-- format_raw_statement()  -- fallback: output tokens as-is
```

`format()` is the entry point. It loops over the token stream, collects leading comment groups, inserts 3-blank-line separators between code blocks, and calls `format_stmt()` for each statement.

---

## 2. Test Pipeline

### Running the baseline diff test

The primary test compares formatter output against a known-good expected file:

```bash
cat tests/fixtures/input.sql | python3 psql_custom_formatter.py | diff - tests/fixtures/expected.sql
```

- **Input**: `tests/fixtures/input.sql` -- raw, unformatted SQL with various statement types.
- **Expected output**: `tests/fixtures/expected.sql` -- the correctly formatted version.
- **Pass condition**: `diff` produces no output (exit code 0).

You can also test file-mode (in-place formatting):

```bash
cp tests/fixtures/input.sql /tmp/test.sql
python3 psql_custom_formatter.py /tmp/test.sql
diff /tmp/test.sql tests/fixtures/expected.sql
```

### Running the edge case test suite

```bash
python3 tests/run_tests.py
```

The test runner executes targeted edge case tests. It checks:

- **Regressions** -- each changelog fix has a corresponding test case to prevent reintroduction.
- **Fused keywords** -- verifies that keywords don't run together (e.g., `ENDELSE`, `ENDFROM`) due to missing whitespace/newlines.
- **Idempotency** -- formatting already-formatted SQL should produce identical output (format(format(sql)) == format(sql)).
- **Token preservation** -- ensures all meaningful tokens from the input appear in the output (nothing silently dropped).

Edge case test inputs live in `tests/edge_cases.sql` (20 test cases).

### Adding new tests

To add a regression test for a new bug:

1. Create a minimal SQL input that triggers the bug.
2. Add it to `tests/edge_cases.sql` or create a new file in `tests/`.
3. Run the formatter and verify the output is correct.
4. Add the expected output to the test runner's validation.
