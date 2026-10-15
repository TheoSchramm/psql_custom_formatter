"""SELECT formatting: select list, FROM / table refs / JOIN, WITH (CTEs)."""

from __future__ import annotations
from ..constants import INDENT
from ..nodes import RawStatement, SelectStatement
from ..tokenizer import join_expr


class SelectFormatterMixin:
    """SELECT formatting: select list, FROM / table refs / JOIN, WITH (CTEs)."""

    def format_select(self, stmt, base=0, is_subquery=False):
        for comment in stmt.leading_comments:
            self.w(self.ind(base) + comment + '\n')
        if stmt.paren_query is not None:
            self._format_paren_query(stmt.paren_query, base)
            self._format_set_operations(stmt, base, is_subquery)
            return
        self.w(self.ind(base) + 'SELECT')
        if stmt.all_rows:
            self.w(' ALL')
        if stmt.distinct:
            self.w(' DISTINCT')
        if stmt.distinct_on:
            self.w(' ON (')
            first_on = True
            for e in stmt.distinct_on:
                if not first_on:
                    self.w(', ')
                first_on = False
                self.format_expression(e, base, inline=True)
            self.w(')')
        ci = base + 1
        self._format_select_columns(stmt.columns, ci)
        for comment in stmt.select_list_trailing_comments:
            self.nl(ci)
            self.w(comment)
        if stmt.into:
            self.nl(base)
            self.w('INTO')
            self.nl(ci)
            self.w(join_expr(self._utility_prepare(stmt.into)))
        if stmt.from_clause:
            self.nl(base)
            self.w('FROM')
            self.format_from_clause(stmt.from_clause, base)
        if stmt.where is not None:
            for comment in stmt.pre_where_comments:
                self.nl(base)
                self.w(comment)
            self.nl(base)
            self.w('WHERE')
            for comment in stmt.where_leading_comments:
                self.nl(base + 1)
                self.w(comment)
            self.nl(base + 1)
            where_inline = is_subquery and self._fits_inline(stmt.where, base + 1)
            self.format_where_expr(stmt.where, base + 1, inline_and=where_inline,
                                    final_trailing_comment=stmt.where_trailing_comment)
        if stmt.group_by:
            for comment in stmt.group_by_leading_comments:
                self.nl(base)
                self.w(comment)
            self.nl(base)
            self.w('GROUP BY')
            self._format_expr_list_leading_comma(stmt.group_by, base + 1)
        if stmt.having is not None:
            for comment in stmt.pre_having_comments:
                self.nl(base)
                self.w(comment)
            self.nl(base)
            self.w('HAVING')
            for comment in stmt.having_leading_comments:
                self.nl(base + 1)
                self.w(comment)
            self.nl(base + 1)
            having_inline = is_subquery and self._fits_inline(stmt.having, base + 1)
            self.format_where_expr(stmt.having, base + 1, inline_and=having_inline,
                                    final_trailing_comment=stmt.having_trailing_comment)
        if stmt.window_defs:
            self.nl(base)
            self.w('WINDOW')
            for i, (wname, wspec) in enumerate(stmt.window_defs):
                self.nl(base + 1)
                if i > 0:
                    self.w(', ')
                self.w(wname + ' AS ')
                self._format_window_spec(wspec, base + 1)
        if stmt.order_by:
            for comment in stmt.order_by_leading_comments:
                self.nl(base)
                self.w(comment)
            self.nl(base)
            self.w('ORDER BY')
            self._format_order_by_list(stmt.order_by, base + 1)
        if stmt.limit:
            self.nl(base)
            self.w('LIMIT ')
            self.w(join_expr(stmt.limit.tokens))
        if stmt.offset:
            self.nl(base)
            self.w('OFFSET ')
            self.w(join_expr(stmt.offset.tokens))
        if stmt.fetch_clause:
            self.nl(base)
            self.w('FETCH ')
            self.w(join_expr(stmt.fetch_clause.tokens[1:]))  # skip FETCH token itself
        if stmt.for_clause:
            self.nl(base)
            self.w(stmt.for_clause)
        for comment in stmt.trailing_comments:
            self.nl(base + 1)
            self.w(comment)
        semi_after_set_ops = bool(stmt.set_tail) or (stmt.unions and stmt.unions[-1].parenthesized)
        if stmt._has_semicolon and not semi_after_set_ops:
            if stmt.trailing_comments or self._last_was_comment:
                self.nl(base)
            self._semi()
        self._format_set_operations(stmt, base, is_subquery)

    def _format_paren_query(self, query, base):
        self.w(self.ind(base) + '(\n')
        self._format_subquery_body(query, base + 1)
        self.w('\n' + self.ind(base) + ')')

    def _format_set_operations(self, stmt, base, is_subquery):
        for u in stmt.unions:
            self.w('\n')
            self.w(self.ind(base) + u.union_type)
            self.w('\n')
            if u.parenthesized:
                self._format_paren_query(u.query, base)
            else:
                self.format_select(u.query, base, is_subquery=is_subquery)
        if stmt.set_tail:
            for ln in self._render_token_lines(self._utility_prepare(stmt.set_tail)):
                self.nl(base)
                self.w(ln)
        if stmt.set_tail or stmt.paren_query is not None or (stmt.unions and stmt.unions[-1].parenthesized):
            if stmt._has_semicolon:
                self._semi()

    def _format_select_columns(self, columns, ci):
        """Select-list items at level ci, each on a new line, leading-comma style."""
        first = True
        for item in columns:
            if first:
                self.nl(ci)
                first = False
                if item.leading_comment:
                    self._write_comment_lines(item.leading_comment, ci)
                    self.nl(ci)
                self.format_select_item(item, ci)
            else:
                if item.leading_comment:
                    self.nl(ci)
                    self._write_comment_lines(item.leading_comment, ci)
                self.nl(ci)
                self.w(', ')
                self.format_select_item(item, ci)

    def format_select_item(self, item, ci):
        self.format_expression(item.expr, ci, inline=True)
        for c in item.pre_alias_comments:
            self.nl(ci)
            self.w(c)
        if item.alias and item.pre_alias_comments:
            self.nl(ci)
            self.w('AS ')
        elif item.alias:
            self.w(' AS ')
        if item.alias:
            if item.alias_quoted:
                self.w('"' + item.alias + '"')
            else:
                self.w(item.alias)
        if item.trailing_comment:
            self._emit_trailing_comment(item.trailing_comment)

    def format_from_clause(self, clause, base):
        ci = base + 1
        for comment in clause.leading_comments:
            self.nl(ci)
            self.w(comment)
        self.nl(ci)
        for ti, table in enumerate(clause.tables):
            if ti > 0:
                for comment in table.leading_comments:
                    self.nl(ci)
                    self.w(comment)
                self.nl(ci)
                self.w(', ')
            self.format_table_ref(table, ci)
            # the JOINs written after this comma item, in source order
            for join in clause.joins:
                if join.after_table != ti:
                    continue
                for comment in join.leading_comments:
                    self.nl(ci)
                    self.w(comment)
                self.nl(ci)
                self.format_join(join, ci)

    def format_table_ref(self, ref, ci):
        if ref.is_lateral:
            self.w('LATERAL ')
        if ref.subquery:
            self.w('(\n')
            self._format_subquery_body(ref.subquery, ci)
            self.w('\n')
            self.w(self.ind(ci) + ')')
        elif ref.values:
            self.format_values_table_ref(ref.values, ci)
        elif ref.func_call:
            self.format_expression(ref.func_call, ci, inline=True)
        else:
            name = ref.name
            if ref.schema:
                name = ref.schema + '.' + name
            self.w(('ONLY ' if ref.only else '') + name + (' *' if ref.descendants else ''))
        if ref.with_ordinality:
            self.w(' WITH ORDINALITY')
        if ref.alias:
            # Table aliases don't use AS keyword
            if ref.alias_quoted:
                self.w(' "' + ref.alias + '"')
            else:
                self.w(' ' + ref.alias)
            if ref.alias_columns:
                self.w(' (' + join_expr(ref.alias_columns) + ')')
        elif ref.alias_columns:
            self.w(' AS (' + join_expr(ref.alias_columns) + ')')  # column definitions, no alias
        if ref.tablesample:
            self.w(' TABLESAMPLE ' + join_expr(ref.tablesample))
        if ref.trailing_comment:
            self._emit_trailing_comment(ref.trailing_comment)

    def format_values_statement(self, stmt):
        """VALUES rows laid out like INSERT ... VALUES: one row per line, leading commas."""
        self.w('VALUES')
        for i, row in enumerate(stmt.rows):
            if i > 0:
                self.nl(0)
                self.w(',')
            self.w(' (' + join_expr(row) + ')')
        if stmt.tail:
            lines = self._render_token_lines(self._utility_prepare(stmt.tail))
            for ln in lines:
                self.nl(0)
                self.w(ln)
        if stmt._has_semicolon:
            self._semi()

    def format_values_table_ref(self, vc, ci):
        self.w('(\n')
        self.w(self.ind(ci) + 'VALUES')
        raw_rows = getattr(vc, '_raw_rows', [])
        first = True
        for i, row_toks in enumerate(raw_rows):
            self.nl(ci + 1)
            row_str = '(' + join_expr(row_toks) + ')'
            if first:
                self.w(row_str)
                first = False
            else:
                self.w(', ' + row_str)
            for c in vc.row_comments.get(i, []):
                self._emit_list_comment(c, ci + 1)
        self.nl(ci)
        self.w(')')
        if vc.alias:
            self.w(' AS ')
            if vc.alias_quoted:
                self.w('"' + vc.alias + '"')
            else:
                self.w(vc.alias)
        if vc.columns:
            self.w('(' + ', '.join(vc.columns) + ')')

    def format_join(self, join, ci):
        self.w(join.join_type + ' ')
        # Save trailing comment to emit after ON keyword (tab-aligned on the ON line),
        # matching the original formatter style.
        saved_comment = join.table.trailing_comment
        join.table.trailing_comment = None
        self.format_table_ref(join.table, ci)
        join.table.trailing_comment = saved_comment
        for nested in join.nested_joins:
            # the right operand's own joins, one level in; our ON/USING then drops back
            self.nl(ci + 1)
            self.format_join(nested, ci + 1)
        # ON / USING on its own line at the JOIN's column (after comments or nested joins)
        dropped = bool(join.pre_on_comments) or bool(join.nested_joins)
        if join.nested_joins and not join.pre_on_comments and (
                join.on_condition is not None or join.using_columns):
            self.nl(ci)
        if join.pre_on_comments:
            # comments between the joined table and ON/USING: own lines, with the
            # keyword dropped back to the JOIN's column so it still reads as part of this join
            for comment in join.pre_on_comments:
                self.nl(ci + 1)
                self.w(comment)
            self.nl(ci)
        if join.on_condition is not None:
            # ON condition always goes on next line (double-indented)
            self.w('ON' if dropped else ' ON')
            if saved_comment:
                self._emit_trailing_comment(saved_comment)
            for comment in join.on_leading_comments:
                self.nl(ci + 1)
                self.w(comment)
            self.nl(ci + 1)
            self.format_where_expr(join.on_condition, ci + 1, inline_and=False,
                                    final_trailing_comment=join.on_trailing_comment)
        else:
            if saved_comment:
                self._emit_trailing_comment(saved_comment)
        if join.using_columns:
            self.w(('' if dropped else ' ') + 'USING (' + ', '.join(join.using_columns) + ')')
            if join.using_alias:
                self.w(' AS ' + join.using_alias)

    def format_with(self, stmt):
        for comment in stmt.leading_comments:
            self.w(comment + '\n')
        self.w('WITH')
        if stmt.recursive:
            self.w(' RECURSIVE')
        first_cte = True
        for cte in stmt.ctes:
            if first_cte:
                self.w(' ')
                first_cte = False
            else:
                self.w('\n')
            for comm in cte.leading_comments:
                self.w(comm)
                self.w('\n')
            self.w(cte.name)
            if cte.columns:
                self.w(' (' + ', '.join(cte.columns) + ')')
            self.w(' AS ')
            if cte.materialized:
                self.w(cte.materialized + ' ')
            self.w('(')
            self.w('\n')
            for comm in cte.body_leading_comments:
                self.w(INDENT + comm + '\n')
            if isinstance(cte.body, SelectStatement):
                self.format_select(cte.body, 1)
            else:
                # INSERT/UPDATE/DELETE (or nested WITH) body: render at column 0, then indent
                sub = type(self)()
                sub.format_statement(cte.body)
                text = ''.join(sub.out).rstrip(';')
                self.w('\n'.join((INDENT + ln) if ln.strip() else ln for ln in text.split('\n')))
            self.w('\n)')
            for clause in cte.search_cycle:
                self.w(' ' + join_expr(self._utility_prepare(clause)))
            if cte is not stmt.ctes[-1]:
                self.w(',')
        if isinstance(stmt.main_statement, RawStatement) and not stmt.main_statement.tokens:
            if stmt._has_semicolon:
                self._semi()
            return
        self.w('\n')
        for comm in stmt.main_leading_comments:
            self.w(comm)
            self.w('\n')
        self.format_statement(stmt.main_statement)
