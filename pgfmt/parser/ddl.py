"""CREATE TABLE / VIEW / INDEX, DO blocks, utility statements, EXPLAIN, raw fallback."""

from __future__ import annotations
from ..constants import SqlSyntaxError, _STATEMENT_START_KWS, _TCL_STARTERS
from ..nodes import (
    ColumnDef, Comment, CreateIndexStatement, CreateTableAsStatement, CreateTableStatement,
    CreateViewStatement, DoBlock, ExplainStatement, RawStatement, UtilityStatement,
    WithStatement,
)
from ..tokenizer import ascii_upper, join_expr


class DdlParserMixin:
    """CREATE TABLE / VIEW / INDEX, DO blocks, utility statements, EXPLAIN, raw fallback."""

    _CREATE_MODIFIERS = frozenset({
        'OR', 'REPLACE', 'TEMP', 'TEMPORARY', 'UNLOGGED', 'GLOBAL', 'LOCAL',
        'UNIQUE', 'MATERIALIZED', 'RECURSIVE',
    })

    def _scan_create(self):
        """Look past CREATE's modifiers (OR REPLACE, TEMP, UNIQUE, ...) without
        consuming anything. Returns (modifier words, object-kind word)."""
        mods = []
        j = 1
        while self.pk(j)[0] in ('ID', 'KW') and self.pk(j)[1].upper() in self._CREATE_MODIFIERS:
            mods.append(self.pk(j)[1].upper())
            j += 1
        kind = self.pk(j)[1].upper() if self.pk(j)[0] in ('ID', 'KW') else ''
        return mods, kind

    def parse_create(self):
        mods, kind = self._scan_create()
        if kind == 'VIEW':
            return self.parse_create_view(mods)
        if kind not in ('TABLE', 'INDEX'):
            return self.parse_utility()  # CREATE FUNCTION / TRIGGER / SEQUENCE / ...
        self.eat()  # CREATE
        for _ in mods:
            self.eat()
        unique = 'UNIQUE' in mods
        prefix = ' '.join(m for m in mods if m != 'UNIQUE')
        if self.pk()[1] == 'INDEX':
            # collect rest as raw
            raw = [('KW', 'CREATE')]
            if unique:
                raw = [('KW', 'CREATE'), ('KW', 'UNIQUE')]
            raw.append(self.eat())  # INDEX
            while not self.done():
                t = self.pk()
                if t[0] in ('EOF',):
                    break
                if t[1] == ';':
                    raw.append(self.eat())
                    break
                raw.append(self.eat())
            return CreateIndexStatement(unique=unique, raw_rest=raw)
        # CREATE TABLE
        if self.pk()[1] == 'TABLE':
            self.eat()
        stmt = CreateTableAsStatement(table_name='', prefix=prefix)
        if self.pk()[1] == 'IF':
            self.eat()
            if self.pk()[1] == 'NOT':
                self.eat()
            if self.pk()[1] == 'EXISTS':
                self.eat()
            stmt.if_not_exists = True
        self.skip_blanks()
        # table name
        while self.pk()[0] == 'BLANK_LINE':
            self.eat()
        if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
            stmt.table_name = self.eat()[1]
        else:
            raise SqlSyntaxError('CREATE TABLE without a table name')  # (kept verbatim)
        if self.pk()[0] == 'DOT':
            self.eat()
            stmt.schema = stmt.table_name
            stmt.table_name = self.eat()[1] if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID') else stmt.table_name
        # Check for CREATE TABLE (col defs) vs CREATE TABLE ... AS SELECT
        self.skip_blanks()
        n_opts = self._ctas_options_len()
        if n_opts:
            # CREATE TABLE t (a, b) USING m WITH (...) ON COMMIT ... TABLESPACE ts AS query
            stmt.options = [t for t in (self.eat() for _ in range(n_opts)) if t[0] != 'BLANK_LINE']
        elif self.pk()[1] == '(':
            return self.parse_create_table_columns(
                stmt.table_name, stmt.schema, stmt.if_not_exists, prefix)
        if (not self.done() and self.pk()[1] not in ('AS', ';', 'SELECT') and
                self.pk()[0] not in ('EOF', 'BLANK_LINE')):
            toks = []
            depth = 0
            while not self.done():
                t = self.pk()
                if t[0] == 'BLANK_LINE':
                    self.eat()
                    continue
                if t[1] == ';' and depth == 0:
                    toks.append(self.eat())
                    break
                # FOR VALUES WITH (...) / WITH (storage); FOR VALUES IN ((SELECT 1)) is nested
                if depth == 0 and t[1] in _STATEMENT_START_KWS - {'WITH'}:
                    break
                depth += {'(': 1, ')': -1}.get(t[1], 0)
                toks.append(self.eat())
            stmt.raw_fallback = toks
            return stmt
        if self.pk()[1] == 'AS':
            self.eat()
        self.skip_blanks()
        if self.pk()[1] == 'WITH':
            wstmt = self.parse_with()
            stmt.with_clause = wstmt
        elif self.pk()[1] == 'SELECT':
            stmt.select = self.parse_select()
            stmt._has_semicolon = stmt.select._has_semicolon
            self.skip_blanks()
            if not stmt._has_semicolon and self.pk()[1] == 'WITH' and self._at_view_suffix():
                stmt.suffix, stmt._has_semicolon = self._parse_query_suffix()
                return stmt
        elif not self.done() and self.pk()[1] != ';':
            # AS TABLE x / AS VALUES (...) / AS EXECUTE ...: keep the body as raw tokens
            body = []
            while not self.done() and self.pk()[1] != ';' and self.pk()[0] not in ('META', 'META_INLINE'):
                if self.pk()[0] == 'BLANK_LINE':
                    self.eat()
                    continue
                body.append(self.eat())
            stmt.body_raw = body
        self.skip_blanks()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

    # Keywords that end a type name and start a column constraint
    _CONSTRAINT_STARTERS = frozenset({
        'DEFAULT', 'PRIMARY', 'FOREIGN', 'REFERENCES', 'UNIQUE',
        'CHECK', 'CONSTRAINT', 'GENERATED', 'COLLATE',
    })

    # Table-constraint openers (first token of a table-level constraint entry)
    _TABLE_CONSTRAINT_OPENERS = frozenset({
        'PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK', 'CONSTRAINT', 'EXCLUDE', 'LIKE',
    })

    _CTAS_QUERY_STARTS = frozenset({'SELECT', 'WITH', 'VALUES', 'TABLE', 'EXECUTE', '('})

    def _ctas_options_len(self):
        """Token count of the column-name list / options before `AS query` in a
        CREATE TABLE AS, or 0 when this isn't a CREATE TABLE AS with such options."""
        j, depth = 0, 0
        while True:
            t = self.pk(j)
            if t[0] in ('EOF', 'META', 'META_INLINE') or (depth == 0 and t[1] == ';'):
                return 0
            if t[1] == '(':
                depth += 1
            elif t[1] == ')':
                depth -= 1
            elif depth == 0 and t[1] == 'AS':
                k = j + 1
                while self.pk(k)[0] == 'BLANK_LINE':
                    k += 1
                nxt = self.pk(k)
                if nxt[1] in self._CTAS_QUERY_STARTS or (nxt[0] in ('ID', 'KW') and nxt[1].upper() in self._CTAS_QUERY_STARTS):
                    return j
                return 0
            j += 1

    def parse_create_table_columns(self, table_name, schema, if_not_exists, prefix=''):
        """Parse CREATE TABLE name ( col defs ... ) [;]"""
        stmt = CreateTableStatement(
            table_name=table_name, schema=schema, if_not_exists=if_not_exists,
            prefix=prefix)
        self.eat()  # consume '('
        pending = []
        last = None  # last item parsed: ('col', ColumnDef) | ('con', index)
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[0] == 'COMMENT':
                self.eat()
                if not t[2] and last is not None:
                    # inline comment after the separating comma trails the previous item
                    if last[0] == 'col' and last[1].trailing_comment is None:
                        last[1].trailing_comment = Comment(
                            text=t[1], is_block=t[1].startswith('/*'), is_trailing=True)
                        continue
                    if last[0] == 'con' and stmt.constraint_trailing[last[1]] is None:
                        stmt.constraint_trailing[last[1]] = t[1]
                        continue
                pending.append(t[1])
                continue
            if t[1] == ')':
                self.eat()
                break
            if t[1] == ',':
                self.eat()
                continue
            if t[0] == 'EOF':
                break
            # Detect table-level constraint vs column definition
            first_up = t[1].upper()
            if first_up in self._TABLE_CONSTRAINT_OPENERS:
                tc = self._collect_until_col_sep()
                if tc:
                    # a trailing line comment ends up inside the collected tokens: split it off
                    trailing = None
                    if tc and tc[-1][0] == 'COMMENT' and not (len(tc[-1]) > 2 and tc[-1][2]):
                        trailing = tc.pop()[1]
                    stmt.table_constraints.append(tc)
                    stmt.constraint_leading.append(pending)
                    stmt.constraint_trailing.append(trailing)
                    last = ('con', len(stmt.table_constraints) - 1)
                    pending = []
            else:
                col = self.parse_column_def()
                if col is not None:
                    col.leading_comments = pending
                    pending = []
                    stmt.columns.append(col)
                    last = ('col', col)
        if pending:
            # comments right before the closing paren: keep them as a leading
            # comment of a synthetic empty constraint slot so they aren't lost
            stmt.constraint_leading.append(pending)
            stmt.constraint_trailing.append(None)
            stmt.table_constraints.append([])
        # table options after the closing paren: PARTITION BY ..., WITH (...), TABLESPACE ...
        self.skip_blanks()
        depth = 0
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if t[0] == 'COMMENT':
                # `) -- note` then more table options: the comment stays inside the tail
                j = 0
                while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                    j += 1
                nt = self.pk(j)
                if (nt[0] in ('EOF', 'META', 'META_INLINE') or nt[1] == ';'
                        or (depth == 0 and nt[1] in _STATEMENT_START_KWS - {'WITH'})):
                    break
                stmt.tail.append(self.eat())
                continue
            if (t[1] == ';' and depth == 0) or t[0] in ('META', 'META_INLINE'):
                break
            if depth == 0 and t[1] in _STATEMENT_START_KWS - {'WITH'}:  # CREATE TABLE ... WITH (storage)
                break
            depth += {'(': 1, ')': -1}.get(t[1], 0)
            stmt.tail.append(self.eat())
        if not self.done() and self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

    def _collect_until_col_sep(self):
        """Collect tokens until ',' or ')' at depth 0 (for table constraints)."""
        toks = []
        depth = 0
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if depth == 0 and t[1] in (',', ')'):
                break
            if t[1] in ('(', '['):
                depth += 1
            elif t[1] in (')', ']'):
                depth -= 1
            toks.append(self.eat())
        return toks

    def parse_column_def(self):
        """Parse one column definition: name type [constraints]."""
        if self.pk()[0] not in ('ID', 'KW', 'QUOTED_ID'):
            self.eat()  # skip unexpected token
            return None
        name = self.eat()[1]

        # Parse type: tokens until a constraint-starting keyword or separator
        type_toks = []
        depth = 0
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if depth == 0:
                if t[1] in (',', ')') or t[0] in ('COMMENT', 'EOF'):
                    break
                # KW 'NOT' starts NOT NULL; 'NULL' alone can be a constraint
                if t[0] == 'KW' and t[1] == 'NOT':
                    break
                if t[0] == 'KW' and t[1] == 'NULL':
                    break
                if t[0] == 'ID' and t[1].upper() in self._CONSTRAINT_STARTERS:
                    break
            if t[1] in ('(', '['):
                depth += 1
            elif t[1] in (')', ']'):
                if depth == 0:
                    break
                depth -= 1
            type_toks.append(self.eat())

        type_str = self._format_type_tokens(type_toks)

        # Parse optional column constraints: rest until ',' or ')' at depth 0
        constraint_toks = []
        depth = 0
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if depth == 0 and t[1] in (',', ')') or t[0] == 'EOF':
                break
            if t[0] == 'COMMENT':
                break
            if t[1] in ('(', '['):
                depth += 1
            elif t[1] in (')', ']'):
                if depth == 0:
                    break
                depth -= 1
            constraint_toks.append(self.eat())

        # Optional trailing inline comment (same line, not preceded by newline)
        trailing = None
        if not self.done() and self.pk()[0] == 'COMMENT':
            c = self.pk()
            if not (len(c) > 2 and c[2]):  # inline comment only
                self.eat()
                trailing = Comment(
                    text=c[1], is_block=c[1].startswith('/*'), is_trailing=True)

        return ColumnDef(name=name, type_str=type_str,
                         constraint_tokens=constraint_toks,
                         trailing_comment=trailing)

    @staticmethod
    def _format_type_tokens(toks):
        """Return type token list as a properly spaced uppercase string."""
        upcased = []
        for t in toks:
            if t[0] in ('ID', 'KW'):
                upcased.append((t[0], ascii_upper(t[1])) + t[2:])
            else:
                upcased.append(t)
        return join_expr(upcased)

    def parse_do_block(self):
        self.eat()  # DO
        lang_before = None
        if self.pk()[0] in ('ID', 'KW') and self.pk()[1].lower() == 'language':
            self.eat()
            lang_before = self.eat()[1]
        if self.pk()[0] not in ('DOLLAR_BODY', 'STR'):
            raise SqlSyntaxError("DO without a body")
        body = self.eat()[1]  # DOLLAR_BODY / quoted string
        stmt = DoBlock(dollar_body=body, language_before=lang_before)
        self.skip_blanks()
        if self.pk()[0] in ('ID', 'KW') and self.pk()[1].lower() == 'language':
            self.eat()
            stmt.language_after = self.eat()[1]
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

    # ── Utility / EXPLAIN / CREATE VIEW / MERGE ───────────────────

    _SIMPLE_UTILITY = frozenset({
        'SET', 'RESET', 'SHOW', 'DROP', 'TRUNCATE', 'VACUUM', 'ANALYZE',
        'ANALYSE', 'REINDEX', 'LOCK', 'DISCARD', 'DEALLOCATE', 'LISTEN',
        'NOTIFY', 'UNLISTEN', 'REFRESH', 'CLUSTER', 'COMMENT',
    })

    def parse_utility(self):
        """Statement with no dedicated formatter: collect its tokens up to `;`.

        Always consumes at least one token. A statement written without a
        terminating semicolon ends at the next DML keyword when it's a short
        one-liner (transaction control, SET, DROP, ...), so `ROLLBACK\nSELECT 1`
        still splits correctly.
        """
        first = self.pk()
        kind = first[1].upper()
        stops_at_dml = kind in _TCL_STARTERS or kind in self._SIMPLE_UTILITY
        stmt = UtilityStatement(kind=kind, tokens=[])
        depth = 0
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if t[0] in ('META', 'META_INLINE') and stmt.tokens:
                break
            if depth == 0 and t[1] == ';':
                self.eat()
                stmt._has_semicolon = True
                break
            if (stmt.tokens and depth == 0 and stops_at_dml
                    and t[0] in ('KW', 'ID') and t[1].upper() in _STATEMENT_START_KWS
                    and (t[1].upper() != 'WITH' or self._cte_follows())
                    and not (t[1].upper() == 'UPDATE' and stmt.tokens[-1][1].upper() == 'SHARE')):
                break  # (REFRESH ... WITH NO DATA / VACUUM ... WITH (...) are not a new statement)
            if (kind == 'CREATE' and depth == 0 and t[0] in ('ID', 'KW') and t[1].upper() == 'BEGIN'
                    and self.pk(1)[0] in ('ID', 'KW') and self.pk(1)[1].upper() == 'ATOMIC'):
                self._parse_atomic_body(stmt)
                break
            if t[1] in ('(', '['):
                depth += 1
            elif t[1] in (')', ']'):
                depth = max(0, depth - 1)
            stmt.tokens.append(self.eat())
        return stmt

    def _parse_atomic_body(self, stmt):
        """SQL-standard function body: BEGIN ATOMIC stmt; stmt; ... END [;]"""
        self.eat(); self.eat()  # BEGIN ATOMIC
        stmt.atomic_body = []
        while not self.done():
            while self.pk()[0] == 'BLANK_LINE' or self.pk()[1] == ';':
                self.eat()
            if self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'END':
                self.eat()
                break
            if self.pk()[0] == 'COMMENT':
                stmt.atomic_body.append(self.eat()[1])  # a comment line between body statements
                continue
            start = self.pos
            body_stmt = self.parse_statement()
            if self.pos == start:
                raise SqlSyntaxError('BEGIN ATOMIC: statement expected')
            stmt.atomic_body.append(body_stmt)
        else:
            raise SqlSyntaxError('BEGIN ATOMIC without END')
        self.skip_blanks()
        if self.pk()[1] == ';':
            self.eat()
            stmt._has_semicolon = True

    def parse_explain(self):
        self.eat()  # EXPLAIN
        opts = []
        if self.pk()[1] == '(':
            depth = 0
            while not self.done():
                t = self.eat()
                opts.append(t)
                if t[1] == '(':
                    depth += 1
                elif t[1] == ')':
                    depth -= 1
                    if depth == 0:
                        break
        else:
            while self.pk()[0] in ('ID', 'KW') and self.pk()[1].lower() in ('analyze', 'analyse', 'verbose'):
                opts.append(self.eat())
        self.skip_blanks_and_comments()
        if self.done() or self.pk()[1] == ';':
            stmt = ExplainStatement(opts, RawStatement([]))
            if self.pk()[1] == ';':
                self.eat()
                stmt._has_semicolon = True
            return stmt
        inner = self.parse_statement()
        return ExplainStatement(opts, inner, _has_semicolon=getattr(inner, '_has_semicolon', False))

    def _collect_name_tokens(self):
        """schema.name / "quoted"."name" -> single string (no spaces)."""
        parts = []
        while self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
            parts.append(self.eat()[1])
            if self.pk()[0] == 'DOT':
                parts.append(self.eat()[1])
                continue
            break
        return ''.join(parts)

    def _parse_query_suffix(self):
        """WITH [NO] DATA / WITH [CASCADED | LOCAL] CHECK OPTION after the query of a view
        or CREATE TABLE AS: raw tokens up to `;`. Returns (tokens, has_semicolon)."""
        toks = []
        while not self.done() and self.pk()[1] != ';':
            if self.pk()[0] == 'BLANK_LINE':
                self.eat()
                continue
            toks.append(self.eat())
        if self.pk()[1] == ';':
            self.eat()
            return toks, True
        return toks, False

    def parse_create_view(self, mods):
        start = self.pos
        self.eat()  # CREATE
        for _ in mods:
            self.eat()
        self.eat()  # VIEW
        stmt = CreateViewStatement(prefix=' '.join(mods), name='', columns=[], options=[],
                                   body=None, suffix=[])
        if self.pk()[1] == 'IF' and self.pk(1)[1] == 'NOT' and self.pk(2)[1] == 'EXISTS':
            self.eat(); self.eat(); self.eat()
            stmt.if_not_exists = True
        self.skip_blanks()
        stmt.name = self._collect_name_tokens()
        if self.pk()[1] == '(':
            self.eat()
            stmt.columns = self.collect_raw(lambda t: t[1] == ')')
            self._close_paren()
        # storage options / USING method / TABLESPACE: everything up to AS
        while not self.done() and self.pk()[1] != 'AS' and self.pk()[1] != ';':
            stmt.options.append(self.eat())
        if self.pk()[1] != 'AS':
            self.pos = start
            return self.parse_utility()
        self.eat()  # AS
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'WITH':
            stmt.body = self.parse_with()
        elif self.pk()[1] == 'SELECT':
            stmt.body = self.parse_select()
        else:
            self.pos = start
            return self.parse_utility()
        body_end = stmt.body.main_statement if isinstance(stmt.body, WithStatement) else stmt.body
        stmt._has_semicolon = getattr(stmt.body, '_has_semicolon', False)
        self.skip_blanks()
        if self.pk()[1] == 'WITH' or (self.pk()[0] == 'ID' and self.pk()[1].lower() == 'with'):
            stmt.suffix, has_semi = self._parse_query_suffix()
            stmt._has_semicolon = stmt._has_semicolon or has_semi
        elif self.pk()[1] == ';':
            self.eat()
            stmt._has_semicolon = True
        return stmt

    def parse_raw_statement(self):
        toks = []
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if t[1] == ';':
                toks.append(self.eat())
                break
            if t[1] in _STATEMENT_START_KWS:
                break
            toks.append(self.eat())
        return RawStatement(toks)
