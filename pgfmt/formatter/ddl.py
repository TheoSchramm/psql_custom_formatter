"""CREATE TABLE / VIEW / INDEX, DO blocks, utility statements (ALTER, CREATE OPERATOR, ...), EXPLAIN."""

from __future__ import annotations
from ..constants import (
    INDENT, UTILITY_KWS, _UTILITY_NAME_AFTER, _UTILITY_NAME_SKIP, _UTILITY_NEVER_NAME,
    _UTILITY_TYPE_WORDS,
)
from ..nodes import RawStatement, WithStatement
from ..tokenizer import join_expr


class DdlFormatterMixin:
    """CREATE TABLE / VIEW / INDEX, DO blocks, utility statements (ALTER, CREATE OPERATOR, ...), EXPLAIN."""

    # Keywords to uppercase inside column constraints and table constraints
    _CONSTRAINT_KWS = frozenset({
        'NULL', 'NOT', 'DEFAULT', 'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES',
        'UNIQUE', 'CHECK', 'CONSTRAINT', 'ON', 'DELETE', 'UPDATE', 'CASCADE',
        'RESTRICT', 'NO', 'ACTION', 'GENERATED', 'ALWAYS', 'IDENTITY',
        'STORED', 'WITH', 'TIME', 'ZONE', 'WITHOUT', 'ONLY', 'MATCH',
        'PARTIAL', 'SIMPLE', 'FULL', 'DEFERRED', 'IMMEDIATE', 'DEFERRABLE',
        'INITIALLY', 'USING', 'INDEX', 'WHERE', 'COLLATE', 'NULLS',
        'FIRST', 'LAST', 'ASC', 'DESC', 'LIKE', 'INCLUDING', 'EXCLUDING',
        'ALL', 'DEFAULTS', 'COMMENTS', 'INDEXES', 'STORAGE', 'STATISTICS',
        'CONSTRAINTS', 'IDENTITY', 'GENERATED', 'COMPRESSION',
    })

    def _format_constraint_tokens(self, toks):
        """Render constraint tokens with SQL keywords uppercased.

        Constraint keywords are emitted as KW type so join_expr never
        suppresses the space before '(' — which it would for ID tokens
        (to handle function calls). This gives 'PRIMARY KEY (id)' and
        'CHECK (expr)' instead of 'PRIMARY KEY(id)'.
        """
        result = []
        for t in toks:
            if t[0] == 'KW':
                result.append(t)
            elif t[0] == 'ID' and t[1].upper() in self._CONSTRAINT_KWS:
                result.append(('KW', t[1].upper()) + t[2:])
            else:
                result.append(t)
        return join_expr(result)

    def format_create_table(self, stmt):
        self.w('CREATE ' + (stmt.prefix + ' ' if stmt.prefix else '') + 'TABLE')
        if stmt.if_not_exists:
            self.w(' IF NOT EXISTS')
        self.nl(1)
        name = stmt.table_name
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(name)

        # Column name padding: align type names to a consistent column
        pad_to = max((len(col.name) for col in stmt.columns), default=0) + 1

        constraint_leading = stmt.constraint_leading or [[] for _ in stmt.table_constraints]
        constraint_trailing = stmt.constraint_trailing or [None for _ in stmt.table_constraints]
        all_items = (
            [(True, col, col.leading_comments, col.trailing_comment.text if col.trailing_comment else None)
             for col in stmt.columns] +
            [(False, tc, constraint_leading[k], constraint_trailing[k])
             for k, tc in enumerate(stmt.table_constraints)]
        )
        # a synthetic empty slot only carries comments that sat right before ')'
        real_idx = [k for k, it in enumerate(all_items) if it[0] or it[1]]
        last_real = real_idx[-1] if real_idx else -1
        self.w('\n(')
        for i, (is_col, item, leading, trailing) in enumerate(all_items):
            for c in leading:
                self.w('\n' + INDENT + c)
            if not is_col and not item:
                continue
            self.w('\n' + INDENT)
            if is_col:
                self.w(item.name.ljust(pad_to))
                self.w(item.type_str)
                if item.constraint_tokens:
                    self.w(' ' + self._format_constraint_tokens(item.constraint_tokens))
            else:
                self.w(self._format_constraint_tokens(item))
            if i != last_real:
                self.w(',')
            if trailing:
                last_line = self._last_line()
                self.w(self._comment_tabs(last_line) + trailing)
        self.w('\n)')
        if stmt.tail:
            self._write_tail_lines(self._render_token_lines(self._utility_prepare(stmt.tail)), 0)
        if stmt._has_semicolon:
            self._semi()

    def format_create_table_as(self, stmt):
        self.w('CREATE ' + (stmt.prefix + ' ' if stmt.prefix else '') + 'TABLE')
        if stmt.if_not_exists:
            self.w(' IF NOT EXISTS')
        self.nl(1)
        name = stmt.table_name
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(name)
        if stmt.raw_fallback is not None:
            # PARTITION OF / OF type / ON COMMIT ... AS / ...: the rest as a utility tail
            toks = list(stmt.raw_fallback)
            semi = bool(toks) and toks[-1][1] == ';'
            if semi:
                toks = toks[:-1]
            lines = self._render_token_lines(self._utility_prepare(toks))
            if lines:
                self.w(' ' + lines[0])
            for ln in lines[1:]:
                self.nl(1)
                self.w(ln)
            if semi:
                self._semi()
            return
        if stmt.options:
            self._write_tail_lines(self._render_token_lines(self._utility_prepare(stmt.options)), 1)
        self._write_as()
        if stmt.with_clause:
            self.w('\n')
            self.format_with(stmt.with_clause)
        elif stmt.select:
            self.w('\n')
            self.format_select(stmt.select, 1)
        elif stmt.body_raw:
            self.nl(1)
            self._write_lines(self._render_token_lines(self._utility_prepare(stmt.body_raw)), 1)
        if stmt.suffix:
            self.nl(0)
            self.w(join_expr(self._utility_prepare(stmt.suffix)))
        if stmt._has_semicolon and not (stmt.select and stmt.select._has_semicolon):
            self._semi()

    # ── Utility / EXPLAIN / CREATE VIEW / MERGE ───────────────────

    @staticmethod
    def _utility_prepare(toks):
        """Uppercase keywords / types and mark object names, for utility statements."""
        out = []
        name_next = False
        paren_stack = []
        n = len(toks)
        for idx, t in enumerate(toks):
            typ, val = t[0], t[1]
            nxt = toks[idx + 1] if idx + 1 < n else ('EOF', '')
            prev = out[-1] if out else ('', '')
            new = t
            consumed_name = False
            if typ in ('ID', 'KW'):
                up = val.upper()
                if prev[0] == 'DOT' or nxt[0] == 'DOT':
                    new = ('NAME', val) + t[2:]
                elif (typ == 'ID' and name_next and up not in _UTILITY_NAME_SKIP
                        and up not in _UTILITY_NEVER_NAME
                        and not (prev[1] == 'TYPE' and val in _UTILITY_TYPE_WORDS)):
                    new = ('NAME', val) + t[2:]
                    consumed_name = True
                elif (typ == 'ID' and prev[0] in ('LPAR', 'COMMA') and nxt[0] in ('COMMA', 'RPAR')
                        and up not in ('TRUE', 'FALSE', 'NULL', 'DEFAULT', 'VERBOSE', 'ANALYZE',
                                       'ANALYSE', 'FREEZE', 'FULL')):
                    new = ('NAME', val) + t[2:]  # bare list element: (key, data)
                elif (typ == 'ID' and up == 'TYPE' and nxt[0] not in ('COMMA', 'RPAR', 'EOF')
                        and nxt[1] != '=' and (prev[0] == 'NAME' or prev[1] == 'DATA')):
                    new = ('KW', 'TYPE') + t[2:]  # ALTER COLUMN c TYPE ... / SET DATA TYPE
                elif typ == 'ID' and up == 'TYPE' and prev[1] in ('CREATE', 'DROP', 'ALTER'):
                    new = ('KW', 'TYPE') + t[2:]  # CREATE TYPE / DROP TYPE / ALTER TYPE
                elif typ == 'ID' and up in UTILITY_KWS:
                    new = ('KW', up) + t[2:]
                elif typ == 'ID' and val in _UTILITY_TYPE_WORDS:
                    new = ('KW', up) + t[2:]
                if typ == 'ID' and name_next and prev[1] in ('FUNCTION', 'PROCEDURE') and nxt[1] == '(':
                    new = t  # CREATE FUNCTION f(...): a call-shaped name, keep tight
                # decide whether the *next* word is an object name
                if consumed_name:
                    name_next = False
                elif up in _UTILITY_NAME_AFTER and new[0] == 'KW':
                    name_next = True
                elif not (name_next and up in _UTILITY_NAME_SKIP):
                    name_next = False
            else:
                name_next = False if typ not in ('COMMENT',) else name_next
            out.append(new)
        return out

    def _render_token_lines(self, toks, prepare=False):
        """Join tokens into output lines without ever letting a `--` comment
        swallow code: a line comment ends its line, standalone comments get their own."""
        if prepare:
            toks = self._utility_prepare(toks)
        lines = []
        seg = []

        def flush(comment=None, own_line=False):
            nonlocal seg
            text = join_expr(seg) if seg else ''
            if comment is not None:
                if own_line:
                    if text:
                        lines.append(text)
                    lines.append(comment)
                else:
                    lines.append((text + self._comment_gap(text) if text else '') + comment)
            elif text:
                lines.append(text)
            seg = []

        for t in toks:
            if t[0] == 'BLANK_LINE':
                continue
            if t[0] == 'COMMENT':
                if t[1].lstrip().startswith('--'):
                    flush(t[1], own_line=bool(len(t) > 2 and t[2]) or not seg)
                else:
                    seg.append(t)
                continue
            seg.append(t)
        flush()
        return lines

    def _comment_gap(self, text):
        return self._comment_tabs(text) if hasattr(self, '_comment_tabs') else '\t'

    def _write_lines(self, lines, base=0):
        for i, ln in enumerate(lines):
            if i > 0:
                self.nl(base)
            self.w(ln)

    def _end_statement(self, lines_end_in_comment, has_semicolon, base=0):
        if has_semicolon:
            if lines_end_in_comment:
                self.nl(base)
            self._semi()

    def format_utility(self, stmt):
        toks = self._utility_prepare(stmt.tokens)
        lines = None
        if stmt.kind == 'ALTER' and len(toks) > 2 and toks[1][1].upper() == 'TABLE':
            lines = self._alter_table_lines(toks)
        elif stmt.kind == 'CREATE':
            lines = self._definition_list_lines(toks)
        if lines is None:
            lines = self._render_token_lines(toks)
        self._write_lines(lines)
        if stmt.atomic_body is not None:
            self.nl(0)
            self.w('BEGIN ATOMIC')
            for body_stmt in stmt.atomic_body:
                self.nl(1)
                if isinstance(body_stmt, str):  # comment
                    self.w(body_stmt)
                    continue
                sub = type(self)()
                sub.format_statement(body_stmt)
                text = ''.join(sub.out).rstrip()  # (each body statement keeps its own `;`)
                self.w(('\n' + INDENT).join(text.split('\n')))
            self.nl(0)
            self.w('END')
            if stmt._has_semicolon:
                self._semi()
            return
        self._end_statement(bool(lines) and '--' in lines[-1] and self._ends_with_line_comment(stmt.tokens),
                            stmt._has_semicolon)

    @staticmethod
    def _ends_with_line_comment(toks):
        for t in reversed(toks):
            if t[0] == 'BLANK_LINE':
                continue
            return t[0] == 'COMMENT' and t[1].lstrip().startswith('--')
        return False

    _ALTER_ACTION_STARTERS = frozenset({
        'ADD', 'DROP', 'ALTER', 'RENAME', 'SET', 'RESET', 'OWNER', 'ENABLE',
        'DISABLE', 'VALIDATE', 'INHERIT', 'NO', 'CLUSTER', 'ATTACH', 'DETACH',
        'REPLICA', 'FORCE', 'OF', 'NOT', 'SET',
    })

    def _alter_table_lines(self, toks):
        """ALTER TABLE name <action>[, <action>...]: one action per line when there are several."""
        i = 2
        # IF EXISTS / ONLY
        while i < len(toks) and toks[i][1].upper() in ('IF', 'EXISTS', 'ONLY'):
            i += 1
        # table name (possibly schema.name, optionally followed by '*')
        while i < len(toks) and (toks[i][0] in ('NAME', 'ID', 'QUOTED_ID', 'DOT', 'STAR')):
            i += 1
        head, rest = toks[:i], toks[i:]
        actions = []
        cur = []
        depth = 0
        skip = 0
        for idx, t in enumerate(rest):
            if skip:
                skip -= 1
                continue
            if t[1] in ('(', '['):
                depth += 1
            elif t[1] in (')', ']'):
                depth -= 1
            if depth == 0 and t[0] == 'COMMA':
                nxt = rest[idx + 1] if idx + 1 < len(rest) else None
                if nxt is not None and nxt[0] == 'COMMENT' and not (len(nxt) > 2 and nxt[2]):
                    cur.append(nxt)  # `, -- note` trails the action before the comma
                    skip = 1
                actions.append(cur)
                cur = []
                continue
            cur.append(t)
        if cur:
            actions.append(cur)
        if len(actions) < 2:
            return None
        out = self._render_token_lines(head)
        for k, act in enumerate(actions):
            # standalone comments in front of an action go on their own lines above it
            lead = 0
            while lead < len(act) and act[lead][0] == 'COMMENT' and len(act[lead]) > 2 and act[lead][2]:
                out.append(INDENT + act[lead][1])
                lead += 1
            sub = self._render_token_lines(act[lead:])
            for j, ln in enumerate(sub):
                if j == 0:
                    out.append(INDENT + (', ' if k > 0 else '') + ln)
                else:
                    out.append(INDENT + ('  ' if k > 0 else '') + ln)
        return out

    def _definition_list_lines(self, toks):
        """CREATE OPERATOR / AGGREGATE / COLLATION / TYPE name ( key = value, ... ):
        one option per line, leading commas, keys uppercased, `)` on its own line.
        Returns None when the statement doesn't end in such a list."""
        # the list is the top-level paren group that closes the statement
        end = len(toks) - 1
        while end >= 0 and toks[end][0] in ('COMMENT', 'BLANK_LINE'):
            end -= 1
        if end < 0 or toks[end][1] != ')':
            return None
        depth = 0
        start = None
        for k in range(end, -1, -1):
            if toks[k][1] in (')', ']'):
                depth += 1
            elif toks[k][1] in ('(', '['):
                depth -= 1
                if depth == 0:
                    start = k
                    break
        if not start:
            return None
        head, body, tail = toks[:start + 1], toks[start + 1:end], toks[end:]
        elements, cur, depth, skip = [], [], 0, 0
        for idx, t in enumerate(body):
            if skip:
                skip -= 1
                continue
            if t[1] in ('(', '['):
                depth += 1
            elif t[1] in (')', ']'):
                depth -= 1
            if depth == 0 and t[0] == 'COMMA':
                nxt = body[idx + 1] if idx + 1 < len(body) else None
                if nxt is not None and nxt[0] == 'COMMENT' and not (len(nxt) > 2 and nxt[2]):
                    cur.append(nxt)  # `, -- note` trails the option before the comma
                    skip = 1
                elements.append(cur)
                cur = []
                continue
            cur.append(t)
        elements.append(cur)

        def code(el):
            return [t for t in el if t[0] not in ('COMMENT', 'BLANK_LINE')]
        # every option is `key = value` or a bare flag (HASHES, MERGES), at least one `=`
        if not any(len(code(el)) > 2 and code(el)[1][1] == '=' for el in elements):
            return None
        for el in elements:
            c = code(el)
            if not c or c[0][0] not in ('ID', 'KW', 'NAME') or (len(c) > 1 and c[1][1] != '='):
                return None
        out = self._render_token_lines(head)
        for k, el in enumerate(elements):
            lead = 0
            while lead < len(el) and el[lead][0] == 'COMMENT' and len(el[lead]) > 2 and el[lead][2]:
                out.append(INDENT + el[lead][1])
                lead += 1
            el = el[lead:]
            if el and el[0][0] in ('ID', 'KW', 'NAME'):
                el = [('KW', el[0][1].upper()) + el[0][2:]] + el[1:]
            for j, ln in enumerate(self._render_token_lines(el)):
                out.append(INDENT + ((', ' if k > 0 else '') if j == 0 else ('  ' if k > 0 else '')) + ln)
        out.extend(self._render_token_lines(tail))
        return out

    def format_explain(self, stmt):
        self.w('EXPLAIN')
        if stmt.options:
            opts = []
            for t in stmt.options:
                if t[0] in ('ID', 'KW'):
                    opts.append(('KW', t[1].upper()) + t[2:])
                else:
                    opts.append(t)
            self.w(' ' + join_expr(opts))
        inner = stmt.statement
        if isinstance(inner, RawStatement) and not inner.tokens:
            if stmt._has_semicolon:
                self._semi()
            return
        self.nl(0)
        self.format_statement(inner)
        if stmt._has_semicolon and not getattr(inner, '_has_semicolon', False):
            self._semi()

    def _write_tail_lines(self, lines, level):
        """Continue the current line with lines[0]; further lines at `level`."""
        if lines:
            self.w(' ' + lines[0])
        for ln in lines[1:]:
            self.nl(level)
            self.w(ln)

    def _write_as(self, level=1):
        """` AS` before a view / CREATE TABLE AS query; never after a `--` comment."""
        if self._line_ends_in_comment(self._last_line()):
            self.nl(level)
            self.w('AS')
        else:
            self.w(' AS')

    def format_create_view(self, stmt):
        head = 'CREATE ' + (stmt.prefix + ' ' if stmt.prefix else '') + 'VIEW'
        if stmt.if_not_exists:
            head += ' IF NOT EXISTS'
        self.w(head)
        self.nl(1)
        self.w(stmt.name)
        if stmt.columns:
            self.w(' (' + join_expr(stmt.columns) + ')')
        if stmt.options:
            self._write_tail_lines(self._render_token_lines(self._utility_prepare(stmt.options)), 1)
        self._write_as()
        self.w('\n')
        body = stmt.body
        if isinstance(body, WithStatement):
            self.format_with(body)
        else:
            self.format_select(body, 1)
        inner_semi = getattr(body, '_has_semicolon', False)
        if stmt.suffix:
            self.nl(0)
            self.w(join_expr(self._utility_prepare(stmt.suffix)))
        if stmt._has_semicolon and not (inner_semi and not stmt.suffix):
            self._semi()

    def format_create_index(self, stmt):
        toks = list(stmt.raw_rest)
        semi = bool(toks) and toks[-1][1] == ';'
        if semi:
            toks.pop()
        lines = self._render_token_lines(self._utility_prepare(toks))
        self._write_lines(lines)
        self._end_statement(self._ends_with_line_comment(toks), semi)

    def format_do_block(self, stmt):
        self.w('DO ')
        if stmt.language_before:
            self.w('LANGUAGE ' + stmt.language_before + ' ')
        self.w(stmt.dollar_body)
        if stmt.language_after:
            self.w(' LANGUAGE ' + stmt.language_after)
        if stmt._has_semicolon:
            self._semi()
