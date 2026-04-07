# Known Issues & Potential Improvements

Identified 2026-04-07 via code review of `psql_custom_formatter.py`.

---

## Bugs

### BUG-1: `BETWEEN...AND` broken when comment or blank line separates them

**Severity**: Bug — produces incorrect output for valid SQL.

**Location**: `format_conditions()` lines ~948-952 (outer AND handler) and ~1066-1072 (expression collector).

**Description**: When a comment (or blank line) appears between `BETWEEN` and its matching `AND`, the expression collector breaks before consuming `AND`. The outer `between` flag is True, so the outer AND handler fires and sets `between = False` — but it does **not** consume the `AND` token. Control falls through to the expression collector, which sees `AND`, finds `between` is now False, and breaks again. The outer loop then treats `AND` as a condition separator instead of part of `BETWEEN...AND`.

**Reproduction**:

```sql
SELECT * FROM t WHERE a BETWEEN 1 -- comment
AND 10 AND b = 2;
```

**Actual output** (broken):

```sql
WHERE
    a BETWEEN 1					-- comment
    
    AND 10
    AND b = 2;
```

**Expected output**:

```sql
WHERE
    a BETWEEN 1					-- comment
    AND 10
    AND b = 2;
```

Here `AND 10` should be part of the `BETWEEN 1 AND 10` expression, not a separate condition.

**Fix**: When `between` is True in the outer AND handler (line ~950), consume the AND token (`self.eat()`), reset `between = False`, and let the next iteration collect the rest of the expression. Alternatively, refactor so the expression collector doesn't break on COMMENT when `between` is True.

---

## Performance

### PERF-1: `_last_line()` is O(n) per call — quadratic in total output size

**Severity**: Performance — causes slowdown on large SQL files.

**Location**: `_last_line()` at line ~605.

**Description**: Every call joins the entire `self.out` list into a single string (`''.join(self.out)`) and then searches backward for `\n`. This is called after every comment alignment (trailing comments in SELECT, WHERE, ON, SET, GROUP BY, ORDER BY). For a SQL file with many comments, this becomes O(n^2) in the total output size.

**Fix**: Search `self.out` in reverse for the last element containing `\n`, then extract the substring after it. This makes each call O(k) where k is the length of the last few output fragments, not the entire output.

```python
def _last_line(self):
    for i in range(len(self.out) - 1, -1, -1):
        chunk = self.out[i]
        nl = chunk.rfind('\n')
        if nl >= 0:
            tail = chunk[nl + 1:]
            for j in range(i + 1, len(self.out)):
                tail += self.out[j]
            return tail
    return ''.join(self.out)
```

---

## Inconsistencies

### INCON-1: `format_delete` uses hardcoded `\t` instead of `INDENT`

**Severity**: Inconsistency — DELETE output uses tab indentation while all other statement types use 4-space indentation.

**Location**: `format_delete()` at line ~1275.

**Description**: `format_delete` writes `'\n\t'` for the table name and WHERE condition indentation. Every other formatter method uses `self.nl(level)` which produces `'\n' + INDENT * level` (4 spaces per level). This means DELETE statements look different when displayed in editors with non-4-space tab stops.

**Fix**: Replace `'\n\t'` with `self.nl(1)` calls, and `'\nWHERE '` with `self.nl(0); self.w('WHERE')`.

---

## Missing Features

### FEAT-1: No `EXCEPT` / `INTERSECT` support

**Severity**: Missing feature — these set operations are silently dropped or misformatted.

**Location**: `format_select()` at line ~532.

**Description**: Only `UNION` / `UNION ALL` are handled for set operations. `EXCEPT`, `EXCEPT ALL`, `INTERSECT`, and `INTERSECT ALL` are valid SQL set operators but are not recognized. They would be consumed by whatever clause is active at that point (e.g., ORDER BY item list, WHERE conditions), producing incorrect output.

**Fix**: Extend the UNION handling block to also match `EXCEPT` and `INTERSECT`, with the same `ALL` optional modifier logic. Also add `'EXCEPT'` and `'INTERSECT'` to clause boundary checks throughout the formatter (SELECT list, item list, conditions, etc.).

---

## Fragile Code

### FRAG-1: Alias detection in `format_table_ref` relies on keyword exclusion list

**Severity**: Fragile — adding new keywords can silently break alias detection.

**Location**: `format_table_ref()` at line ~751.

**Description**: After parsing a table reference like `users u`, the formatter checks if the next token is an alias by testing `self.pk()[0] in ('ID', 'QUOTED_ID')` and then excluding a hardcoded list of keywords that should NOT be consumed as aliases:

```python
elif (self.pk()[0] in ('ID', 'QUOTED_ID') and
      self.pk()[1] not in (
          'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL',
          'CROSS', 'ON', 'WHERE', 'GROUP', 'ORDER', 'HAVING',
          'SET', 'SELECT', 'FROM', 'AND', 'OR', 'LIMIT', ';')):
```

Any keyword missing from this list (e.g., `RETURNING`, `UNION`, `EXCEPT`, `INTERSECT`, `LATERAL`, `OFFSET`, `FETCH`) could be incorrectly consumed as a table alias.

Note: `NOT` is notably absent. `FROM table1 NOT` would consume `NOT` as an alias, though this is unlikely in practice since `NOT` rarely appears immediately after a table reference without being part of `IS NOT` or `NOT EXISTS` etc.

**Fix**: Use a positive match approach instead — define a set of valid alias patterns (bare ID not matching any keyword, or QUOTED_ID) and let everything else fall through. Alternatively, expand the exclusion list to cover all currently recognized keywords and add a comment flagging this as a maintenance point.

### FRAG-2: `check_on_has_and` does not skip COMMENT tokens

**Severity**: Fragile — comments between ON conditions may cause incorrect single-line layout.

**Location**: `check_on_has_and()` at line ~324.

**Description**: This lookahead function scans tokens after ON to decide whether conditions need multi-line layout (i.e., whether AND exists). It does not skip COMMENT tokens. If a comment appears between ON condition tokens, the scan sees the COMMENT token, which doesn't match any exit condition or AND, so it just increments `j` and continues — this is fine in practice because COMMENT tokens have type `'COMMENT'` and value `'-- ...'`, neither of which match the checked keywords.

However, the scan also doesn't skip `BLANK_LINE` tokens. A BLANK_LINE has value `''`, which also doesn't match. So this works by accident — the function tolerates unexpected token types by simply advancing past them.

**Fix**: Add explicit `if t[0] in ('COMMENT', 'BLANK_LINE'): j += 1; continue` for clarity and correctness.

---

## Edge Cases

### EDGE-1: Nested SELECT inside IN value list

**Severity**: Edge case — rare SQL pattern produces suboptimal output.

**Location**: `_collect_in_values()` at line ~1100.

**Description**: The function `_collect_in_values` collects value groups inside `IN (...)` by tracking paren depth. If someone writes `IN (1, (SELECT id FROM t), 3)`, the paren depth tracker would consume the `(SELECT ...)` as a value group (the parens balance), but the SELECT inside is not formatted — it stays as raw tokens joined by `join_expr`.

This differs from `IN (SELECT ...)` (without other values), which is detected earlier and properly formatted. The mixed case `IN (value, (SELECT ...), value)` is rare in practice.

**Fix**: Inside `_collect_in_values`, detect `(SELECT` at depth 0 and either delegate to `format_select` for that value group or flag it for special handling.

### EDGE-2: Parenthesized expression depth tracking in `format_conditions`

**Severity**: Edge case — malformed SQL could cause over-consumption.

**Location**: `format_conditions()` at line ~887, ~1085.

**Description**: The `cond_depth` variable tracks unclosed parentheses across expression collector calls:

```python
cond_depth += paren_depth
```

When a `)` is encountered in the outer loop (line ~914), `cond_depth` is checked to decide whether the `)` closes a sub-expression (continue) or ends the WHERE clause (break). If the source SQL has mismatched parentheses, `cond_depth` could be wrong, causing the formatter to consume tokens beyond the WHERE clause boundary or break too early.

This only affects malformed SQL — valid SQL always has balanced parens. Since `format_sql` wraps everything in a try/except and returns original SQL on error, the worst case is returning unformatted SQL.

### EDGE-3: Block comments tab-separated from following token in `join_expr`

**Severity**: Cosmetic — block comments get tab-separated from the token they precede.

**Location**: `join_expr()` at line ~215.

**Description**: `join_expr` handles all COMMENT tokens by inserting a `\t` before them (for tab-alignment). This is correct for trailing `--` comments, but for block comments `/* ... */` that precede an identifier (e.g., `/* note */ email`), the output becomes `/* note */\temail` instead of `/* note */ email`.

In practice this is barely visible since block comments in SELECT items are uncommon, and the tab often renders similarly to a space.

**Fix**: In `join_expr`, check whether the comment starts with `--` vs `/*` and only tab-align `--` comments. For `/* */` comments, use a regular space.

---

## Summary

| ID | Type | Severity | Fix Effort | Description |
|----|------|----------|------------|-------------|
| BUG-1 | Bug | **High** | Small | `BETWEEN...AND` split when comment separates them |
| PERF-1 | Performance | Medium | Small | `_last_line()` O(n) join per call |
| INCON-1 | Inconsistency | Low | Trivial | DELETE uses `\t` not `INDENT` |
| FEAT-1 | Missing | Medium | Small | No `EXCEPT`/`INTERSECT` support |
| FRAG-1 | Fragile | Medium | Medium | Alias detection keyword exclusion list |
| FRAG-2 | Fragile | Low | Trivial | `check_on_has_and` doesn't skip comments/blanks |
| EDGE-1 | Edge case | Low | Medium | Nested SELECT in IN value list |
| EDGE-2 | Edge case | Low | N/A | Paren depth tracking with malformed SQL |
| EDGE-3 | Cosmetic | Low | Small | Block comments tab-separated in `join_expr` |
