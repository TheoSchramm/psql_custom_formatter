#!/usr/bin/env python3
"""Custom PostgreSQL SQL formatter for DBeaver.

Reads SQL from stdin or a file, formats it, and outputs the result.
File mode formats in-place (for DBeaver temp file integration).
"""

import sys

INDENT = '    '  # 4 spaces

KEYWORDS = {
    'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'ON',
    'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL', 'CROSS',
    'ORDER', 'BY', 'GROUP', 'HAVING', 'LIMIT', 'OFFSET',
    'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE',
    'AS', 'IS', 'NULL', 'BETWEEN', 'LIKE', 'EXISTS',
    'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
    'UNION', 'EXCEPT', 'INTERSECT', 'ALL', 'DISTINCT', 'ASC', 'DESC',
    'SUM', 'COUNT', 'AVG', 'MIN', 'MAX',
    'COALESCE', 'NULLIF', 'CAST',
    'TRUE', 'FALSE',
    'WITH', 'RECURSIVE',
    'OVER', 'PARTITION',
    'FETCH', 'FIRST', 'NEXT', 'ONLY',
    'RETURNING', 'CONFLICT', 'DO', 'NOTHING',
    'CREATE', 'TABLE', 'IF', 'DROP', 'ALTER',
    'LATERAL',
}

IDENTIFIER_WORDS = {'name', 'value', 'type', 'status', 'id', 'number', 'amount'}

FUNCTION_KWS = {
    'SUM', 'COUNT', 'AVG', 'MIN', 'MAX', 'COALESCE', 'NULLIF', 'CAST',
    'TRIM', 'SUBSTRING', 'EXTRACT', 'ARRAY_AGG', 'STRING_AGG',
    'ROW_NUMBER', 'RANK', 'DENSE_RANK', 'LAG', 'LEAD',
    'FIRST_VALUE', 'LAST_VALUE', 'NTH_VALUE', 'UPPER', 'LOWER',
    'CONCAT', 'LENGTH', 'REPLACE', 'ROUND', 'ABS', 'CEIL', 'FLOOR',
}


def tokenize(sql):
    tokens = []
    i = 0
    n = len(sql)
    while i < n:
        if sql[i] in ' \t\n\r':
            # Detect blank lines (2+ newlines) to preserve comment group gaps
            if sql[i] == '\n':
                j = i + 1
                newline_count = 1
                while j < n and sql[j] in ' \t\n\r':
                    if sql[j] == '\n':
                        newline_count += 1
                    j += 1
                if newline_count >= 2:
                    tokens.append(('BLANK_LINE', ''))
                    i = j
                    continue
            i += 1
            continue
        if sql[i:i+2] == '--':
            end = sql.find('\n', i)
            if end == -1:
                end = n
            tokens.append(('COMMENT', sql[i:end].rstrip()))
            i = end
            continue
        if sql[i:i+2] == '/*':
            end = sql.find('*/', i)
            end = n if end == -1 else end + 2
            tokens.append(('COMMENT', sql[i:end]))
            i = end
            continue
        # E'...' escaped string literals (keep E prefix attached)
        if sql[i] in ('E', 'e') and i + 1 < n and sql[i+1] == "'":
            j = i + 2
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j+1] == "'":
                    j += 2
                elif sql[j] == "'":
                    break
                else:
                    j += 1
            tokens.append(('STR', sql[i:j+1]))
            i = j + 1
            continue
        if sql[i] == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j+1] == "'":
                    j += 2
                elif sql[j] == "'":
                    break
                else:
                    j += 1
            tokens.append(('STR', sql[i:j+1]))
            i = j + 1
            continue
        if sql[i] == '"':
            j = i + 1
            while j < n and sql[j] != '"':
                j += 1
            tokens.append(('QUOTED_ID', sql[i:j+1]))
            i = j + 1
            continue
        if sql[i].isdigit() or (sql[i] == '.' and i + 1 < n and sql[i+1].isdigit()):
            j = i
            while j < n and (sql[j].isdigit() or sql[j] == '.'):
                j += 1
            tokens.append(('NUM', sql[i:j]))
            i = j
            continue
        if sql[i].isalpha() or sql[i] == '_':
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == '_'):
                j += 1
            word = sql[i:j]
            up = word.upper()
            if up in KEYWORDS and word.lower() not in IDENTIFIER_WORDS:
                tokens.append(('KW', up))
            else:
                tokens.append(('ID', word.lower()))
            i = j
            continue
        c = sql[i]
        if c == ',':
            tokens.append(('COMMA', ','))
            i += 1
        elif c == ';':
            tokens.append(('SEMI', ';'))
            i += 1
        elif c == '(':
            tokens.append(('LPAR', '('))
            i += 1
        elif c == ')':
            tokens.append(('RPAR', ')'))
            i += 1
        elif c == '.':
            tokens.append(('DOT', '.'))
            i += 1
        elif c == '*':
            tokens.append(('STAR', '*'))
            i += 1
        elif i + 2 < n and sql[i:i+3] in ('->>',):
            tokens.append(('OP', sql[i:i+3]))
            i += 3
        elif i + 1 < n and sql[i:i+2] in ('<=', '>=', '<>', '!=', '::', '->', '#>'):
            tokens.append(('OP', sql[i:i+2]))
            i += 2
        elif c in '<>=+-/%':
            tokens.append(('OP', c))
            i += 1
        elif c == '$':
            # Dollar-quoting: $$ or $tag$
            j = i + 1
            if j < n and sql[j] == '$':
                delim = '$$'
                body_start = i + 2
            elif j < n and (sql[j].isalpha() or sql[j] == '_'):
                k = j
                while k < n and (sql[k].isalnum() or sql[k] == '_'):
                    k += 1
                if k < n and sql[k] == '$':
                    delim = sql[i:k+1]
                    body_start = k + 1
                else:
                    i += 1
                    continue
            else:
                i += 1
                continue
            end = sql.find(delim, body_start)
            if end == -1:
                tokens.append(('DOLLAR_BODY', sql[i:n]))
                i = n
            else:
                end += len(delim)
                tokens.append(('DOLLAR_BODY', sql[i:end]))
                i = end
        else:
            tokens.append(('SYM', sql[i]))
            i += 1
    return tokens


def join_expr(toks):
    """Join a list of tokens into a properly spaced expression string."""
    if not toks:
        return ''
    parts = [toks[0][1]]
    for i in range(1, len(toks)):
        prev_type, prev_val = toks[i - 1]
        cur_type, cur_val = toks[i]
        need_space = True
        if prev_type == 'DOT' or cur_type == 'DOT':
            need_space = False
        elif prev_val == '(':
            need_space = False
        elif cur_val == ')':
            need_space = False
        elif cur_val == '(' and prev_val.upper() in FUNCTION_KWS:
            need_space = False
        elif cur_val == '(' and prev_type in ('ID', 'QUOTED_ID'):
            need_space = False
        elif prev_val == ')' and cur_type == 'DOT':
            need_space = False
        elif prev_val == '::' or cur_val == '::':
            need_space = False
        elif prev_type == 'SYM' and cur_type == 'SYM':
            need_space = False
        elif cur_type == 'COMMA':
            need_space = False
        # Tab-align line comments; keep block comments inline with a space
        if cur_type == 'COMMENT':
            if cur_val.lstrip().startswith('--'):
                parts.append('\t')
            else:
                parts.append(' ')
            parts.append(cur_val)
            continue
        if need_space:
            parts.append(' ')
        # Uppercase the type after cast operator (::)
        if prev_val == '::' and cur_type == 'ID':
            parts.append(cur_val.upper())
        else:
            parts.append(cur_val)
    return ''.join(parts)


class Formatter:
    def __init__(self, tokens):
        self.tok = tokens
        self.pos = 0
        self.out = []
        self.between_depth = 0

    def pk(self, off=0):
        p = self.pos + off
        return self.tok[p] if p < len(self.tok) else ('EOF', '')

    def eat(self):
        t = self.tok[self.pos]
        self.pos += 1
        return t

    def done(self):
        return self.pos >= len(self.tok)

    def w(self, s):
        self.out.append(s)

    def nl(self, level):
        self.w('\n' + INDENT * level)

    def _skip_blank_lines(self):
        while not self.done() and self.pk()[0] == 'BLANK_LINE':
            self.eat()

    def _skip_inter_clause(self, base):
        """Skip blank lines and output standalone comments between clauses."""
        while not self.done() and self.pk()[0] in ('BLANK_LINE', 'COMMENT'):
            if self.pk()[0] == 'COMMENT':
                self.nl(base)
                self.w(self.eat()[1])
            else:
                self.eat()

    def _lookahead_has_select_in_parens(self):
        """Check if ( is followed by SELECT (possibly after blank lines)."""
        j = 1
        while self.pk(j)[0] == 'BLANK_LINE':
            j += 1
        return self.pk(j)[1] == 'SELECT'

    def ind(self, level):
        return INDENT * level

    def is_join(self):
        return self._is_join_at(0)

    def _is_join_at(self, off):
        t = self.pk(off)
        if t[1] == 'JOIN':
            return True
        if t[1] in ('LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS', 'OUTER'):
            j = off + 1
            while self.pk(j)[1] in ('LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS', 'OUTER'):
                j += 1
            return self.pk(j)[1] == 'JOIN'
        return False

    def is_clause_boundary(self):
        t = self.pk()
        if t[1] in ('SELECT', 'FROM', 'WHERE', 'SET', 'HAVING', 'LIMIT',
                     'UPDATE', 'DELETE', 'INSERT'):
            return True
        if t[1] == 'GROUP' and self.pk(1)[1] == 'BY':
            return True
        if t[1] == 'ORDER' and self.pk(1)[1] == 'BY':
            return True
        if t[1] in ('UNION', 'EXCEPT', 'INTERSECT'):
            return True
        return False

    def collect_until(self, stop_fn):
        """Collect tokens until stop condition, respecting paren nesting."""
        toks = []
        depth = 0
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if depth == 0 and stop_fn(t):
                break
            if t[1] == '(':
                depth += 1
            elif t[1] == ')':
                if depth == 0:
                    break
                depth -= 1
            toks.append(self.eat())
        return toks

    def check_on_has_and(self):
        """Look ahead past ON to see if the conditions contain AND."""
        j = 1
        while True:
            t = self.pk(j)
            if t[0] in ('EOF', 'COMMENT', 'BLANK_LINE'):
                if t[0] == 'EOF':
                    return False
                j += 1
                continue
            if t[1] in (';', 'WHERE', 'GROUP', 'ORDER',
                        'HAVING', 'LIMIT', 'SELECT', 'FROM'):
                return False
            if t[1] == 'JOIN':
                return False
            if t[1] in ('LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS', 'OUTER', 'LATERAL'):
                k = j + 1
                while self.pk(k)[1] in ('LEFT', 'RIGHT', 'INNER', 'FULL',
                                         'CROSS', 'OUTER'):
                    k += 1
                if self.pk(k)[1] == 'JOIN':
                    return False
            if t[1] == 'AND':
                return True
            j += 1

    # ── Top-level ──────────────────────────────────────────────

    def format(self):
        first = True
        while not self.done():
            # Skip stray semicolons and blank lines
            if self.pk()[1] == ';':
                self.eat()
                continue
            if self.pk()[0] == 'BLANK_LINE':
                self.eat()
                continue

            # Collect comment groups separated by blank lines
            comment_groups = []
            comments_had_trailing_blank = False
            if self.pk()[0] == 'COMMENT':
                current_group = []
                while not self.done() and self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
                    if self.pk()[0] == 'BLANK_LINE':
                        self.eat()
                        if current_group:
                            comment_groups.append(current_group)
                            current_group = []
                        comments_had_trailing_blank = True
                    else:
                        current_group.append(self.eat()[1])
                        comments_had_trailing_blank = False
                if current_group:
                    comment_groups.append(current_group)
            # Skip semicolons after comments
            while not self.done() and self.pk()[1] == ';':
                self.eat()

            # Trailing comments only (no statement after)
            if self.done():
                for gi, group in enumerate(comment_groups):
                    if gi > 0 or not first:
                        self.w('\n\n\n\n')
                    self.w('\n'.join(group))
                break

            # 3-blank-line gap between code blocks
            if not first:
                self.w('\n\n\n\n')
            first = False

            # Write comment groups with 3-blank-line gaps between them
            # Last group attaches to the statement below it (unless
            # there was a blank line separating comments from code)
            for gi, group in enumerate(comment_groups):
                if gi > 0:
                    self.w('\n\n\n\n')
                self.w('\n'.join(group))
            if comment_groups:
                if comments_had_trailing_blank:
                    self.w('\n\n\n\n')
                else:
                    self.w('\n')

            self.format_stmt()
        return ''.join(self.out)

    def format_stmt(self):
        t = self.pk()
        if t[1] == 'SELECT':
            self.format_select(0)
        elif t[1] == 'UPDATE':
            self.format_update()
        elif t[1] == 'DELETE':
            self.format_delete()
        elif t[1] == 'INSERT':
            self.format_insert()
        elif t[1] == 'WITH':
            self.format_with()
        elif t[1] == 'CREATE':
            self.format_create()
        elif t[1] == 'DO' and self.pk(1)[0] == 'DOLLAR_BODY':
            self.format_do_block()
        elif t[0] == 'DOLLAR_BODY':
            self.w(self.eat()[1])
        else:
            self.format_raw_statement()

    def format_raw_statement(self):
        """Output tokens as-is until next statement boundary or semicolon."""
        toks = []
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if t[1] == ';':
                toks.append(self.eat())
                break
            # Stop at next top-level statement keyword
            if not toks and t[1] in ('SELECT', 'UPDATE', 'DELETE', 'INSERT',
                                      'CREATE', 'WITH'):
                # Don't consume the keyword, let the main loop handle it
                break
            if toks and t[1] in ('SELECT', 'UPDATE', 'DELETE', 'INSERT',
                                  'CREATE', 'WITH'):
                break
            toks.append(self.eat())
        self.w(join_expr(toks))

    # ── SELECT ─────────────────────────────────────────────────

    def format_select(self, base, is_subquery=False):
        self.w(self.ind(base) + 'SELECT')
        self.eat()

        if self.pk()[1] == 'DISTINCT':
            self.w(' DISTINCT')
            self.eat()

        self.format_select_list(base + 1)

        self._skip_inter_clause(base)
        if self.pk()[1] == 'FROM':
            self.nl(base)
            self.w('FROM')
            self.eat()
            self.format_from_clause(base)

        self._skip_inter_clause(base)
        if self.pk()[1] == 'WHERE':
            self.nl(base)
            self.w('WHERE')
            self.eat()
            self.format_where(base, is_subquery=is_subquery)

        self._skip_inter_clause(base)
        if self.pk()[1] == 'GROUP' and self.pk(1)[1] == 'BY':
            self.nl(base)
            self.eat()  # GROUP
            self.eat()  # BY
            self.w('GROUP BY')
            self.format_item_list(base + 1)

        self._skip_inter_clause(base)
        if self.pk()[1] == 'HAVING':
            self.nl(base)
            self.w('HAVING')
            self.eat()
            self.format_where(base, is_subquery=is_subquery)

        self._skip_inter_clause(base)
        if self.pk()[1] == 'ORDER' and self.pk(1)[1] == 'BY':
            self.nl(base)
            self.eat()  # ORDER
            self.eat()  # BY
            self.w('ORDER BY')
            self.format_item_list(base + 1)

        self._skip_inter_clause(base)
        if self.pk()[1] == 'LIMIT':
            self.nl(base)
            self.w('LIMIT ')
            self.eat()
            toks = self.collect_until(
                lambda t: t[1] in (';', 'OFFSET') or t[0] == 'EOF')
            self.w(join_expr(toks))

        self._skip_inter_clause(base)
        if self.pk()[1] == 'OFFSET':
            self.nl(base)
            self.w('OFFSET ')
            self.eat()
            toks = self.collect_until(
                lambda t: t[1] in (';',) or t[0] == 'EOF')
            self.w(join_expr(toks))

        # FETCH FIRST/NEXT ... ONLY (SQL standard alternative to LIMIT)
        self._skip_inter_clause(base)
        if self.pk()[1] == 'FETCH':
            self.nl(base)
            toks = self.collect_until(
                lambda t: t[1] in (';',) or t[0] == 'EOF')
            self.w(join_expr(toks))

        self._skip_blank_lines()
        if self.pk()[1] == ';':
            self.w(';')
            self.eat()

        # Handle UNION / EXCEPT / INTERSECT (with optional ALL) chaining
        if self.pk()[1] in ('UNION', 'EXCEPT', 'INTERSECT'):
            op = self.eat()[1]  # UNION, EXCEPT, or INTERSECT
            self.w('\n')
            if self.pk()[1] == 'ALL':
                self.w(self.ind(base) + op + ' ALL')
                self.eat()
            else:
                self.w(self.ind(base) + op)
            self.w('\n')
            self.format_select(base, is_subquery=is_subquery)

    def format_select_list(self, ci):
        first = True
        need_nl = False
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if t[1] in ('FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING',
                         'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT',
                         ';', ')') or t[0] == 'EOF':
                break

            if t[1] == ',':
                self.eat()
                # Trailing line comment after comma (e.g., id,--comment)
                if (self.pk()[0] == 'COMMENT' and
                        self.pk()[1].lstrip().startswith('--')):
                    comment = self.eat()[1]
                    last_line = self._last_line()
                    tabs = self._calc_comment_tabs(last_line)
                    self.w(tabs + comment)
                self.nl(ci)
                self.w(', ')
                first = False
                continue

            # Standalone line comment (-- ...) before the next item
            if t[0] == 'COMMENT' and t[1].lstrip().startswith('--'):
                # Check if this comment precedes a clause boundary
                j = 0
                while self.pk(j)[0] == 'COMMENT':
                    j += 1
                next_after = self.pk(j)
                if next_after[1] in ('FROM', 'WHERE', 'GROUP', 'ORDER',
                                     'HAVING', 'LIMIT', 'UNION',
                                     'EXCEPT', 'INTERSECT', ';',
                                     ')') or next_after[0] == 'EOF':
                    break  # leave for outer handler
                self.nl(ci)
                self.w(self.eat()[1])
                first = False
                need_nl = True
                continue

            if first:
                self.nl(ci)
                first = False
            elif need_nl:
                self.nl(ci)
                need_nl = False

            if self.pk()[1] == 'CASE':
                self.format_case(ci)
            else:
                self.format_select_item(ci)

            # Trailing comment (first comment after item is always trailing)
            if self.pk()[0] == 'COMMENT':
                comment = self.eat()[1]
                last_line = self._last_line()
                tabs = self._calc_comment_tabs(last_line)
                self.w(tabs + comment)

    def _last_line(self):
        """Get the last line of output so far (searches in reverse for efficiency)."""
        for i in range(len(self.out) - 1, -1, -1):
            chunk = self.out[i]
            nl = chunk.rfind('\n')
            if nl >= 0:
                tail = chunk[nl + 1:]
                for j in range(i + 1, len(self.out)):
                    tail += self.out[j]
                return tail
        return ''.join(self.out)

    def _calc_comment_tabs(self, line):
        """Calculate tabs needed to align comment to column 32 (4-char tabs)."""
        col = len(line)
        target = 32
        if col >= target:
            return '\t'
        tab_size = 4
        num_tabs = (target - col + tab_size - 1) // tab_size
        return '\t' * num_tabs

    def format_select_item(self, ci):
        """Format one SELECT item (not CASE)."""
        toks = self.collect_until(
            lambda t: t[1] in (',',) or
            (t[0] == 'COMMENT' and t[1].lstrip().startswith('--')) or
            t[0] == 'EOF' or
            t[1] in ('FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING',
                      'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT', ';'))
        self.w(join_expr(toks))

    def _collect_case_expr(self, stops):
        """Collect tokens for a CASE sub-expression, using join_expr for spacing."""
        toks = []
        while not self.done() and self.pk()[1] not in stops and self.pk()[0] != 'EOF':
            if self.pk()[0] == 'COMMENT':
                # Flush collected tokens, output comment tab-aligned
                if toks:
                    self.w(' ' + join_expr(toks))
                    toks = []
                comment = self.eat()[1]
                last_line = self._last_line()
                tabs = self._calc_comment_tabs(last_line)
                self.w(tabs + comment)
                continue
            if self.pk()[1] == 'CASE':
                if toks:
                    self.w(' ' + join_expr(toks))
                    toks = []
                self.w(' ')
                self.format_case(self._current_case_ci)
                continue
            toks.append(self.eat())
        if toks:
            self.w(' ' + join_expr(toks))

    def format_case(self, ci):
        self._current_case_ci = ci
        self.w('CASE')
        self.eat()

        # Expression after CASE (before WHEN)
        self._collect_case_expr(('WHEN', 'END'))

        # WHEN / ELSE clauses
        while self.pk()[1] in ('WHEN', 'ELSE'):
            self.nl(ci + 1)
            if self.pk()[1] == 'WHEN':
                self.w('WHEN')
                self.eat()
                self._collect_case_expr(('WHEN', 'ELSE', 'END'))
            else:
                self.w('ELSE')
                self.eat()
                self._collect_case_expr(('END',))

        # END
        if self.pk()[1] == 'END':
            self.nl(ci + 1)
            self.w('END')
            self.eat()
            if self.pk()[1] == 'AS':
                self.w(' AS')
                self.eat()
                if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
                    self.w(' ' + self.eat()[1])

    # ── FROM ───────────────────────────────────────────────────

    def format_from_clause(self, base):
        ci = base + 1
        self.nl(ci)
        if self.pk()[1] == '(':
            self.format_from_subquery(base, ci)
        else:
            self.format_table_ref()

        while True:
            # Skip blank lines and standalone comments before checking for JOINs
            while not self.done() and self.pk()[0] in ('BLANK_LINE', 'COMMENT'):
                if self.pk()[0] == 'COMMENT':
                    self.nl(ci)
                    self.w(self.eat()[1])
                else:
                    self.eat()
            if self.pk()[1] == ',':
                self.eat()  # consume comma
                self.nl(ci - 1)
                self.w(', ')
                if self.pk()[1] == '(':
                    self.format_from_subquery(base, ci)
                else:
                    self.format_table_ref()
                continue
            if not self.is_join():
                break
            self.nl(ci)
            self.format_join(ci)

    def format_from_subquery(self, base, ci):
        """Handle subquery in FROM: ( SELECT ... ) alias"""
        self.w('(\n')
        self.eat()  # (
        self.format_select(ci, is_subquery=True)
        if self.pk()[1] == ')':
            self.w('\n')
            self.w(self.ind(ci) + ')')
            self.eat()  # )
        # Alias after subquery
        if self.pk()[1] == 'AS':
            self.w(' AS ')
            self.eat()
            if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
                self.w(self.eat()[1])
        elif self.pk()[0] in ('ID', 'QUOTED_ID'):
            self.w(' ' + self.eat()[1])

    def format_table_ref(self):
        if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
            self.w(self.eat()[1])
        while self.pk()[0] == 'DOT':
            self.w('.')
            self.eat()
            if self.pk()[0] in ('ID', 'KW', 'STAR', 'QUOTED_ID'):
                self.w(self.eat()[1])
        # Alias
        if self.pk()[1] == 'AS':
            self.w(' AS ')
            self.eat()
            if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
                self.w(self.eat()[1])
        elif (self.pk()[0] in ('ID', 'QUOTED_ID') and
              self.pk()[1] not in (
                  'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL',
                  'CROSS', 'ON', 'WHERE', 'GROUP', 'ORDER', 'HAVING',
                  'SET', 'SELECT', 'FROM', 'AND', 'OR', 'NOT', 'LIMIT',
                  'OFFSET', 'FETCH', 'UNION', 'EXCEPT', 'INTERSECT',
                  'RETURNING', 'LATERAL', 'INTO', ';')):
            self.w(' ' + self.eat()[1])

    def format_join(self, ci):
        while self.pk()[1] in ('LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS',
                                'OUTER'):
            self.w(self.eat()[1] + ' ')
        self.w('JOIN ')
        self.eat()
        # LATERAL comes after JOIN: LEFT JOIN LATERAL (...)
        if self.pk()[1] == 'LATERAL':
            self.w('LATERAL ')
            self.eat()
        self._skip_blank_lines()
        # Subquery in JOIN: JOIN (SELECT ...) alias
        if self.pk()[1] == '(' and self._lookahead_has_select_in_parens():
            self.format_from_subquery(ci - 1, ci)
        else:
            self.format_table_ref()

        # Handle trailing comment after table ref (before ON)
        had_comment = False
        if self.pk()[0] == 'COMMENT':
            comment = self.eat()[1]
            last_line = self._last_line()
            tabs = self._calc_comment_tabs(last_line)
            self.w(tabs + comment)
            had_comment = True
        # Skip standalone comments between table ref and ON
        while self.pk()[0] == 'COMMENT':
            self.nl(ci)
            self.w(self.eat()[1])
            had_comment = True

        if self.pk()[1] == 'ON':
            multi = self.check_on_has_and() or had_comment
            if had_comment:
                self.nl(ci + 1)
                self.w('ON')
            else:
                self.w(' ON')
            self.eat()
            # Handle parenthesized ON conditions: ON (cond AND cond)
            has_parens = self.pk()[1] == '('
            if has_parens:
                self.eat()  # consume opening '('
            if not multi:
                self.w(' ')
            if has_parens:
                self.w(' (')
            self.nl(ci + 1)
            self.format_on_conditions(ci + 1)
            if has_parens and self.pk()[1] == ')':
                self.nl(ci)
                self.w(')')
                self.eat()  # consume closing ')'

    def format_on_conditions(self, ci):
        def is_on_boundary(t):
            if t[1] in ('WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT',
                         'SELECT', 'FROM', ';') or t[0] in ('EOF', 'BLANK_LINE'):
                return True
            return False

        while not self.done():
            t = self.pk()
            if is_on_boundary(t) or t[1] == ')':
                break
            if self.is_join():
                break

            # Comment within ON conditions
            if t[0] == 'COMMENT':
                # Check if comment precedes a boundary
                j = 0
                while self.pk(j)[0] == 'COMMENT':
                    j += 1
                next_after = self.pk(j)
                if (is_on_boundary(next_after) or next_after[1] == ')' or
                        self._is_join_at(j)):
                    break  # leave for outer handler
                comment = self.eat()[1]
                last_line = self._last_line()
                tabs = self._calc_comment_tabs(last_line)
                self.w(tabs + comment)
                continue

            if t[1] in ('AND', 'OR'):
                self.nl(ci)
                self.w(t[1] + ' ')
                self.eat()
                continue

            toks = []
            depth = 0
            while not self.done():
                tt = self.pk()
                if tt[0] == 'COMMENT':
                    break
                if tt[1] == '(':
                    depth += 1
                elif tt[1] == ')':
                    if depth == 0:
                        break
                    depth -= 1
                if depth == 0:
                    if is_on_boundary(tt):
                        break
                    if self.is_join():
                        break
                    if tt[1] in ('AND', 'OR'):
                        break
                toks.append(self.eat())
            self.w(join_expr(toks))
            # Trailing inline comment (first comment after expression)
            if not self.done() and self.pk()[0] == 'COMMENT':
                comment = self.eat()[1]
                last_line = self._last_line()
                tabs = self._calc_comment_tabs(last_line)
                self.w(tabs + comment)

    # ── WHERE ──────────────────────────────────────────────────

    def format_where(self, base, is_subquery=False):
        ci = base + 1
        self.nl(ci)
        self.format_conditions(ci, inline_and=is_subquery)

    def format_conditions(self, ci, inline_and=False):
        between = False
        first_cond = True
        after_comment = False
        cond_depth = 0  # Track unclosed parens across expressions
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                if inline_and:
                    self.eat()
                    continue
                # Look ahead past blank lines to see what follows
                j = 1
                while self.pk(j)[0] == 'BLANK_LINE':
                    j += 1
                next_real = self.pk(j)
                # If AND/OR/(/COMMENT follows, or we haven't emitted
                # any condition yet, skip the blank line
                if (first_cond or
                        next_real[1] in ('AND', 'OR', '(') or
                        next_real[0] == 'COMMENT'):
                    self.eat()
                    continue
                break

            # ON CONFLICT boundary (for INSERT ... ON CONFLICT)
            if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
                break
            if t[1] in ('GROUP', 'ORDER', 'HAVING', 'LIMIT', 'UNION',
                         'EXCEPT', 'INTERSECT', 'RETURNING', ';') or t[0] == 'EOF':
                break
            if t[1] == ')':
                if cond_depth > 0:
                    cond_depth -= 1
                    self.nl(ci - 1)
                    self.w(self.eat()[1])
                    continue
                break

            # Standalone comment line within conditions
            if t[0] == 'COMMENT':
                # Check if this comment precedes a clause boundary
                j = 0
                while self.pk(j)[0] == 'COMMENT':
                    j += 1
                next_after = self.pk(j)
                if (next_after[1] in ('GROUP', 'ORDER', 'HAVING', 'LIMIT',
                                      'UNION', 'EXCEPT', 'INTERSECT',
                                      'RETURNING', ';') or
                        next_after[0] in ('EOF', 'BLANK_LINE') or
                        (next_after[1] == 'ON' and self.pk(j + 1)[1] == 'CONFLICT')):
                    break  # leave comment for outer handler
                comment = self.eat()[1]
                if not first_cond:
                    self.nl(ci)
                self.w(comment)
                first_cond = False
                after_comment = True
                continue

            # Nested SELECT without parens
            if t[1] == 'SELECT':
                self.w('\n')
                self.format_select(ci, is_subquery=True)
                break

            # AND handling
            if t[1] == 'AND':
                if between:
                    # AND is part of BETWEEN...AND — don't treat as separator.
                    # Keep between=True so the expression collector below
                    # consumes this AND as a regular token.
                    pass  # fall through to expression collector
                elif inline_and and not after_comment:
                    self.w(' AND ')
                    self.eat()
                    after_comment = False
                    continue
                else:
                    self.nl(ci)
                    self.w('AND ')
                    self.eat()
                    after_comment = False
                    continue

            # OR
            if t[1] == 'OR':
                if inline_and and not after_comment:
                    self.w(' OR ')
                else:
                    self.nl(ci)
                    self.w('OR ')
                self.eat()
                after_comment = False
                continue

            if after_comment:
                self.nl(ci)
            after_comment = False

            # Subquery in parens: ( SELECT ... )
            if t[1] == '(' and self.pk(1)[1] == 'SELECT':
                self.w(' (')
                self.eat()
                self.w('\n')
                self.format_select(ci + 1, is_subquery=True)
                self.nl(ci)
                if self.pk()[1] == ')':
                    self.w(')')
                    self.eat()
                continue

            # Collect expression tokens until next AND/OR/clause boundary
            expr_toks = []
            paren_depth = 0
            case_depth = 0
            in_list_pending = False
            while not self.done():
                tt = self.pk()
                if tt[0] == 'BLANK_LINE':
                    break
                # CASE at top-level paren depth: flush collected tokens
                # and delegate to format_case for proper WHEN/END indentation
                if tt[1] == 'CASE' and paren_depth == 0 and case_depth == 0:
                    self.w(join_expr(expr_toks))
                    if expr_toks:
                        self.w(' ')
                    expr_toks = []
                    self.format_case(ci)
                    continue
                # Comments inside CASE expressions stay inline;
                # outside CASE they signal an expression boundary
                if tt[0] == 'COMMENT':
                    if case_depth > 0:
                        expr_toks.append(self.eat())
                        continue
                    break
                # Track CASE/END nesting so AND inside CASE is not a boundary
                if tt[1] == 'CASE':
                    case_depth += 1
                elif tt[1] == 'END' and case_depth > 0:
                    case_depth -= 1
                # Detect IN ( ... ) with multiple values
                if paren_depth == 0 and case_depth == 0 and tt[1] == 'IN':
                    in_list_pending = True
                if in_list_pending and tt[1] == '(':
                    in_list_pending = False
                    # IN ( SELECT ... ) — subquery
                    if self.pk(1)[1] == 'SELECT':
                        self.w(join_expr(expr_toks))
                        expr_toks = []
                        self.w(' (')
                        self.eat()  # eat '('
                        self.w('\n')
                        self.format_select(ci + 1, is_subquery=True)
                        self.nl(ci)
                        if self.pk()[1] == ')':
                            self.w(')')
                            self.eat()
                        continue
                    # IN ( val, val, ... ) — value list
                    self.eat()  # eat '('
                    vals = self._collect_in_values()
                    if len(vals) > 3:
                        self.w(join_expr(expr_toks))
                        expr_toks = []
                        self.format_in_list_expanded(vals, ci)
                    else:
                        expr_toks.append(('LPAR', '('))
                        for vi, v in enumerate(vals):
                            if vi > 0:
                                expr_toks.append(('COMMA', ','))
                            expr_toks.extend(v)
                        expr_toks.append(('RPAR', ')'))
                        if self.pk()[1] == ')':
                            self.eat()
                    continue
                if tt[1] != 'IN':
                    in_list_pending = False
                if paren_depth == 0 and case_depth == 0:
                    if tt[1] in ('OR', 'GROUP', 'ORDER', 'HAVING',
                                 'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT',
                                 'RETURNING', ';',
                                 'SELECT') or tt[0] == 'EOF':
                        break
                    if tt[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
                        break
                    if tt[1] == 'AND':
                        if between:
                            between = False
                            expr_toks.append(self.eat())
                            continue
                        else:
                            break
                    if tt[1] == ')':
                        break
                if tt[1] == '(':
                    if self.pk(1)[1] == 'SELECT' and paren_depth == 0:
                        break
                    paren_depth += 1
                elif tt[1] == ')':
                    paren_depth -= 1
                if tt[1] == 'BETWEEN':
                    between = True
                expr_toks.append(self.eat())

            # Carry forward unclosed parens to the outer depth tracker
            cond_depth += paren_depth

            self.w(join_expr(expr_toks))
            if expr_toks:
                first_cond = False

            # Trailing inline comment (first comment after expression)
            if not self.done() and self.pk()[0] == 'COMMENT':
                comment = self.eat()[1]
                last_line = self._last_line()
                tabs = self._calc_comment_tabs(last_line)
                self.w(tabs + comment)
                after_comment = True

    def _collect_in_values(self):
        """Collect value groups inside IN (...), returns list of token lists.

        Handles nested (SELECT ...) subqueries within value lists by
        collecting the subquery tokens (including parens) as a single
        value group.
        """
        vals = []
        current = []
        depth = 0
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if t[1] == '(':
                # Detect (SELECT ...) subquery inside the value list
                if depth == 0 and self.pk(1)[1] == 'SELECT':
                    if current:
                        vals.append(current)
                        current = []
                    # Collect the entire subquery as one value group
                    sub_toks = [self.eat()]  # (
                    sub_depth = 1
                    while not self.done() and sub_depth > 0:
                        st = self.pk()
                        if st[1] == '(':
                            sub_depth += 1
                        elif st[1] == ')':
                            sub_depth -= 1
                        sub_toks.append(self.eat())
                    vals.append(sub_toks)
                    continue
                depth += 1
            elif t[1] == ')':
                if depth == 0:
                    break
                depth -= 1
            if t[1] == ',' and depth == 0:
                self.eat()
                if current:
                    vals.append(current)
                    current = []
                continue
            current.append(self.eat())
        if current:
            vals.append(current)
        return vals

    def format_in_list_expanded(self, vals, ci):
        """Format IN (...) values expanded one per line."""
        self.w(' (')
        for vi, v in enumerate(vals):
            self.nl(ci + 1)
            if vi > 0:
                self.w(', ')
            self.w(join_expr(v))
        self.nl(ci)
        self.w(')')
        if not self.done() and self.pk()[1] == ')':
            self.eat()

    # ── Item list (GROUP BY, ORDER BY) ─────────────────────────

    def format_item_list(self, ci):
        first = True
        while not self.done():
            t = self.pk()
            if t[1] in ('HAVING', 'ORDER', 'LIMIT', 'UNION', 'EXCEPT',
                         'INTERSECT', ';', 'WHERE', 'FROM', 'SELECT',
                         ')', 'INSERT', 'UPDATE', 'DELETE',
                         'RETURNING', 'CREATE') or t[0] == 'EOF':
                break
            if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
                break
            if t[0] == 'BLANK_LINE':
                if first:
                    self.eat()
                    continue
                break
            if t[0] == 'COMMENT':
                break
            if t[1] == 'GROUP' and self.pk(1)[1] == 'BY':
                break

            if t[1] == ',':
                self.eat()
                # Trailing comment after comma
                if self.pk()[0] == 'COMMENT':
                    comment = self.eat()[1]
                    last_line = self._last_line()
                    tabs = self._calc_comment_tabs(last_line)
                    self.w(tabs + comment)
                self.nl(ci)
                self.w(', ')
                first = False
                continue

            if first:
                self.nl(ci)
                first = False

            def _item_stop(t):
                if t[1] in (',', 'HAVING', 'ORDER', 'LIMIT', 'UNION',
                             'EXCEPT', 'INTERSECT', ';', 'WHERE',
                             'FROM', 'SELECT', 'INSERT', 'UPDATE',
                             'DELETE', 'RETURNING', 'CREATE'):
                    return True
                if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
                    return True
                return t[0] in ('EOF', 'COMMENT')
            toks = self.collect_until(_item_stop)
            self.w(join_expr(toks))

    # ── UPDATE ─────────────────────────────────────────────────

    def format_update(self):
        self.w('UPDATE')
        self.eat()

        self.nl(1)
        self.format_table_ref()

        if self.pk()[1] == 'SET':
            self.nl(0)
            self.w('SET')
            self.eat()
            self.format_set_clause()

        if self.pk()[1] == 'FROM':
            self.nl(0)
            self.w('FROM')
            self.eat()
            self.format_from_clause(0)

        if self.pk()[1] == 'WHERE':
            self.nl(0)
            self.w('WHERE')
            self.eat()
            self.nl(1)
            self.format_conditions(1, inline_and=False)

        if self.pk()[1] == 'RETURNING':
            self.nl(0)
            self.w('RETURNING')
            self.eat()
            self.format_item_list(1)

        if not self.done() and self.pk()[1] == ';':
            self.w(';')
            self.eat()

    def format_set_clause(self):
        first = True
        while not self.done():
            t = self.pk()
            if t[1] in ('WHERE', 'FROM', ';') or t[0] in ('EOF', 'BLANK_LINE'):
                break

            if t[0] == 'COMMENT':
                comment = self.eat()[1]
                self.nl(1)
                self.w(comment)
                continue

            if t[1] == ',':
                self.eat()
                if self.pk()[0] == 'COMMENT':
                    comment = self.eat()[1]
                    last_line = self._last_line()
                    tabs = self._calc_comment_tabs(last_line)
                    self.w(tabs + comment)
                self.nl(1)
                self.w(', ')
                first = False
                continue

            if first:
                self.nl(1)
                first = False

            toks = self.collect_until(
                lambda t: t[1] in (',', 'WHERE', 'FROM', ';') or
                t[0] in ('EOF', 'COMMENT'))
            self.w(join_expr(toks))

    # ── DELETE ─────────────────────────────────────────────────

    def format_delete(self):
        self.w('DELETE')
        self.eat()
        if self.pk()[1] == 'FROM':
            self.w(' FROM')
            self.eat()

        self.nl(1)
        if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
            self.w(self.eat()[1])

        if self.pk()[1] == 'WHERE':
            self.nl(0)
            self.w('WHERE')
            self.eat()
            self.nl(1)
            toks = self.collect_until(
                lambda t: t[1] == ';' or t[0] == 'EOF')
            self.w(join_expr(toks))

        if self.pk()[1] == ';':
            self.w(';')
            self.eat()

    # ── INSERT ──────────────────────────────────────────────────

    def format_insert(self):
        self.w('INSERT')
        self.eat()
        if self.pk()[1] == 'INTO':
            self.w(' INTO')
            self.eat()

        # Table name
        self.w(' ')
        self.format_table_ref()

        # Column list in parens
        if self.pk()[1] == '(':
            self.w(' (')
            self.eat()
            self.format_item_list(1)
            self.nl(0)
            if self.pk()[1] == ')':
                self.w(')')
                self.eat()

        # VALUES or SELECT
        if self.pk()[1] == 'SELECT':
            self.w('\n')
            self.format_select(0)
        elif self.pk()[1] == 'VALUES':
            self.nl(0)
            self.w('VALUES')
            self.eat()
            self.format_values()

        # ON CONFLICT
        if self.pk()[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
            self.nl(0)
            self.w('ON CONFLICT')
            self.eat()  # ON
            self.eat()  # CONFLICT
            toks = self.collect_until(
                lambda t: t[1] == ';' or t[0] == 'EOF')
            if toks:
                self.w(' ' + join_expr(toks))

        # RETURNING
        if self.pk()[1] == 'RETURNING':
            self.nl(0)
            self.w('RETURNING')
            self.eat()
            self.format_item_list(1)

        if not self.done() and self.pk()[1] == ';':
            self.w(';')
            self.eat()

    def format_values(self):
        while not self.done():
            if self.pk()[1] == '(':
                self.w(' (')
                self.eat()
                toks = self.collect_until(lambda t: t[1] == ')')
                self.w(join_expr(toks))
                if self.pk()[1] == ')':
                    self.w(')')
                    self.eat()
            if self.pk()[1] == ',':
                self.eat()
                self.nl(0)
                self.w(',')
            else:
                break

    # ── WITH ────────────────────────────────────────────────────

    def format_with(self):
        self.w('WITH')
        self.eat()

        if self.pk()[1] == 'RECURSIVE':
            self.w(' RECURSIVE')
            self.eat()

        first_cte = True
        while not self.done():
            # Skip blank lines between CTEs
            while not self.done() and self.pk()[0] == 'BLANK_LINE':
                self.eat()

            if self.pk()[1] in ('SELECT', 'INSERT', 'UPDATE', 'DELETE',
                                 ';') or self.pk()[0] == 'EOF':
                break

            # Before subsequent CTE: collect inter-CTE comments
            if not first_cte:
                # Collect comments between CTEs
                while not self.done() and self.pk()[0] in ('BLANK_LINE', 'COMMENT'):
                    if self.pk()[0] == 'COMMENT':
                        self.w('\n')
                        self.w(self.eat()[1])
                    else:
                        self.eat()
                self.w('\n')
            else:
                self.w(' ')
                first_cte = False

            # CTE name
            if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
                self.w(self.eat()[1])

            # Optional column list: name (col1, col2)
            if self.pk()[1] == '(' and self.pk(1)[1] != 'SELECT':
                # Check if this is a column list (no SELECT inside)
                # vs AS ( SELECT ... )
                j = 1
                depth = 1
                is_col_list = True
                while depth > 0:
                    j += 1
                    if self.pk(j)[1] == '(':
                        depth += 1
                    elif self.pk(j)[1] == ')':
                        depth -= 1
                    elif self.pk(j)[0] == 'EOF':
                        is_col_list = False
                        break
                if is_col_list:
                    self.w(' (')
                    self.eat()  # (
                    toks = self.collect_until(lambda t: t[1] == ')')
                    self.w(join_expr(toks))
                    if self.pk()[1] == ')':
                        self.w(')')
                        self.eat()

            # AS keyword
            if self.pk()[1] == 'AS':
                self.w(' AS')
                self.eat()

            # Opening paren with SELECT inside
            if self.pk()[1] == '(':
                self.w(' (')
                self.eat()

                # Skip blank lines
                while not self.done() and self.pk()[0] == 'BLANK_LINE':
                    self.eat()

                if self.pk()[1] == 'SELECT':
                    self.w('\n')
                    self.format_select(1)
                else:
                    # Fallback: collect until matching closing paren
                    toks = self.collect_until(lambda t: t[1] == ')')
                    self.w(join_expr(toks))

                # Skip blank lines before closing paren
                while not self.done() and self.pk()[0] == 'BLANK_LINE':
                    self.eat()

                if self.pk()[1] == ')':
                    self.w('\n)')
                    self.eat()
            else:
                # No paren — unexpected syntax, bail to raw
                break

            # After CTE body: attach comma to closing paren if more CTEs follow
            while not self.done() and self.pk()[0] == 'BLANK_LINE':
                self.eat()
            if self.pk()[1] == ',':
                self.w(',')
                self.eat()

        # Skip blank lines before main statement
        while not self.done() and self.pk()[0] == 'BLANK_LINE':
            self.eat()

        # Main statement after WITH
        if not self.done() and self.pk()[1] in ('SELECT', 'INSERT',
                                                  'UPDATE', 'DELETE'):
            self.w('\n')
            self.format_stmt()


    # ── CREATE TABLE ... AS ─────────────────────────────────────

    def format_create(self):
        # CREATE TABLE
        self.w('CREATE')
        self.eat()
        if self.pk()[1] == 'TABLE':
            self.w(' TABLE')
            self.eat()
        # Optional IF NOT EXISTS
        if self.pk()[1] == 'IF':
            self.w(' IF')
            self.eat()
            if self.pk()[1] == 'NOT':
                self.w(' NOT')
                self.eat()
            if self.pk()[1] == 'EXISTS':
                self.w(' EXISTS')
                self.eat()

        # Table name (indented, no alias parsing)
        self.nl(1)
        while not self.done() and self.pk()[0] == 'BLANK_LINE':
            self.eat()
        if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
            self.w(self.eat()[1])
        while not self.done() and self.pk()[0] == 'DOT':
            self.w('.')
            self.eat()
            if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
                self.w(self.eat()[1])

        # After table name, expect AS or ; — if something unexpected, fall back
        if not self.done() and self.pk()[1] not in ('AS', ';') and self.pk()[0] not in ('EOF', 'BLANK_LINE') and self.pk()[1] != 'SELECT':
            # Unexpected token (e.g. hyphen in table name) — output rest raw
            toks = []
            while not self.done():
                t = self.pk()
                if t[0] == 'BLANK_LINE':
                    self.eat()
                    continue
                if t[1] == ';':
                    toks.append(self.eat())
                    break
                if t[1] in ('SELECT', 'UPDATE', 'DELETE', 'INSERT',
                             'CREATE', 'WITH'):
                    break
                toks.append(self.eat())
            if toks:
                self.w(join_expr(toks))
            return

        # AS keyword
        if not self.done() and self.pk()[1] == 'AS':
            self.w(' AS')
            self.eat()

        # If followed by SELECT, format it indented
        if not self.done() and self.pk()[1] == 'SELECT':
            self.w('\n')
            self.format_select(1)

        if not self.done() and self.pk()[1] == ';':
            self.w(';')
            self.eat()


    # ── DO $$ ... $$ (PL/pgSQL passthrough) ────────────────────

    def format_do_block(self):
        self.w(self.eat()[1])  # DO
        self.w(' ')
        self.w(self.eat()[1])  # DOLLAR_BODY (entire $$...$$)
        if not self.done() and self.pk()[1] == ';':
            self.w(';')
            self.eat()


def format_sql(sql):
    """Format SQL, returning original unchanged if any error occurs."""
    try:
        tokens = tokenize(sql)
        f = Formatter(tokens)
        return f.format()
    except Exception:
        return sql


def main():
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        with open(filepath, 'r') as f:
            sql = f.read()
        result = format_sql(sql)
        with open(filepath, 'w') as f:
            f.write(result)
    else:
        sql = sys.stdin.read()
        result = format_sql(sql)
        sys.stdout.write(result)


if __name__ == '__main__':
    main()
