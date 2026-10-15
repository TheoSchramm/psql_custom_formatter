"""INSERT / UPDATE / DELETE / MERGE parsing: SET clauses, ON CONFLICT, RETURNING."""

from __future__ import annotations
from ..constants import COMMENT_SEP, SqlSyntaxError, _SET_ITEM_END_KWS, _SET_LIST_END_KWS
from ..nodes import (
    ConflictClause, DeleteStatement, InsertStatement, MergeStatement, MergeWhen, RawTokens,
    SetClause, UpdateStatement,
)
from ..tokenizer import join_expr


class DmlParserMixin:
    """INSERT / UPDATE / DELETE / MERGE parsing: SET clauses, ON CONFLICT, RETURNING."""

    # ── Statement parsers ──────────────────────────────────────────

    def parse_update(self):
        self.eat()  # UPDATE
        self.skip_blanks()
        stmt = UpdateStatement(table='')
        # table ref
        ref = self.parse_table_ref()
        stmt.table = ref.name
        stmt.schema = ref.schema
        stmt.alias = ref.alias
        stmt.only, stmt.descendants = ref.only, ref.descendants
        self.skip_blanks()
        if self.pk()[1] == 'SET':
            self.eat()
            stmt.set_clauses = self.parse_set_clauses()
        pending_comments = self._collect_comments()
        if self.pk()[1] == 'FROM':
            self.eat()
            stmt.from_clause = self.parse_from_clause()
        pending_comments += self._collect_comments()
        if self.pk()[1] == 'WHERE':
            stmt.pre_where_comments = pending_comments
            pending_comments = []
            self.eat()
            stmt.where_leading_comments = self._collect_comments()
            if self.pk()[1] == 'CURRENT' and self.pk(1)[1].lower() == 'of':
                stmt.where_raw = self._where_current_of()
            else:
                stmt.where = self.parse_expression(stop_fn=self._where_stop)
                if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                    stmt.where_trailing_comment = self.eat()[1]
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning_with = self._parse_returning_with()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

    def parse_set_clauses(self, extra_stops=()):
        clauses = []
        pending_leading_comment = None
        stoppers = _SET_LIST_END_KWS | frozenset(extra_stops)
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[1] in stoppers or t[0] in ('EOF', 'BLANK_LINE', 'META', 'META_INLINE'):
                break
            if t[0] == 'COMMENT':
                # Comments before a clause keyword / the next statement are not SET items:
                # leave them in the stream for whoever parses what follows.
                j = 0
                while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                    j += 1
                if self.pk(j)[1] in stoppers or self.pk(j)[0] in ('EOF', 'META', 'META_INLINE'):
                    break
                # standalone comment between SET items — attach as the
                # leading comment of the next item instead of discarding it.
                pending_leading_comment = (pending_leading_comment + COMMENT_SEP if pending_leading_comment else '') + self.eat()[1]  # several stack up
                continue
            if t[1] == ',':
                self.eat()
                # trailing comment after comma
                if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                    if clauses:
                        clauses[-1].trailing_comment = self.eat()[1]
                continue
            # col = value
            target_toks = self.collect_raw(lambda t: t[1] == '=')
            if self.pk()[1] == '=':
                self.eat()
            target = join_expr(target_toks)
            val = self.parse_expression(stop_fn=lambda t: t[1] in _SET_ITEM_END_KWS or t[1] == ','
                                        or t[1] in extra_stops or t[0] == 'EOF')
            sc = SetClause(target=target, value=val)
            if pending_leading_comment is not None:
                sc.leading_comment = pending_leading_comment
                pending_leading_comment = None
            # trailing comment
            if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                sc.trailing_comment = self.eat()[1]
            clauses.append(sc)
        return clauses

    def parse_on_conflict(self):
        """Parse what follows ON CONFLICT: target, then DO NOTHING / DO UPDATE SET ... [WHERE ...].

        Falls back to keeping everything as raw tokens when the DO clause isn't
        in the expected shape, so nothing is ever dropped.
        """
        toks = self.collect_raw(lambda t: t[1] in (';', 'RETURNING', 'DO') or t[0] == 'EOF')
        if (len(toks) > 1 and toks[0][1] == 'ON'
                and toks[1][0] == 'ID' and toks[1][1].lower() == 'constraint'):
            toks[1] = ('KW', 'CONSTRAINT')
        clause = ConflictClause(toks)
        if self.pk()[1] != 'DO':
            return clause
        nxt = self.pk(1)
        if nxt[1] == 'NOTHING':
            self.eat(); self.eat()
            clause.action = 'NOTHING'
        elif nxt[1] == 'UPDATE' and self.pk(2)[1] == 'SET':
            self.eat(); self.eat(); self.eat()
            clause.action = 'UPDATE'
            clause.set_clauses = self.parse_set_clauses()
            self.skip_blanks()
            if self.pk()[1] == 'WHERE':
                self.eat()
                clause.where = self.parse_expression(stop_fn=self._where_stop)
                if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                    clause.where_trailing_comment = self.eat()[1]
        else:
            clause.raw_tokens = toks + self.collect_raw(
                lambda t: t[1] in (';', 'RETURNING') or t[0] == 'EOF')
        return clause

    def _parse_returning_with(self):
        """RETURNING WITH (OLD AS o, NEW AS n) ...: the option list's raw tokens, or None."""
        self.skip_blanks()
        if self.pk()[1] == 'WITH' and self.pk(1)[1] == '(':
            self.eat()
            return self._collect_balanced_parens_raw()[1:-1]
        return None

    def parse_returning_list(self):
        items = []
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[1] in (';', ')') or t[0] == 'EOF':
                break
            if t[1] == ',':
                self.eat()
                continue
            item = self.parse_select_item()
            items.append(item)
        return items

    def parse_insert(self):
        self.eat()  # INSERT
        stmt = InsertStatement(table='')
        if self.pk()[1] == 'INTO':
            self.eat()
        self.skip_blanks()
        # table name
        if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
            stmt.table = self.eat()[1]
        if self.pk()[0] == 'DOT':
            self.eat()
            stmt.schema = stmt.table
            stmt.table = self.eat()[1] if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID') else stmt.table
        if self.pk()[1] == 'AS' and self.pk(1)[0] in ('ID', 'KW', 'QUOTED_ID'):
            self.eat()
            stmt.alias = self.eat()[1]
        # column list: each column is the token run up to a top-level comma, so
        # `complex_col.r` / `arr[1]` stay whole; comments stay with the column before them
        # (INSERT INTO t (SELECT ...) UNION (...): that paren opens the query, not columns)
        if self.pk()[1] == '(' and not (self._query_follows(1) or self._paren_query_at(0)):
            self.eat()
            cols, cur, depth = [], [], 0
            while not self.done():
                t = self.pk()
                if t[0] == 'BLANK_LINE':
                    self.eat()
                    continue
                if depth == 0 and t[1] == ')':
                    break
                if t[1] in ('(', '['):
                    depth += 1
                elif t[1] in (')', ']'):
                    depth -= 1
                if depth == 0 and t[1] == ',':
                    self.eat()
                    cols.append(cur)
                    cur = []
                    if self.pk()[0] == 'COMMENT' and not self.pk()[2] and cols:
                        cols[-1].append(self.eat())  # `a, -- note`: trails column a
                    continue
                if t[0] == 'COMMENT' and t[2] and not cur and cols:
                    cols[-1].append(self.eat())  # own-line comment before the next column
                    continue
                cur.append(self.eat())
            if cur:
                cols.append(cur)
            stmt.columns = [join_expr(c) for c in cols]
            self._close_paren()
        self.skip_blanks()
        if (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'OVERRIDING'
                and self.pk(1)[1].upper() in ('SYSTEM', 'USER') and self.pk(2)[1].upper() == 'VALUE'):
            self.eat()
            stmt.overriding = self.eat()[1].upper()
            self.eat()
            self.skip_blanks()
        if self.pk()[1] == 'DEFAULT' and self.pk(1)[1] == 'VALUES':
            self.eat(); self.eat()
            stmt.default_values = True
        elif self.pk()[1] == 'SELECT':
            stmt.select = self.parse_select()
        elif self.pk()[1] == '(' and (self._query_follows(1) or self._paren_query_at(0)):
            stmt.select = self.parse_paren_select()
        elif self.pk()[1] == 'WITH':
            stmt.with_body = self.parse_with()
        elif self.pk()[1] == 'VALUES':
            self.eat()
            rows = []
            while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):  # VALUES -- note
                t = self.eat()
                if t[0] == 'COMMENT':
                    stmt.values_row_comments.setdefault(-1, []).append(t)
            while not self.done():
                self.skip_blanks()
                if self.pk()[1] != '(':
                    break
                self.eat()  # (
                row_toks = self.collect_raw(lambda t: t[1] == ')')
                self._close_paren()
                rows.append(row_toks)
                self.skip_blanks()
                j = 0
                while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                    j += 1
                if j and self.pk(j)[1] == ',':
                    # `(1, 'a')  -- note` + newline + `, (2, 'b')`: the comment follows this row
                    while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
                        t = self.eat()
                        if t[0] == 'COMMENT':
                            stmt.values_row_comments.setdefault(len(rows) - 1, []).append(t)
                if self.pk()[1] == ',':
                    self.eat()
                    # `(1, 'a'), -- note` / own-line comments: they follow this row
                    while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
                        t = self.eat()
                        if t[0] == 'COMMENT':
                            stmt.values_row_comments.setdefault(len(rows) - 1, []).append(t)
                else:
                    break
            stmt.values_rows = rows  # list of raw token lists
            # `VALUES (...) -- note` before ON CONFLICT / RETURNING: trails the last row
            j = 0
            while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                j += 1
            if j and rows and (self.pk(j)[1] == 'RETURNING'
                               or (self.pk(j)[1] == 'ON' and self.pk(j + 1)[1] == 'CONFLICT')):
                while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
                    t = self.eat()
                    if t[0] == 'COMMENT':
                        stmt.values_row_comments.setdefault(len(rows) - 1, []).append(t)
        # ON CONFLICT
        self.skip_blanks()
        if self.pk()[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
            self.eat(); self.eat()
            stmt.on_conflict = self.parse_on_conflict()
        self.skip_blanks()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning_with = self._parse_returning_with()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

    def _where_current_of(self):
        """WHERE CURRENT OF cursor (UPDATE / DELETE): raw tokens, OF uppercased."""
        toks = self.collect_raw(lambda t: t[1] in (';', 'RETURNING') or t[0] == 'EOF')
        if len(toks) > 1 and toks[1][0] == 'ID' and toks[1][1].lower() == 'of':
            toks[1] = ('KW', 'OF')
        return RawTokens(toks)

    def parse_delete(self):
        self.eat()  # DELETE
        stmt = DeleteStatement(table='')
        if self.pk()[1] == 'FROM':
            self.eat()
        self.skip_blanks()
        ref = self.parse_table_ref()
        stmt.table = ref.name
        stmt.schema = ref.schema
        stmt.alias = ref.alias
        stmt.only, stmt.descendants = ref.only, ref.descendants
        self.skip_blanks()
        if self.pk()[1] == 'USING':
            self.eat()
            stmt.using = self.parse_from_clause()
        pending_comments = self._collect_comments()
        if self.pk()[1] == 'WHERE':
            stmt.pre_where_comments = pending_comments
            pending_comments = []
            self.eat()
            stmt.where_leading_comments = self._collect_comments()
            if self.pk()[1] == 'CURRENT' and self.pk(1)[1].lower() == 'of':
                stmt.where_raw = self._where_current_of()
            else:
                stmt.where = self.parse_expression(stop_fn=self._where_stop)
                if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                    stmt.where_trailing_comment = self.eat()[1]
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning_with = self._parse_returning_with()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

    def parse_merge(self):
        self.eat()  # MERGE
        self.eat()  # INTO
        self.skip_blanks()
        target = self.parse_table_ref()
        self.skip_blanks()
        if self.pk()[1] == 'USING':
            self.eat()
        self.skip_blanks()
        source = self.parse_table_ref()
        self.skip_blanks()
        source_joins = []
        while self._is_join():
            source_joins.append(self.parse_join())
            self.skip_blanks()
        on_cond = None
        if self.pk()[1] == 'ON':
            self.eat()
            on_cond = self.parse_expression(stop_fn=lambda t: t[1] in ('WHEN', 'RETURNING', ';') or t[0] == 'EOF')
        stmt = MergeStatement(target=target, source=source, on_condition=on_cond, whens=[],
                              source_joins=source_joins)
        while True:
            saved = self.pos
            comments = self._collect_comments()
            if self.pk()[1] != 'WHEN':
                # comments with no following WHEN belong to whatever comes next
                self.pos = saved
                break
            self.eat()  # WHEN
            matched = 'MATCHED'
            if self.pk()[1] == 'NOT':
                self.eat()
                matched = 'NOT MATCHED'
            if self.pk()[0] in ('ID', 'KW') and self.pk()[1].lower() == 'matched':
                self.eat()
            if self.pk()[1] == 'BY':
                self.eat()
                matched += ' BY ' + self.eat()[1].upper()
            cond = None
            if self.pk()[1] == 'AND':
                self.eat()
                cond = self.parse_expression(stop_fn=lambda t: t[1] == 'THEN')
            if self.pk()[1] == 'THEN':
                self.eat()
            self.skip_blanks()
            comments += self._collect_comments()  # THEN /* note */ DELETE: shown above the WHEN
            w = MergeWhen(matched=matched, condition=cond, action='', leading_comments=comments)
            act = self.pk()[1].upper() if self.pk()[0] in ('ID', 'KW') else ''
            if act == 'UPDATE':
                self.eat()
                if self.pk()[1] == 'SET':
                    self.eat()
                w.action = 'UPDATE'
                w.set_clauses = self.parse_set_clauses(extra_stops=('WHEN',))
            elif act == 'DELETE':
                self.eat()
                w.action = 'DELETE'
            elif act == 'DO' and self.pk(1)[1] == 'NOTHING':
                self.eat(); self.eat()
                w.action = 'DO NOTHING'
            elif act == 'INSERT':
                self.eat()
                w.action = 'INSERT'
                self.skip_blanks()
                if self.pk()[1] == '(':
                    w.insert_columns = self._collect_balanced_parens_raw()[1:-1]
                self.skip_blanks()
                if (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'OVERRIDING'
                        and self.pk(1)[1].upper() in ('SYSTEM', 'USER') and self.pk(2)[1].upper() == 'VALUE'):
                    self.eat()
                    w.insert_overriding = self.eat()[1].upper()
                    self.eat()
                    self.skip_blanks()
                if self.pk()[1] == 'DEFAULT':
                    self.eat()
                    if self.pk()[1] == 'VALUES':
                        self.eat()
                    w.insert_default_values = True
                elif self.pk()[1] == 'VALUES':
                    self.eat()
                    self.skip_blanks()
                    if self.pk()[1] == '(':
                        w.insert_values = self._collect_balanced_parens_raw()[1:-1]
            else:
                raise SqlSyntaxError("Unrecognised MERGE action")
            stmt.whens.append(w)
        if not stmt.whens:
            raise SqlSyntaxError("MERGE without WHEN clause")
        self.skip_blanks()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning_with = self._parse_returning_with()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
            self.eat()
            stmt._has_semicolon = True
        return stmt
