"""INSERT / UPDATE / DELETE / MERGE formatting: SET clauses, RETURNING."""

from __future__ import annotations
from ..tokenizer import join_expr


class DmlFormatterMixin:
    """INSERT / UPDATE / DELETE / MERGE formatting: SET clauses, RETURNING."""

    def format_update(self, stmt):
        self.w('UPDATE')
        self.nl(1)
        name = stmt.table
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(('ONLY ' if stmt.only else '') + name + (' *' if stmt.descendants else ''))
        if stmt.alias:
            self.w(' ' + stmt.alias)
        if stmt.set_clauses:
            self.nl(0)
            self.w('SET')
            self._format_set_clauses(stmt.set_clauses)
        if stmt.from_clause:
            self.nl(0)
            self.w('FROM')
            self.format_from_clause(stmt.from_clause, 0)
        if stmt.where is not None or stmt.where_raw is not None:
            for comment in stmt.pre_where_comments:
                self.nl(0)
                self.w(comment)
            self.nl(0)
            self.w('WHERE')
            for comment in stmt.where_leading_comments:
                self.nl(1)
                self.w(comment)
            self.nl(1)
            if stmt.where_raw is not None:
                self.w(join_expr(stmt.where_raw.tokens))  # CURRENT OF cursor
            else:
                self.format_where_expr(stmt.where, 1, inline_and=False,
                                       final_trailing_comment=stmt.where_trailing_comment)
        if stmt.returning:
            self.nl(0)
            self.w('RETURNING')
            self._format_returning(stmt.returning, 1, stmt.returning_with)
        if stmt._has_semicolon:
            self._semi()

    def _format_set_clauses(self, clauses, level=1):
        first = True
        for sc in clauses:
            if first:
                self.nl(level)
                first = False
            else:
                if sc.leading_comment:
                    self.nl(level)
                    self._write_comment_lines(sc.leading_comment, level)
                self.nl(level)
                self.w(', ')
            self.w(sc.target + ' = ')
            self.format_expression(sc.value, level, inline=True)
            if sc.trailing_comment:
                self._emit_trailing_comment(sc.trailing_comment)

    def format_insert(self, stmt):
        self.w('INSERT INTO ')
        name = stmt.table
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(name)
        if stmt.alias:
            self.w(' AS ' + stmt.alias)
        if stmt.columns:
            self.w(' (')
            self._format_raw_column_list(stmt.columns, 1)
            self.nl(0)
            self.w(')')
        if stmt.overriding:
            self.nl(0)
            self.w(f'OVERRIDING {stmt.overriding} VALUE')
        if stmt.default_values:
            self.nl(0)
            self.w('DEFAULT VALUES')
        elif stmt.with_body:
            self.w('\n')
            self.format_with(stmt.with_body)
        elif stmt.values_rows is not None:
            self.nl(0)
            self.w('VALUES')
            row_on_new_line = False
            for c in stmt.values_row_comments.get(-1, []):
                self._emit_list_comment(c, 0)
                row_on_new_line = True
            if row_on_new_line:
                self.nl(0)
            for i, row_toks in enumerate(stmt.values_rows):
                self.w('(' if row_on_new_line and i == 0 else ' (')
                self.w(join_expr(row_toks))
                self.w(')')
                for c in stmt.values_row_comments.get(i, []):
                    self._emit_list_comment(c, 0)
                if i + 1 < len(stmt.values_rows):
                    self.nl(0)
                    self.w(',')
        elif stmt.select:
            self.w('\n')
            self.format_select(stmt.select, 0)
        if stmt.on_conflict:
            self.nl(0)
            self.w('ON CONFLICT')
            oc = stmt.on_conflict
            if oc.raw_tokens:
                self.w(' ' + join_expr(oc.raw_tokens))
            if oc.action == 'NOTHING':
                self.w(' DO NOTHING')
            elif oc.action == 'UPDATE':
                self.w(' DO UPDATE')
                self.nl(0)
                self.w('SET')
                self._format_set_clauses(oc.set_clauses)
                if oc.where is not None:
                    self.nl(0)
                    self.w('WHERE')
                    self.nl(1)
                    self.format_where_expr(oc.where, 1, inline_and=False,
                                           final_trailing_comment=oc.where_trailing_comment)
        if stmt.returning:
            self.nl(0)
            self.w('RETURNING')
            self._format_returning(stmt.returning, 1, stmt.returning_with)
        if stmt._has_semicolon:
            self._semi()

    def _format_raw_column_list(self, cols, ci):
        first = True
        for col in cols:
            if first:
                self.nl(ci)
                first = False
            else:
                self.nl(ci)
                self.w(', ')
            self.w(col)

    def _format_returning(self, items, ci, with_options=None):
        if with_options is not None:
            self.w(' WITH (' + join_expr(self._utility_prepare(with_options)) + ')')
        first = True
        for item in items:
            if first:
                self.nl(ci)
                first = False
            else:
                self.nl(ci)
                self.w(', ')
            self.format_select_item(item, ci)

    def format_delete(self, stmt):
        self.w('DELETE FROM')
        self.nl(1)
        name = stmt.table
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(('ONLY ' if stmt.only else '') + name + (' *' if stmt.descendants else ''))
        if stmt.alias:
            self.w(' ' + stmt.alias)
        if stmt.using:
            self.nl(0)
            self.w('USING')
            self.format_from_clause(stmt.using, 0)
        if stmt.where is not None or stmt.where_raw is not None:
            for comment in stmt.pre_where_comments:
                self.nl(0)
                self.w(comment)
            self.nl(0)
            self.w('WHERE')
            for comment in stmt.where_leading_comments:
                self.nl(1)
                self.w(comment)
            self.nl(1)
            if stmt.where_raw is not None:
                self.w(join_expr(stmt.where_raw.tokens))
            else:
                self.format_where_expr(stmt.where, 1, inline_and=False,
                                        final_trailing_comment=stmt.where_trailing_comment)
        if stmt.returning:
            self.nl(0)
            self.w('RETURNING')
            self._format_returning(stmt.returning, 1, stmt.returning_with)
        if stmt._has_semicolon:
            self._semi()

    def format_merge(self, stmt):
        self.w('MERGE INTO ')
        self.format_table_ref(stmt.target, 1)
        src = stmt.source
        self.nl(0)
        if src.subquery or src.values or src.func_call:
            self.w('USING')
            self.nl(1)
            self.format_table_ref(src, 1)
        else:
            self.w('USING ')
            self.format_table_ref(src, 1)
        for join in stmt.source_joins:
            self.nl(1)
            self.format_join(join, 1)
        if stmt.on_condition is not None:
            self.nl(0)
            self.w('ON')
            self.nl(1)
            self.format_where_expr(stmt.on_condition, 1, inline_and=False)
        for wh in stmt.whens:
            for c in wh.leading_comments:
                self.nl(0)
                self.w(c)
            self.nl(0)
            self.w('WHEN ' + wh.matched)
            if wh.condition is not None:
                self.w(' AND ')
                self.format_expression(wh.condition, 1, inline=True)
            self.w(' THEN')
            self.nl(1)
            if wh.action == 'UPDATE':
                self.w('UPDATE SET')
                self._format_set_clauses(wh.set_clauses, level=2)
            elif wh.action == 'INSERT':
                self.w('INSERT')
                if wh.insert_columns:
                    self.w(' (' + join_expr(wh.insert_columns) + ')')
                if wh.insert_overriding:
                    self.w(f' OVERRIDING {wh.insert_overriding} VALUE')
                if wh.insert_default_values:
                    self.w(' DEFAULT VALUES')
                else:
                    self.nl(1)
                    self.w('VALUES (' + join_expr(wh.insert_values) + ')')
            else:
                self.w(wh.action)
        if stmt.returning:
            self.nl(0)
            self.w('RETURNING')
            self._format_returning(stmt.returning, 1, stmt.returning_with)
        if stmt._has_semicolon:
            self._semi()
