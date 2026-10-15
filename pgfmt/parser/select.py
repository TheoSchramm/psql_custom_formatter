"""SELECT parsing: select list, FROM / table refs / VALUES / JOIN, WITH (CTEs)."""

from __future__ import annotations
from ..constants import (
    COMMENT_SEP, FUNCTION_KWS, JOIN_MODIFIERS, SqlSyntaxError, _CLAUSE_KWS, _GROUP_END_KWS,
    _JOIN_ON_END_KWS, _NOT_ALIAS_KWS, _QUERY_TAIL_KWS, _SET_OP_KWS, _STATEMENT_START_KWS,
    _VIEW_SUFFIX_WORDS, _WHERE_END_KWS, _WITH_MAIN_KWS,
)
from ..nodes import (
    CteClause, FromClause, JoinClause, RawStatement, RawTokens, SelectItem, SelectStatement,
    TableRef, UnionPart, ValuesClause, ValuesStatement, WithStatement,
)
from ..tokenizer import ascii_upper, join_expr


class SelectParserMixin:
    """SELECT parsing: select list, FROM / table refs / VALUES / JOIN, WITH (CTEs)."""

    def _is_join(self, off=0):
        t = self.pk(off)
        if t[0] in ('ID', 'KW') and t[1].upper() == 'NATURAL':
            off += 1
            t = self.pk(off)
        if t[1] == 'JOIN':
            return True
        if t[1] in JOIN_MODIFIERS:
            j = off + 1
            while self.pk(j)[1] in JOIN_MODIFIERS:
                j += 1
            return self.pk(j)[1] == 'JOIN'
        return False

    def parse_select(self, stop_at_rpar=False):
        stmt = SelectStatement()
        self.eat()  # SELECT
        self.skip_blanks()
        if self.pk()[1] == 'ALL':
            stmt.all_rows = True  # SELECT ALL (the default, written out)
            self.eat()
            self.skip_blanks()
        if self.pk()[1] == 'DISTINCT':
            stmt.distinct = True
            self.eat()
            self.skip_blanks()
            if self.pk()[1] == 'ON':
                self.eat()
                self.skip_blanks()
                if self.pk()[1] == '(':
                    self.eat()
                    stmt.distinct_on = self.parse_expr_list(lambda t: t[1] == ')')
                    self.skip_blanks()
                    self._close_paren()
        stmt.columns = self.parse_select_list()
        if not stmt.columns:
            # `SELECT;` / `SELECT FROM t` are valid (zero columns); anything else after a
            # bare SELECT means the list wasn't understood
            j = 0
            while self.pk(j)[0] in ('BLANK_LINE', 'COMMENT'):
                j += 1
            nt = self.pk(j)
            if not (nt[0] in ('EOF', 'META', 'META_INLINE') or nt[1] in _CLAUSE_KWS
                    or nt[1] in _QUERY_TAIL_KWS or nt[1] in (')', 'INTO', 'RETURNING')
                    or (nt[1] == 'ON' and self.pk(j + 1)[1] == 'CONFLICT')):
                raise SqlSyntaxError("SELECT with no columns")
        stmt.select_list_trailing_comments = getattr(self, '_select_list_extra_comments', [])
        pending_comments = self._collect_comments()
        if self.pk()[1] == 'INTO':
            self.eat()
            stmt.into = self.collect_raw(lambda t: t[1] in _CLAUSE_KWS or t[1] in ('FROM', 'WINDOW') or t[0] == 'EOF')
            pending_comments += self._collect_comments()
        if self.pk()[1] == 'FROM':
            self.eat()
            stmt.from_clause = self.parse_from_clause()
        pending_comments += self._collect_comments()
        if self.pk()[1] == 'WHERE':
            stmt.pre_where_comments = pending_comments
            pending_comments = []
            self.eat()
            stmt.where_leading_comments = self._collect_comments()
            stmt.where = self.parse_expression(stop_fn=self._where_stop)
            if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                stmt.where_trailing_comment = self.eat()[1]
        pending_comments += self._collect_comments()
        if self.pk()[1] == 'GROUP' and self.pk(1)[1] == 'BY':
            stmt.group_by_leading_comments = pending_comments
            pending_comments = []
            self.eat(); self.eat()
            stmt.group_by = self.parse_expr_list(self._group_stop)
        pending_comments += self._collect_comments()
        if self.pk()[1] == 'HAVING':
            stmt.pre_having_comments = pending_comments
            pending_comments = []
            self.eat()
            stmt.having_leading_comments = self._collect_comments()
            stmt.having = self.parse_expression(stop_fn=self._group_stop)
            if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                stmt.having_trailing_comment = self.eat()[1]
        pending_comments += self._collect_comments()
        if self.pk()[1] == 'WINDOW':
            self.eat()
            while not self.done():
                self.skip_blanks()
                if self.pk()[0] not in ('ID', 'KW', 'QUOTED_ID'):
                    break
                wname = self.eat()[1]
                if self.pk()[1] == 'AS':
                    self.eat()
                if self.pk()[1] != '(':
                    break
                self.eat()
                stmt.window_defs.append((wname, self.parse_window_spec()))
                if self.pk()[0] == 'COMMA':
                    self.eat()
                    continue
                break
            pending_comments += self._collect_comments()
        if self.pk()[1] == 'ORDER' and self.pk(1)[1] == 'BY':
            stmt.order_by_leading_comments = pending_comments
            pending_comments = []
            self.eat(); self.eat()
            stmt.order_by = self.parse_order_by_list()
        pending_comments += self._collect_comments()
        stmt.trailing_comments = self._release_next_statement_comments(pending_comments)
        # comments right after the body (no blank line before them) stay with the statement
        while self.pk()[0] == 'COMMENT':
            stmt.trailing_comments.append(self.eat()[1])
        self._comments_before(stmt, ('LIMIT',))
        if self.pk()[1] == 'LIMIT':
            self.eat()
            toks = self.collect_raw(lambda t: t[1] in (_QUERY_TAIL_KWS - {'LIMIT'}) or t[1] == ';' or t[0] == 'EOF')
            stmt.limit = RawTokens(toks)
        self._comments_before(stmt, ('OFFSET',))
        if self.pk()[1] == 'OFFSET':
            self.eat()
            toks = self.collect_raw(lambda t: t[1] in (';', 'FETCH', 'FOR') or t[0] == 'EOF')
            stmt.offset = RawTokens(toks)
        self._comments_before(stmt, ('FETCH',))
        if self.pk()[1] == 'FETCH':
            toks = [self.eat()]  # FETCH
            while not self.done() and self.pk()[1] not in (';', 'FOR') and self.pk()[0] != 'EOF':
                toks.append(self.eat())
            stmt.fetch_clause = RawTokens(toks)
        self._comments_before(stmt, ('FOR',))
        if self.pk()[1] == 'FOR':
            stmt.for_clause = self._parse_for_clause()
        self._comments_before(stmt, (';',))
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return self._parse_set_operations(stmt, stop_at_rpar)

    def _parse_set_operations(self, stmt, stop_at_rpar=False):
        """UNION / EXCEPT / INTERSECT [ALL | DISTINCT] operands, each a SELECT or a
        parenthesized query; after a parenthesized last operand, the ORDER BY / LIMIT /
        ... that applies to the whole result is kept as stmt.set_tail."""
        self._comments_before(stmt, _SET_OP_KWS)
        while self.pk()[1] in _SET_OP_KWS:
            op = self.eat()[1]
            self.skip_blanks()
            if self.pk()[1] in ('ALL', 'DISTINCT'):
                op = op + ' ' + self.eat()[1]
            self.skip_blanks()
            op_comments = self._collect_comments()  # UNION ALL -- recursive term\n SELECT ...
            if self.pk()[1] == '(' and (self._query_follows(1) or self._paren_query_at(0)):
                self.eat()
                sub = self._parse_paren_body()
                self.skip_blanks()
                self._close_paren()
                if hasattr(sub, 'leading_comments'):
                    sub.leading_comments = op_comments + sub.leading_comments
                stmt.unions.append(UnionPart(op, sub, parenthesized=True))
                self.skip_blanks()
                continue
            sub = self.parse_select(stop_at_rpar=stop_at_rpar)
            sub.leading_comments = op_comments + sub.leading_comments
            stmt.unions.append(UnionPart(op, sub))
        if (stmt.unions and stmt.unions[-1].parenthesized) or (stmt.paren_query is not None and not stmt.unions):
            depth = 0
            while not self.done():
                t = self.pk()
                if t[0] in ('EOF', 'META', 'META_INLINE') or (depth == 0 and t[1] in (';', ')')):
                    break
                if t[1] == '(':
                    depth += 1
                elif t[1] == ')':
                    depth -= 1
                if t[0] == 'BLANK_LINE':
                    self.eat()
                    continue
                stmt.set_tail.append(self.eat())
            if self.pk()[1] == ';':
                self.eat()
                stmt._has_semicolon = True
        return stmt

    def parse_paren_select(self):
        """A statement that starts with a parenthesized query: (SELECT ...) UNION ... / (SELECT ...) LIMIT 1"""
        stmt = SelectStatement()
        self.eat()  # (
        stmt.paren_query = self._parse_paren_body()
        self.skip_blanks()
        self._close_paren()
        self.skip_blanks()
        return self._parse_set_operations(stmt)

    _LOCK_WORDS = frozenset({'for', 'update', 'share', 'no', 'key', 'of', 'nowait', 'skip', 'locked'})

    def _parse_for_clause(self):
        """Row-locking clause: FOR UPDATE / NO KEY UPDATE / SHARE / KEY SHARE
        [OF table, ...] [NOWAIT | SKIP LOCKED], possibly repeated.

        Lock words are uppercased; table names after OF are left as written.
        """
        parts = []
        in_of = False
        while not self.done():
            t = self.pk()
            if t[0] == 'EOF' or t[1] in _SET_OP_KWS or t[1] in (';', ')'):
                break
            if t[0] == 'COMMENT':
                break
            self.eat()
            if t[0] == 'BLANK_LINE':
                continue
            word = t[1]
            low = word.lower() if t[0] in ('ID', 'KW') else None
            if low == 'of':
                in_of = True
                parts.append('OF')
            elif low in ('nowait', 'skip', 'locked', 'for'):
                in_of = False
                parts.append(word.upper())
            elif in_of or low not in self._LOCK_WORDS:
                parts.append(word)
            else:
                parts.append(ascii_upper(word))
        out = ' '.join(parts)
        return out.replace(' , ', ', ').replace(' .', '.').replace('. ', '.')

    def _where_stop(self, t):
        if t[1] in _WHERE_END_KWS:
            return True
        if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
            return True
        return t[0] == 'EOF'

    def _group_stop(self, t):
        if t[1] in _GROUP_END_KWS:
            return True
        if t[1] == 'GROUP' and self.pk(1)[1] == 'BY':
            return True
        if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
            return True
        return t[0] == 'EOF'

    def parse_select_list(self):
        items = []
        pending_leading_comment = None
        self._select_list_extra_comments = []
        while not self.done():
            if items and self.pk()[0] == 'BLANK_LINE':
                # blank line, then comments: those lead whatever comes next, they are not
                # trailing comments of this select list
                j = 0
                while self.pk(j)[0] == 'BLANK_LINE':
                    j += 1
                if self.pk(j)[0] == 'COMMENT':
                    break
            self.skip_blanks()
            t = self.pk()
            if t[1] in _CLAUSE_KWS or t[1] == ')' or t[0] == 'EOF':
                break
            if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
                break
            if t[1] == 'WITH' and self._at_view_suffix():
                break
            if t[1] in ('INTO', 'RETURNING'):
                break
            if t[1] == ',':
                self.eat()
                # trailing comment after comma (inline, not preceded by newline)
                if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                    c = self.eat()[1]
                    if items:
                        items[-1].trailing_comment = c
                continue
            # standalone comment inside select list
            if t[0] == 'COMMENT':
                # check if it (and subsequent comments) precede a clause boundary
                j = 0
                while self.pk(j)[0] == 'COMMENT':
                    j += 1
                nxt = self.pk(j)
                if nxt[1] in _CLAUSE_KWS or nxt[1] == ')' or nxt[0] == 'EOF':
                    # Comments before clause end — first one attaches as trailing to
                    # the last item; any additional ones get their own line before
                    # the next clause so they aren't silently dropped.
                    while self.pk()[0] == 'COMMENT':
                        c = self.eat()[1]
                        if items and items[-1].trailing_comment is None:
                            items[-1].trailing_comment = c
                        else:
                            self._select_list_extra_comments.append(c)
                    break
                # Between-column comment — store as leading comment of next item
                pending_leading_comment = (pending_leading_comment + COMMENT_SEP if pending_leading_comment else '') + self.eat()[1]  # several stack up
                continue
            item = self.parse_select_item()
            if pending_leading_comment is not None:
                item.leading_comment = pending_leading_comment
                pending_leading_comment = None
            items.append(item)
            # Another item can only follow a comma. Anything else (a clause keyword, `)`, or the
            # start of the next statement when this one has no terminating `;`) ends the list.
            j = 0
            while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                j += 1
            nt = self.pk(j)
            ends_normally = (nt[1] in _CLAUSE_KWS or nt[1] in (')', 'INTO') or nt[0] == 'EOF'
                             or (nt[1] == 'ON' and self.pk(j + 1)[1] == 'CONFLICT')
                             or (nt[1] == 'WITH' and self.pk(j + 1)[0] in ('ID', 'KW')
                                 and self.pk(j + 1)[1].lower() in _VIEW_SUFFIX_WORDS))
            if nt[0] != 'COMMA' and nt[1] != ',' and not ends_normally:
                break  # not a continuation of this select list: the next statement starts here
        return items

    def parse_select_item(self):
        expr = self.parse_expression(stop_fn=self._select_item_stop)
        item = SelectItem(expr=expr)
        # A blank line followed by comments ends the item: leave the blank in the stream so
        # parse_select_list / parse_select can see it and treat those comments as leading
        # whatever comes next, not as this item's trailing comments.
        j = 0
        while self.pk(j)[0] == 'BLANK_LINE':
            j += 1
        if j and self.pk(j)[0] == 'COMMENT':
            return item
        self.skip_blanks()
        # trailing inline comment
        if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
            item.trailing_comment = self.eat()[1]
        # own-line comments between the expression and its AS alias
        j = 0
        while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
            j += 1
        if j and self.pk(j)[1] == 'AS':
            item.pre_alias_comments = [t[1] for t in (self.eat() for _ in range(j)) if t[0] == 'COMMENT']
        # alias
        if self.pk()[1] == 'AS':
            self.eat()
            if self.pk()[0] == 'QUOTED_ID':
                item.alias = self.eat()[1].strip('"')
                item.alias_quoted = True
            elif self.pk()[0] in ('ID', 'KW'):
                t = self.eat()
                item.alias = t[1].lower() if t[0] == 'KW' else t[1]  # an alias is a name: AS sum
        elif (self.pk()[0] in ('ID', 'QUOTED_ID') and
              self.pk()[1] not in _NOT_ALIAS_KWS and
              self.pk()[1] not in _CLAUSE_KWS):
            if self.pk()[0] == 'QUOTED_ID':
                item.alias = self.eat()[1].strip('"')
                item.alias_quoted = True
            else:
                item.alias = self.eat()[1]
        elif (self.pk()[0] == 'KW' and self.pk()[1] in FUNCTION_KWS and self.pk(1)[1] != '('
              and (self.pk(1)[1] in (',', ')', ';') or self.pk(1)[1] in _CLAUSE_KWS or self.pk(1)[0] == 'EOF')):
            item.alias = self.eat()[1].lower()  # sum(x) sum: a function-name keyword as a bare alias
        # trailing comment after alias
        if not item.trailing_comment and self.pk()[0] == 'COMMENT' and not self.pk()[2]:
            item.trailing_comment = self.eat()[1]
        return item

    def _at_view_suffix(self):
        """At `WITH NO DATA` / `WITH [LOCAL|CASCADED] CHECK OPTION` after a view body."""
        return (self.pk()[1] == 'WITH' and self.pk(1)[0] in ('ID', 'KW')
                and self.pk(1)[1].lower() in _VIEW_SUFFIX_WORDS)

    def _select_item_stop(self, t):
        if t[1] in _CLAUSE_KWS or t[1] == ')' or t[0] == 'EOF' or t[1] == ',':
            return True
        if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
            return True
        if t[1] == 'WITH' and self._at_view_suffix():
            return True
        if t[1] == 'INTO':
            return True
        if t[0] == 'COMMENT' and len(t) > 2 and t[2]:
            return True
        return False

    # ── FROM clause ───────────────────────────────────────────────

    def parse_from_clause(self):
        tables = []
        joins = []
        self.skip_blanks()
        # Standalone comments before the first table
        leading = []
        while self.pk()[0] == 'COMMENT':
            leading.append(self.eat()[1])
            self.skip_blanks()
        t = self.parse_table_ref()
        tables.append(t)
        while not self.done():
            self.skip_blanks()
            # Only consume standalone comments here if they precede another
            # table/JOIN — otherwise leave them for the next clause (e.g. WHERE)
            # to pick up, instead of discarding them.
            j = 0
            while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                j += 1
            comments = []
            if self.pk(j)[1] == ',' or self._is_join(j):
                while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
                    tok = self.eat()
                    if tok[0] == 'COMMENT':
                        comments.append(tok[1])
            if self.pk()[1] == ',':
                self.eat()
                self.skip_blanks()
                comments += self._collect_comments()
                ref = self.parse_table_ref()
                ref.leading_comments = comments
                tables.append(ref)
                continue
            if self._is_join():
                jc = self.parse_join()
                jc.leading_comments = comments
                jc.after_table = len(tables) - 1
                joins.append(jc)
                continue
            break
        return FromClause(tables, joins, leading)

    def parse_table_ref(self):
        self.skip_blanks()
        ref = TableRef()
        if self.pk()[1] == 'LATERAL':
            ref.is_lateral = True
            self.eat()
            self.skip_blanks()
        if (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'ONLY'
                and self.pk(1)[0] in ('ID', 'KW', 'QUOTED_ID')):
            ref.only = True
            self.eat()
        if self.pk()[1] == '(':
            # subquery or VALUES
            j = 1
            while self.pk(j)[0] == 'BLANK_LINE':
                j += 1
            if self._query_follows(j):
                self.eat()  # (
                sub = self._parse_query()
                self.skip_blanks()
                self._close_paren()
                ref.subquery = sub
            elif self.pk(j)[1] == 'VALUES':
                ref.values = self.parse_values_table_ref()
            else:
                # grouped table ref (rare) — treat as subquery fallback
                toks = self._collect_balanced_parens_raw()
                ref.name = join_expr(toks)
        elif self.pk()[1] == 'ROWS' and self.pk(1)[1] == 'FROM' and self.pk(2)[1] == '(':
            # ROWS FROM (f(...), g(...)): kept as one opaque table expression
            self.eat(); self.eat()
            ref.name = 'ROWS FROM ' + join_expr(self._collect_balanced_parens_raw())
        elif (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'COLLATION'
              and self.pk(1)[1] == 'FOR' and self.pk(2)[1] == '('):
            ref.func_call = self.parse_primary()  # FROM collation for ('x'::text) col
        else:
            # regular table name
            if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID', 'WORD'):
                ref.name = self.eat()[1]
            while self.pk()[0] == 'DOT':
                self.eat()
                ref.schema = ref.name
                ref.name = self.eat()[1] if self.pk()[0] in ('ID', 'KW', 'STAR', 'QUOTED_ID', 'WORD') else ref.name
            if self.pk()[1] == '(':
                # table function call, e.g. generate_series(1, 10), unnest(arr)
                ref.func_call = self.parse_function_call(ref.name, ref.schema)
                ref.name = ''
                ref.schema = None
            elif self.pk()[0] == 'STAR':
                self.eat()
                ref.descendants = True
        self.skip_blanks()
        if (self.pk()[1] == 'WITH' and self.pk(1)[0] in ('ID', 'KW')
                and self.pk(1)[1].lower() == 'ordinality'):
            self.eat(); self.eat()
            ref.with_ordinality = True
        # alias
        self.skip_blanks()
        saw_as = False
        if self.pk()[1] == 'AS':
            self.eat()
            saw_as = True
            if self.pk()[0] == 'QUOTED_ID':
                ref.alias = self.eat()[1].strip('"')
                ref.alias_quoted = True
            elif self.pk()[0] in ('ID', 'KW'):
                ref.alias = self.eat()[1]
        elif (self.pk()[0] in ('ID', 'QUOTED_ID') and
              self.pk()[1] not in _NOT_ALIAS_KWS and
              not self._is_join() and
              not (self.pk()[0] == 'ID' and self.pk()[1].lower() == 'tablesample') and
              self.pk()[1] not in (',', ')', ';')):
            if self.pk()[0] == 'QUOTED_ID':
                ref.alias = self.eat()[1].strip('"')
                ref.alias_quoted = True
            else:
                ref.alias = self.eat()[1]
        # alias column list x(a, b), or a column definition list for a function:
        # f() AS t(a int, b numeric(10, 2)) / f() AS (a int, b text)
        if (ref.alias or saw_as) and self.pk()[1] == '(':
            ref.alias_columns = self._collect_balanced_parens_raw()[1:-1]
        # TABLESAMPLE method (args) [REPEATABLE (seed)]
        if (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'TABLESAMPLE'
                and self.pk(1)[0] in ('ID', 'KW') and self.pk(2)[1] == '('):
            self.eat()
            toks = [('KW', self.eat()[1].upper())] + self._collect_balanced_parens_raw()
            if self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'REPEATABLE' and self.pk(1)[1] == '(':
                self.eat()
                toks += [('KW', 'REPEATABLE')] + self._collect_balanced_parens_raw()
            ref.tablesample = toks
        # trailing comment
        if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
            ref.trailing_comment = self.eat()[1]
        return ref

    def parse_values_table_ref(self):
        """Parse (VALUES (...), ...) AS alias(cols)"""
        self.eat()  # (
        self.skip_blanks()
        self.eat()  # VALUES
        rows = []
        row_comments = {}
        while not self.done():
            self.skip_blanks()
            # `(...), -- note` / `(...) -- note` + `, (...)`: comments follow the row before
            while self.pk()[0] in ('COMMENT', 'BLANK_LINE') or (self.pk()[1] == ',' and rows):
                t = self.eat()
                if t[0] == 'COMMENT':
                    row_comments.setdefault(len(rows) - 1, []).append(t)
            if self.pk()[1] != '(':
                break
            self.eat()  # row (
            row_toks = self.collect_raw(lambda t: t[1] == ')')
            self._close_paren()
            rows.append(row_toks)
        # outer )
        self.skip_blanks()
        if self.pk()[1] != ')':
            # Row loop stopped on something that isn't a value row or the
            # closing paren (e.g. a non-SQL template placeholder like
            # <<COLAR_PASSO_1>>) — bail out instead of silently leaving the
            # token stream desynced, which corrupts everything downstream.
            raise SqlSyntaxError("Malformed VALUES table constructor")
        self.eat()
        vc = ValuesClause(rows=[], row_comments=row_comments)
        vc._raw_rows = rows  # keep as raw token lists for now
        # alias
        if self.pk()[1] == 'AS':
            self.eat()
            if self.pk()[0] == 'QUOTED_ID':
                vc.alias = self.eat()[1].strip('"')
                vc.alias_quoted = True
            elif self.pk()[0] in ('ID', 'KW'):
                vc.alias = self.eat()[1]
        elif self.pk()[0] in ('ID', 'QUOTED_ID'):
            vc.alias = self.eat()[1]
        # column list
        if self.pk()[1] == '(':
            self.eat()
            while not self.done() and self.pk()[1] != ')':
                if self.pk()[1] == ',':
                    self.eat()
                    continue
                vc.columns.append(self.eat()[1])
            self._close_paren()
        return vc

    def _collect_balanced_parens_raw(self):
        toks = [self.eat()]  # (
        depth = 1
        while not self.done() and depth > 0:
            t = self.eat()
            toks.append(t)
            if t[1] == '(':
                depth += 1
            elif t[1] == ')':
                depth -= 1
        return toks

    def parse_join(self):
        join_type_parts = []
        if self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'NATURAL':
            self.eat()
            join_type_parts.append('NATURAL')
        while self.pk()[1] in JOIN_MODIFIERS:
            join_type_parts.append(self.eat()[1])
        join_type_parts.append(self.eat()[1])  # JOIN
        join_type = ' '.join(join_type_parts)
        self.skip_blanks()
        # LATERAL after JOIN
        if self.pk()[1] == 'LATERAL':
            self.eat()
            join_type = join_type + ' LATERAL'
        self.skip_blanks()
        table = self.parse_table_ref()
        self.skip_blanks()
        nested = []
        if 'CROSS' not in join_type and 'NATURAL' not in join_type:
            # `a LEFT JOIN b LEFT JOIN c ON x ON y`: b's own join comes before our ON
            while self._is_join():
                nested.append(self.parse_join())
                self.skip_blanks()
        on_cond = None
        using_cols = None
        on_trailing_comment = None
        on_leading_comments = []
        self.skip_blanks()
        # standalone comments between the joined table and ON/USING
        pre_on_comments = []
        saved_pos = self.pos
        while self.pk()[0] == 'COMMENT':
            pre_on_comments.append(self.eat()[1])
            self.skip_blanks()
        if self.pk()[1] not in ('ON', 'USING'):
            # no condition follows: the comments belong to whatever comes next
            # (another JOIN, WHERE, ...), not to this join
            self.pos = saved_pos
            pre_on_comments = []
        if self.pk()[1] == 'ON':
            self.eat()
            self.skip_blanks()
            # Capture inline comment after ON (e.g., "ON  -- the join" in formatted output)
            # and attach it to the table ref so round-trips preserve it.
            if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                table.trailing_comment = self.eat()[1]
                self.skip_blanks()
            # Standalone comment(s) between ON and its condition — preserve
            # them instead of letting parse_expression silently swallow them.
            on_leading_comments = self._collect_comments()
            on_cond = self.parse_expression(stop_fn=self._join_on_stop)
            if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                on_trailing_comment = self.eat()[1]
        elif self.pk()[1] == 'USING':
            self.eat()
            if self.pk()[1] == '(':
                self.eat()
                using_cols = []
                while not self.done() and self.pk()[1] != ')':
                    if self.pk()[1] == ',':
                        self.eat()
                        continue
                    using_cols.append(self.eat()[1])
                self._close_paren()
        jc = JoinClause(join_type, table, on_cond, using_cols, on_trailing_comment, on_leading_comments,
                        pre_on_comments=pre_on_comments, nested_joins=nested)
        if using_cols is not None and self.pk()[1] == 'AS' and self.pk(1)[0] in ('ID', 'KW', 'QUOTED_ID'):
            self.eat()
            jc.using_alias = self.eat()[1]
        return jc

    def _join_on_stop(self, t):
        if t[1] in _JOIN_ON_END_KWS:
            return True
        if t[0] == 'EOF':
            return True
        if self._is_join():
            return True
        return False

    def parse_values_statement(self):
        """VALUES (...), (...) [ORDER BY ...] [LIMIT ...] [OFFSET ...] as a statement."""
        self.eat()  # VALUES
        stmt = ValuesStatement(rows=[])
        while self.pk()[1] == '(':
            self.eat()
            stmt.rows.append(self.collect_raw(lambda t: t[1] == ')'))
            self._close_paren()
            self.skip_blanks()
            if self.pk()[1] != ',':
                break
            self.eat()
            self.skip_blanks()
        stmt.tail = self.collect_raw(lambda t: t[1] == ';' or t[0] in ('EOF', 'META', 'META_INLINE')
                                     or (t[1] in _STATEMENT_START_KWS and t[1] != 'WITH'))
        if self.pk()[1] == ';':
            self.eat()
            stmt._has_semicolon = True
        return stmt

    @staticmethod
    def _search_list_comma(toks):
        """Inside SEARCH ... BY a, b / CYCLE a, b SET: a comma continues the column list
        until SET (afterwards it separates CTEs)."""
        words = [t[1].upper() for t in toks if t[0] in ('ID', 'KW')]
        return 'SET' not in words

    def parse_with(self):
        self.eat()  # WITH
        stmt = WithStatement(recursive=False, ctes=[], main_statement=RawStatement([]))
        if self.pk()[1] == 'RECURSIVE':
            stmt.recursive = True
            self.eat()
        first_cte = True
        while not self.done():
            loop_start = self.pos
            self.skip_blanks()
            pending_comments = []
            if not first_cte:
                # comments between CTEs (or before the main statement)
                while self.pk()[0] == 'COMMENT':
                    pending_comments.append(self.eat()[1])
                    self.skip_blanks()
            is_merge = self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'MERGE'
            is_values = self.pk()[1] == 'VALUES' and self.pk(1)[1] == '('
            is_paren = self.pk()[1] == '(' and (self._query_follows(1) or self._paren_query_at(0))
            if (self.pk()[1] in _WITH_MAIN_KWS or is_merge or is_values or is_paren or self.pk()[1] == ';'
                    or self.pk()[0] == 'EOF'):
                stmt.main_leading_comments = pending_comments
                break
            first_cte = False
            cte_name = ''
            if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
                cte_name = self.eat()[1]
            columns = []
            # Optional column list — only if ( is NOT followed by AS or SELECT
            if self.pk()[1] == '(' and self.pk(1)[1] not in ('SELECT',):
                # check if it's truly a column list
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
                    self.eat()  # (
                    while not self.done() and self.pk()[1] != ')':
                        if self.pk()[1] == ',':
                            self.eat()
                            continue
                        columns.append(self.eat()[1])
                    self._close_paren()
            materialized = None
            if self.pk()[1] == 'AS':
                self.eat()
                self.skip_blanks()
                if self.pk()[0] == 'ID' and self.pk()[1].lower() == 'materialized':
                    self.eat()
                    materialized = 'MATERIALIZED'
                elif (self.pk()[1] == 'NOT' and self.pk(1)[0] == 'ID'
                        and self.pk(1)[1].lower() == 'materialized'):
                    self.eat(); self.eat()
                    materialized = 'NOT MATERIALIZED'
            self.skip_blanks()
            if self.pk()[1] == '(':
                self.eat()
                # comments between "(" and the body's first keyword stay inside the CTE
                body_comments = self._collect_comments()
                if (self.pk()[1] in (_WITH_MAIN_KWS - {'SELECT'}) | {'WITH'}
                        or (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'MERGE')):
                    # data-modifying CTE: WITH x AS (INSERT/UPDATE/DELETE/MERGE ... RETURNING ...)
                    body = self.parse_statement()
                elif self.pk()[1] in ('VALUES', 'TABLE'):
                    # VALUES (..), (..) / TABLE t as a CTE body: keep as written (it is not a SELECT)
                    body = RawStatement(self.collect_raw(lambda t: t[1] == ')'))
                else:
                    body = self._parse_paren_body()  # SELECT / WITH, or ((VALUES ...) UNION ALL (...))
                self.skip_blanks()
                self._close_paren()
            else:
                # `name AS (` is mandatory; inventing an empty body would print SQL that was
                # never written (e.g. `CREATE TABLE x AS SELECT ... WITH NO DATA`)
                raise SqlSyntaxError(f"WITH: expected '(' after CTE {cte_name!r}")
            cte = CteClause(name=cte_name, columns=columns, body=body,
                            leading_comments=pending_comments, materialized=materialized,
                            body_leading_comments=body_comments)
            # recursive-query clauses after the body: SEARCH ... SET col, CYCLE ... USING path
            while (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() in ('SEARCH', 'CYCLE')
                   and self.pk(1)[0] in ('ID', 'KW')):
                toks = [('KW', self.eat()[1].upper())]
                while not self.done():
                    t = self.pk()
                    if t[1] == ',' and not self._search_list_comma(toks):
                        break  # the comma separates this CTE from the next one
                    if t[1] in (';', ')') or t[0] in ('EOF', 'COMMENT', 'BLANK_LINE'):
                        break
                    if (t[0] in ('ID', 'KW') and t[1].upper() in ('SEARCH', 'CYCLE')
                            and self.pk(1)[0] in ('ID', 'KW')):
                        break
                    if t[1] in _WITH_MAIN_KWS or t[1] == 'WITH':
                        break
                    toks.append(self.eat())
                cte.search_cycle.append(toks)
            stmt.ctes.append(cte)
            self.skip_blanks()
            if self.pk()[1] == ',':
                self.eat()
            if self.pos == loop_start:
                # nothing consumed: not a well-formed CTE list; fail instead of looping forever
                raise SqlSyntaxError("Malformed WITH clause")
        self.skip_blanks()
        if (self.pk()[1] in _WITH_MAIN_KWS or (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'MERGE')
                or (self.pk()[1] == 'VALUES' and self.pk(1)[1] == '(')
                or (self.pk()[1] == '(' and (self._query_follows(1) or self._paren_query_at(0)))):
            stmt.main_statement = self.parse_statement()
            stmt._has_semicolon = getattr(stmt.main_statement, '_has_semicolon', False)
        elif self.pk()[1] == ';':
            # `WITH x AS (...);` with no main query (not valid SQL, but the `;` must survive)
            self.eat()
            stmt._has_semicolon = True
        return stmt
