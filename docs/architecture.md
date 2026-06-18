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
Raw SQL string
    → tokenize()           (character-by-character lexer)
    → Parser.parse_all()   (recursive-descent + Pratt parser → AST)
    → ASTFormatter.format_all()  (AST walker → formatted string)
```

The public entry point is `format_sql(sql)`, which wraps the pipeline in a try/except and returns the original SQL unchanged if any error occurs.

---

### Stage 1 — Tokenizer (`tokenize`)

`tokenize(sql)` scans the raw SQL character-by-character and produces a flat list of `(type, value)` tuples. COMMENT tokens carry a third element `preceded_by_newline` (bool) to distinguish inline trailing comments from standalone line comments.

| Token Type    | Description                                         | Example Value         |
|---------------|-----------------------------------------------------|-----------------------|
| `KW`          | SQL keyword (uppercased)                            | `SELECT`, `FROM`      |
| `ID`          | Identifier (lowercased)                             | `table1`, `col_name`  |
| `QUOTED_ID`   | Double-quoted identifier                            | `"MyTable"`           |
| `STR`         | String literal (single-quoted, or `E'...'`)         | `'hello'`             |
| `NUM`         | Numeric literal                                     | `42`, `3.14`          |
| `COMMENT`     | Single-line `--` or block `/* */` comment           | `-- note`             |
| `BLANK_LINE`  | Two or more consecutive newlines in source          | (empty string)        |
| `COMMA`       | `,`                                                 | `,`                   |
| `SEMI`        | `;`                                                 | `;`                   |
| `LPAR`        | `(`                                                 | `(`                   |
| `RPAR`        | `)`                                                 | `)`                   |
| `DOT`         | `.`                                                 | `.`                   |
| `STAR`        | `*`                                                 | `*`                   |
| `OP`          | Operators: `<=`, `>=`, `<>`, `!=`, `::`, `+`, etc. | `::`                  |
| `WORD`        | psql variable: `:ident`, `:'quoted'`, `:"quoted"`   | `:my_var`             |
| `DOLLAR_BODY` | Dollar-quoted block (`$$...$$` or `$tag$...$tag$`)  | `$$BEGIN ... END$$`   |
| `SYM`         | Any other single character                          | `@`, `#`              |

Key tokenizer behaviors:

- Words matching `KEYWORDS` are emitted as `KW` **unless** the lowercase form is in `IDENTIFIER_WORDS` (`name`, `value`, `type`, `status`, `id`, `number`, `amount`), in which case they are emitted as `ID`.
- `BLANK_LINE` tokens are synthesized when 2+ newlines appear consecutively.
- psql variable forms (`:ident`, `:'quoted'`, `:"quoted"`) are consumed as single `WORD` tokens.

---

### Stage 2 — Parser (`Parser` class)

`Parser(tokens)` converts the flat token list into a tree of typed AST nodes using recursive descent for statements/clauses and a Pratt parser (top-down operator precedence) for expressions.

**Entry point**: `Parser.parse_all()` returns `List[Union[Statement, CommentGroup]]`.

`CommentGroup` holds comment lines that appear between statements (with a flag for whether a blank line separated the group from the following statement, which drives the 3-blank-line gap logic).

#### Statement parsers

| Method              | Produces                   |
|---------------------|----------------------------|
| `parse_select()`    | `SelectStatement`          |
| `parse_with()`      | `WithStatement`            |
| `parse_insert()`    | `InsertStatement`          |
| `parse_update()`    | `UpdateStatement`          |
| `parse_delete()`    | `DeleteStatement`          |
| `parse_create()`    | `CreateTableAsStatement` or `CreateIndexStatement` |
| `parse_do_block()`  | `DoBlock`                  |
| `parse_raw_statement()` | `RawStatement`         |

#### Expression parser (Pratt)

`parse_expression(stop_fn, min_prec)` implements top-down operator precedence. `stop_fn` is a caller-supplied predicate that stops parsing at clause boundaries (e.g., `FROM`, `WHERE`, `GROUP`).

Operator precedence levels used:

| Level | Operators |
|-------|-----------|
| 80    | `::` (type cast, right-associative) |
| 60    | `*`, `/`, `%` |
| 55    | `+`, `-`, `\|\|`, `->`, `->>`, `#>` |
| 45    | `=`, `<`, `>`, `<=`, `>=`, `<>`, `!=` |
| 40    | `LIKE`, `ILIKE`, `IN`, `BETWEEN`, `IS` (postfix-like) |
| 20    | `AND` |
| 10    | `OR` |

`parse_primary()` handles prefix forms: literals, identifiers, function calls, `CASE`, `EXISTS`, `ARRAY[...]`, `NOT`, parenthesized expressions, and subqueries.

#### Key AST node types

**Statements**: `SelectStatement`, `InsertStatement`, `UpdateStatement`, `DeleteStatement`, `WithStatement`, `CreateTableAsStatement`, `CreateIndexStatement`, `DoBlock`, `RawStatement`

**Clauses**: `SelectItem`, `FromClause`, `TableRef`, `JoinClause`, `CteClause`, `SetClause`, `OrderItem`, `WindowSpec`, `ValuesClause`, `UnionPart`, `ConflictClause`

**Expressions**: `Literal`, `Identifier`, `BinaryOp`, `UnaryOp`, `IsNullOp`, `FunctionCall`, `CaseExpr`, `CastExpr`, `TypeCastOp`, `InExpr`, `BetweenExpr`, `ExistsExpr`, `SubqueryExpr`, `Parenthesized`, `ArrayExpr`, `AnyAllExpr`, `RawTokens`

`RawTokens` / `RawStatement` are fallback nodes that hold raw token tuples. `join_expr()` formats them on output, preserving the formatter's behavior for unsupported constructs.

---

### Stage 3 — ASTFormatter (`ASTFormatter` class)

`ASTFormatter.format_all(results)` walks the list returned by `parse_all()` and produces the final formatted string.

The formatter is structurally driven — no lookahead is needed at format time because the shape of the query is already encoded in the AST:

| Old heuristic | Replaced by |
|---------------|-------------|
| `check_on_has_and()` | `isinstance(on_condition, BinaryOp) and op in ('AND','OR')` |
| `_on_paren_is_wrapper()` | `SubqueryExpr` vs `Parenthesized` node type |
| `_lookahead_has_select_in_parens()` | `TableRef.subquery is not None` |
| `_lookahead_has_values_in_parens()` | `TableRef.values is not None` |
| `_collect_in_values()` | `InExpr.values` list / `InExpr.subquery` |
| `_collect_case_expr()` | `CaseExpr.branches` list |
| `_collect_bracket_values()` | `ArrayExpr.elements` list |
| `between_depth` counter | `BetweenExpr` node |
| `paren_depth` in `format_conditions` | Implicit in AST nesting |
| Alias exclusion list in `format_table_ref` | `alias` field on `TableRef` |

#### AND/OR formatting

`format_where_expr(expr, ci, inline_and)` flattens a top-level `BinaryOp` AND/OR tree with `_flatten_conditions()`:

```python
def _flatten_conditions(expr):
    if isinstance(expr, BinaryOp) and expr.op in ('AND', 'OR'):
        return _flatten_conditions(expr.left) + [(expr.op, expr.right)]
    return [(None, expr)]
```

Each condition is emitted on its own line with the connector (`AND`/`OR`) as a prefix. Expressions inside `Parenthesized` nodes stay inline.

In subquery context (`inline_and=True`), `format_expression` is called directly with `inline=True` so AND/OR stays on one line.

#### Key format methods

| Method | Handles |
|--------|---------|
| `format_all(results)` | Top-level loop: 3-blank-line gaps, comment groups |
| `format_statement(stmt)` | Dispatches to type-specific methods |
| `format_select(stmt, base, is_subquery)` | SELECT with all clauses; recurses for UNION chains |
| `format_where_expr(expr, ci, inline_and)` | AND/OR flattening for WHERE/HAVING/ON |
| `format_expression(expr, ci, inline)` | All expression types |
| `format_case(expr, ci)` | CASE WHEN … THEN … END |
| `format_in_expr(expr, ci)` | IN (…) with expansion when > 3 values |
| `format_function_call(call, ci)` | Functions, window specs, FILTER clauses |
| `format_from_clause(clause, base)` | FROM tables + JOINs |
| `format_join(join, ci)` | JOIN … ON … with multi-line condition layout |
| `format_table_ref(ref, ci)` | Bare table, subquery, or VALUES constructor |
| `format_with(stmt)` | WITH cte AS (…) main-statement |
| `format_update(stmt)` | UPDATE … SET … FROM … WHERE … |
| `format_insert(stmt)` | INSERT INTO … VALUES/SELECT … ON CONFLICT … |

---

## 2. Test Pipeline

### Running the baseline diff test

```bash
cat tests/fixtures/input.sql | python3 psql_custom_formatter.py | diff - tests/fixtures/expected.sql
```

- **Input**: `tests/fixtures/input.sql` — raw, unformatted SQL with various statement types.
- **Expected output**: `tests/fixtures/expected.sql` — the correctly formatted version.
- **Pass condition**: `diff` produces no output (exit code 0).

### Running the full test suite

```bash
python3 tests/run_tests.py
```

75 tests across four suites:

1. **Regression** — compares fixture input/expected output.
2. **Edge cases** — 24 targeted test blocks in `tests/edge_cases.sql`; each starts with `-- TEST N:`.
3. **Idempotency** — `format(format(sql)) == format(sql)` for every test case.
4. **Round-trip tokens** — verifies no tokens are silently dropped.

Plus 7 automated quality checks on every output: no exceptions, no empty output, no fused keywords, no double spaces, correct semicolon spacing, keyword uppercasing, balanced parentheses.

### Adding new tests

To add a regression test:

1. Create a minimal SQL input that triggers the case.
2. Add it to `tests/edge_cases.sql` with a `-- TEST N:` header.
3. Run the formatter and verify the output is correct.
4. The test runner picks up new blocks automatically.
