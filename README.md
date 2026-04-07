# psql_custom_formatter

A lightweight, zero-dependency PostgreSQL SQL formatter written in Python. Designed to be used as an **external formatter in DBeaver**, but works standalone via stdin/stdout or file mode.

## Features

- **Leading comma style** -- commas at the start of continuation lines for easy column toggling
- **Clause-per-line layout** -- SELECT, FROM, WHERE, GROUP BY, ORDER BY each on their own line
- **Smart JOIN formatting** -- JOINs indented under FROM, ON conditions double-indented with AND/OR on new lines
- **CASE expression formatting** -- WHEN/ELSE indented with recursive nesting support
- **Comment preservation** -- inline trailing comments tab-aligned, standalone comments on their own line
- **Cast operator** -- `col::TEXT` with no spaces and uppercased type
- **IN list expansion** -- auto-expands to one-per-line when more than 3 values
- **Subquery formatting** -- proper indentation for subqueries in FROM, WHERE, and IN clauses
- **Keyword uppercasing** -- SQL keywords uppercased, identifiers lowercased
- **Statement separation** -- 3 blank lines between code blocks

### Supported Statements

| Statement | Features |
|-----------|----------|
| `SELECT` | DISTINCT, subqueries, UNION/UNION ALL, HAVING, LIMIT/OFFSET |
| `INSERT` | Column lists, VALUES, SELECT body, ON CONFLICT, RETURNING |
| `UPDATE` | SET clause, FROM with JOINs, WHERE, RETURNING |
| `DELETE` | FROM, WHERE |
| `CREATE TABLE ... AS SELECT` | IF NOT EXISTS, schema-qualified names |
| `WITH` (CTE) | Multiple CTEs, RECURSIVE, column lists |
| `DO $$ ... $$` | PL/pgSQL passthrough |

## Installation

No dependencies required -- just Python 3.

```bash
git clone https://github.com/TheoSchramm/psql_custom_formatter.git
cd psql_custom_formatter
```

## Usage

### Stdin/Stdout

```bash
echo "SELECT id, name, email FROM users WHERE active = true ORDER BY name" | python3 psql_custom_formatter.py
```

Output:

```sql
SELECT
    id
    , name
    , email
FROM
    users
WHERE
    active = TRUE
ORDER BY
    name
```

### File Mode (in-place)

```bash
python3 psql_custom_formatter.py myquery.sql
```

Formats the file in-place -- designed for DBeaver's temp file integration.

### DBeaver Integration

1. Go to **Preferences > Editors > SQL Editor > Formatting**
2. Set **Formatter** to **External**
3. Set the command to:
   ```
   python3 /path/to/psql_custom_formatter.py
   ```
4. Use `Ctrl+Shift+F` to format SQL in the editor

## Examples

### Before

```sql
select o.order_number as order_num, c.name as customer, ol.description as product,
ol.unit_price as price from store.order_lines ol join store.orders o on
o.id = ol.order_id join store.customers c on c.id = o.customer_id where o.status not in
('Cancelled', 'Refunded') and o.deleted is false and ol.deleted is false order by order_num
```

### After

```sql
SELECT
    o.order_number AS order_num
    , c.name AS customer
    , ol.description AS product
    , ol.unit_price AS price
FROM
    store.order_lines ol
    JOIN store.orders o ON
        o.id = ol.order_id
    JOIN store.customers c ON
        c.id = o.customer_id
WHERE
    o.status NOT IN ('Cancelled', 'Refunded')
    AND o.deleted IS FALSE
    AND ol.deleted IS FALSE
ORDER BY
    order_num
```

## Testing

```bash
# Regression test against expected output
cat tests/fixtures/input.sql | python3 psql_custom_formatter.py | diff - tests/fixtures/expected.sql

# Full test suite (63 tests: edge cases, idempotency, round-trip tokens)
python3 tests/run_tests.py
```

## Project Structure

```
psql_custom_formatter/
    psql_custom_formatter.py      # The formatter (single file, no dependencies)
    docs/
        architecture.md         # Internal architecture and test pipeline
        known-issues.md         # Open bugs and potential improvements
    tests/
        run_tests.py            # Test runner (edge cases, idempotency, round-trip)
        edge_cases.sql          # 20 edge case test inputs
        fixtures/
            input.sql           # Regression test input
            expected.sql        # Regression test expected output
    examples/
        select_join_where.sql       # SELECT with JOINs, WHERE, INSERT
        select_with_subquery.sql    # SELECT with subqueries, COUNT
        create_and_update.sql       # CREATE TABLE AS, UPDATE, templated message
        select_with_groupby.sql     # SELECT with GROUP BY, ORDER BY, IN subquery
        do_block_search.sql         # DO block with PL/pgSQL column search
    CHANGELOG.md                # All fix history and version changes
    CLAUDE.md                   # Claude Code instructions and formatting rules
```

## License

MIT
