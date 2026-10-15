"""Expression formatting: operators, AND/OR chains, IN lists, CASE, function calls, ORDER BY / window."""

from __future__ import annotations
from ..nodes import (
    AnyAllExpr, ArrayExpr, BetweenExpr, BinaryOp, CaseExpr, CastExpr, ExistsExpr, FieldExpr,
    FunctionCall, Identifier, InExpr, IsNullOp, Literal, Parenthesized, PostfixOp, RawTokens,
    RowExpr, StringContinuation, SubqueryExpr, SubscriptExpr, TypeCastOp, UnaryOp, ValuesExpr,
)
from ..tokenizer import ascii_upper, join_expr


class ExpressionFormatterMixin:
    """Expression formatting: operators, AND/OR chains, IN lists, CASE, function calls, ORDER BY / window."""

    def _format_expr_list_leading_comma(self, exprs, ci):
        first = True
        for e in exprs:
            if first:
                self.nl(ci)
                first = False
            else:
                self.nl(ci)
                self.w(', ')
            self.format_expression(e, ci, inline=True)

    def _format_order_by_list(self, items, ci):
        first = True
        for item in items:
            if first:
                self.nl(ci)
                first = False
            else:
                self.nl(ci)
                self.w(', ')
            self.format_expression(item.expr, ci, inline=True)
            if item.using:
                self.w(' USING ' + item.using)
            if item.direction:
                self.w(' ' + item.direction)
            if item.nulls:
                self.w(' NULLS ' + item.nulls)

    def format_expression(self, expr, ci, inline=True):
        if isinstance(expr, Literal):
            self.w(expr.value)
        elif isinstance(expr, StringContinuation):
            self.w(expr.pieces[0])
            for piece in expr.pieces[1:]:
                self.nl(ci + 1)
                self.w(piece)
            self._unjoinable = True
        elif isinstance(expr, Identifier):
            self.w('.'.join(expr.parts))
        elif isinstance(expr, BinaryOp):
            if expr.op == '':
                # AnyAllExpr in right position
                self.format_expression(expr.right, ci, inline)
            else:
                if not inline and expr.op in ('AND', 'OR'):
                    parts = self._flatten_conditions(expr)
                    for i, (op, leading_comments, part_expr, trailing_comment) in enumerate(parts):
                        for comm in leading_comments:
                            self.nl(ci)
                            self.w(comm.text)
                        if i > 0:
                            self.nl(ci)
                            self.w(op + ' ')
                        self.format_expression(part_expr, ci, inline=True)
                        if trailing_comment:
                            self._emit_trailing_comment(trailing_comment)
                else:
                    self.format_expression(expr.left, ci, inline)
                    if expr.op:
                        self.w(' ' + expr.op + ' ')
                    self.format_expression(expr.right, ci, inline)
        elif isinstance(expr, UnaryOp):
            if expr.op in ('-', '+'):
                # Sign operators bind tight (-a, +5); keep a space only when the
                # operand starts with another sign so '- -a' never becomes a '--' comment.
                self.w(expr.op)
                if isinstance(expr.expr, UnaryOp):
                    self.w(' ')  # '- -a' never becomes a comment, '-@a' never a new operator
            else:
                self.w(expr.op + ' ')
            self.format_expression(expr.expr, ci, inline)
        elif isinstance(expr, IsNullOp):
            self.format_expression(expr.expr, ci, inline)
            self.w(' IS NOT NULL' if expr.negated else ' IS NULL')
        elif isinstance(expr, FunctionCall):
            self.format_function_call(expr, ci)
        elif isinstance(expr, CaseExpr):
            self.format_case(expr, ci)
        elif isinstance(expr, CastExpr):
            self.w('CAST(')
            self.format_expression(expr.expr, ci, inline)
            self.w(' AS ' + expr.type_str + ')')
        elif isinstance(expr, TypeCastOp):
            self.format_expression(expr.expr, ci, inline)
            self.w('::' + ascii_upper(expr.type_str))
        elif isinstance(expr, InExpr):
            self.format_in_expr(expr, ci)
        elif isinstance(expr, BetweenExpr):
            self.format_expression(expr.expr, ci, inline)
            self.w(' NOT BETWEEN ' if expr.negated else ' BETWEEN ')
            if expr.mode:
                self.w(expr.mode + ' ')
            self.format_expression(expr.low, ci, inline)
            self.w(' AND ')
            self.format_expression(expr.high, ci, inline)
        elif isinstance(expr, ExistsExpr):
            prefix = 'NOT EXISTS (' if expr.negated else 'EXISTS ('
            self.w(prefix)
            self.w('\n')
            self._format_subquery_body(expr.subquery, ci + 1)
            self.nl(ci)
            self.w(')')
        elif isinstance(expr, SubqueryExpr):
            inline = self._inline_subquery(expr.query)
            if inline is not None:
                self.w(inline)
            else:
                self.w('(')
                self.w('\n')
                self._format_subquery_body(expr.query, ci + 1)
                self.nl(ci)
                self.w(')')
        elif isinstance(expr, Parenthesized):
            self.w('(')
            self.format_expression(expr.expr, ci, inline=True)
            for c in expr.close_comments:
                if c.lstrip().startswith('--'):
                    self._emit_trailing_comment(c)
                    self.nl(ci)
                else:
                    self.w(' ' + c)
            self.w(')')
        elif isinstance(expr, PostfixOp):
            self.format_expression(expr.expr, ci, inline)
            self.w(' ' + expr.op)
        elif isinstance(expr, FieldExpr):
            self.format_expression(expr.base, ci, inline=True)
            self.w('.' + expr.field)
        elif isinstance(expr, ValuesExpr):
            self.w('VALUES ' + ', '.join('(' + join_expr(r) + ')' for r in expr.rows))
        elif isinstance(expr, RowExpr):
            self.w('(')
            for i, it in enumerate(expr.items):
                if i > 0:
                    self.w(', ')
                self.format_expression(it, ci, inline=True)
            self.w(')')
        elif isinstance(expr, SubscriptExpr):
            self.format_expression(expr.base, ci, inline=True)
            self.w('[')
            for i, part in enumerate(expr.parts):
                if i > 0:
                    self.w(':')
                if part is not None:
                    self.format_expression(part, ci, inline=True)
            self.w(']')
        elif isinstance(expr, ArrayExpr):
            self.w('[' if expr.bare else 'ARRAY[')
            for i, el in enumerate(expr.elements):
                if i > 0:
                    self.w(', ')
                self.format_expression(el, ci, inline=True)
            self.w(']')
        elif isinstance(expr, AnyAllExpr):
            inner = expr.array
            if isinstance(inner, ArrayExpr) and len(inner.elements) > 3:
                self.w(expr.quantifier + '(ARRAY[')
                for i, el in enumerate(inner.elements):
                    self.nl(ci + 1)
                    if i > 0:
                        self.w(', ')
                    self.format_expression(el, ci + 1, inline=True)
                self.nl(ci)
                self.w('])')
            elif isinstance(inner, ValuesExpr):
                self.w(expr.quantifier + ' (')
                self.format_expression(inner, ci, inline=True)
                self.w(')')
            elif isinstance(inner, SubqueryExpr) and not getattr(inner, 'scalar_in_any', False):
                # SubqueryExpr renders its own parentheses
                self.w(expr.quantifier + ' ')
                self.format_expression(inner, ci, inline=True)
            else:
                self.w(expr.quantifier + '(')
                self.format_expression(inner, ci, inline=True)
                self.w(')')
        elif isinstance(expr, RawTokens):
            self.w(join_expr(expr.tokens))

    def _flatten_conditions(self, expr):
        """Flatten top-level AND/OR tree into [(op_or_None, leading_comments, sub_expr, trailing_comment)] list."""
        if isinstance(expr, BinaryOp) and expr.op in ('AND', 'OR'):
            left_parts = self._flatten_conditions(expr.left)
            if expr.left_trailing_comment and left_parts:
                op0, lc0, pe0, _ = left_parts[-1]
                left_parts[-1] = (op0, lc0, pe0, expr.left_trailing_comment)
            return left_parts + [(expr.op, expr.leading_comments, expr.right, None)]
        return [(None, [], expr, None)]

    def format_where_expr(self, expr, ci, inline_and=False, final_trailing_comment=None):
        if inline_and:
            self.format_expression(expr, ci, inline=True)
            if final_trailing_comment:
                self._emit_trailing_comment(final_trailing_comment)
        else:
            parts = self._flatten_conditions(expr)
            for i, (op, leading_comments, part_expr, trailing_comment) in enumerate(parts):
                for comm in leading_comments:
                    self.nl(ci)
                    self.w(comm.text)
                if i > 0:
                    self.nl(ci)
                    self.w(op + ' ')
                self.format_expression(part_expr, ci, inline=True)
                tc = trailing_comment
                if i == len(parts) - 1 and not tc:
                    tc = final_trailing_comment
                if tc:
                    self._emit_trailing_comment(tc)

    def format_in_expr(self, expr, ci):
        self.format_expression(expr.expr, ci, inline=True)
        self.w(' NOT IN' if expr.negated else ' IN')
        if expr.subquery:
            self.w(' (')
            self.w('\n')
            self._format_subquery_body(expr.subquery, ci + 1)
            self.nl(ci)
            self.w(')')
        elif len(expr.values) > 3 or expr.end_comments or any(expr.lead_comments) or any(expr.trail_comments):
            self.w(' (')
            for i, val in enumerate(expr.values):
                if i < len(expr.lead_comments):
                    for c in expr.lead_comments[i]:
                        self.nl(ci + 1)
                        self.w(c)
                self.nl(ci + 1)
                if i > 0:
                    self.w(', ')
                self.format_expression(val, ci + 1, inline=True)
                if i < len(expr.trail_comments) and expr.trail_comments[i]:
                    self._emit_trailing_comment(expr.trail_comments[i])
            for c in expr.end_comments:
                self.nl(ci + 1)
                self.w(c)
            self.nl(ci)
            self.w(')')
        else:
            self.w(' (')
            for i, val in enumerate(expr.values):
                if i > 0:
                    self.w(', ')
                self.format_expression(val, ci, inline=True)
            self.w(')')

    def format_case(self, expr, ci):
        gaps = expr.gap_comments or {}
        whens = gaps.get('when', [])

        def gap(comments, level):
            # a comment that followed code on the same line stays trailing; the rest
            # go on their own line (every WHEN/ELSE/END starts a new line anyway)
            for text, own_line in comments:
                if own_line:
                    self.nl(level)
                    self.w(text)
                    self._last_was_comment = True
                else:
                    self._emit_trailing_comment(text)

        self.w('CASE')
        if expr.operand is not None:
            self.w(' ')
            self.format_expression(expr.operand, ci, inline=True)
        for bi, (when_e, then_e) in enumerate(expr.branches):
            gap(whens[bi] if bi < len(whens) else [], ci + 1)
            self.nl(ci + 1)
            self.w('WHEN ')
            self.format_expression(when_e, ci + 1, inline=True)
            self.w(' THEN ')
            self.format_expression(then_e, ci + 1, inline=True)
        if expr.else_expr is not None:
            gap(gaps.get('else', []), ci + 1)
            self.nl(ci + 1)
            self.w('ELSE ')
            self.format_expression(expr.else_expr, ci + 1, inline=True)
        gap(gaps.get('end', []), ci + 1)
        self.nl(ci + 1)
        self.w('END')

    def _format_keyword_args(self, items, ci):
        """('kw', W) / ('comma', ',') / ('expr', node) items, space separated."""
        prev = None
        for kind, val in items:
            if kind == 'comma':
                self.w(',')
            elif kind == 'kw':
                self.w(('' if prev is None else ' ') + val)
            else:
                self.w('' if prev is None else ' ')
                self.format_expression(val, ci, inline=True)
            prev = kind

    def format_function_call(self, call, ci):
        name = call.name
        if call.schema:
            name = call.schema + '.' + name
        self.w(name + '(')
        if call.distinct:
            self.w('DISTINCT ')
        if call.special is not None:
            self._format_keyword_args(call.special, ci)
        elif call.star_arg:
            self.w('*')
        else:
            def arg_comments(i):
                # returns True when the line was left ending in a `--` comment
                after_line_comment = False
                for c in call.arg_comments.get(i, []):
                    if after_line_comment:
                        self.nl(ci + 1)
                    if c.lstrip().startswith('--'):
                        self._emit_trailing_comment(c)
                        after_line_comment = True
                    else:
                        self.w(' ' + c)
                        after_line_comment = False
                return after_line_comment

            broken = arg_comments(-1)
            for i, arg in enumerate(call.args):
                if broken:
                    self.nl(ci + 1)
                    self.w(', ' if i > 0 else '')
                elif i > 0:
                    self.w(', ')
                # SubqueryExpr inside a function call: the function parens serve
                # as the outer parens, so format the SELECT directly (no extra parens)
                if isinstance(arg, SubqueryExpr) and getattr(arg, 'in_call_parens', False):
                    self.w('\n')
                    self._format_subquery_body(arg.query, ci + 1)
                    if call.after_order_by:
                        # JSON_ARRAY(SELECT ... RETURNING jsonb): the options under the query
                        self.nl(ci + 1)
                        self._format_keyword_args(call.after_order_by, ci + 1)
                    self.nl(ci)
                else:
                    self.format_expression(arg, ci, inline=True)
                broken = arg_comments(i)
            if broken and not call.order_by:
                self.nl(ci)
        if call.order_by:
            self.w(' ORDER BY ')
            self._format_order_items(call.order_by, ci)
        if call.after_order_by and not (call.args and getattr(call.args[-1], 'in_call_parens', False)):
            self.w(' ')
            self._format_keyword_args(call.after_order_by, ci)
        self.w(')')
        if call.within_group is not None:
            self.w(' WITHIN GROUP (ORDER BY ')
            self._format_order_items(call.within_group, ci)
            self.w(')')
        if call.filter_clause:
            self.w(' FILTER (WHERE ')
            self.format_expression(call.filter_clause, ci, inline=True)
            self.w(')')
        if call.over_clause:
            ws = call.over_clause
            # named window reference
            if ws.ref_name is not None:
                self.w(' OVER ' + ws.ref_name)
            else:
                self.w(' OVER ')
                self._format_window_spec(ws, ci)

    def _format_order_items(self, items, ci):
        for i, ob in enumerate(items):
            if i > 0:
                self.w(', ')
            self.format_expression(ob.expr, ci, inline=True)
            if ob.using:
                self.w(' USING ' + ob.using)
            if ob.direction:
                self.w(' ' + ob.direction)
            if ob.nulls:
                self.w(' NULLS ' + ob.nulls)

    def _format_window_spec(self, ws, ci):
        self.w('(')
        first_part = True
        if ws.base_name:
            self.w(ws.base_name)
            first_part = False
        if ws.partition_by:
            if not first_part:
                self.w(' ')
            self.w('PARTITION BY ')
            for i, pb in enumerate(ws.partition_by):
                if i > 0:
                    self.w(', ')
                self.format_expression(pb, ci, inline=True)
            first_part = False
        if ws.order_by:
            if not first_part:
                self.w(' ')
            self.w('ORDER BY ')
            self._format_order_items(ws.order_by, ci)
            first_part = False
        if ws.frame:
            self.w(('' if first_part else ' ') + ws.frame)
        self.w(')')

    def _has_top_level_and_or(self, expr):
        return isinstance(expr, BinaryOp) and expr.op in ('AND', 'OR')
