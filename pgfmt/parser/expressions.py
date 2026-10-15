"""Expression parsing (Pratt): operators, primaries, CASE, function calls, window specs, ORDER BY lists."""

from __future__ import annotations
from ..constants import (
    SqlSyntaxError, _CLAUSE_KWS, _INFIX_PREC, _NEVER_PRIMARY_KWS, _NEXT_STATEMENT_KWS,
    _ORDER_BY_END_KWS, _ORDER_ITEM_END_KWS, _ORDER_ITEM_KWS, _OTHER_OP_PREC, _QUERY_TAIL_KWS,
    _STATEMENT_START_KWS, _WINDOW_FRAME_KWS,
)
from ..nodes import (
    AnyAllExpr, ArrayExpr, BetweenExpr, BinaryOp, CaseExpr, CastExpr, Comment, ExistsExpr,
    FieldExpr, FunctionCall, Identifier, InExpr, IsNullOp, Literal, OrderItem, Parenthesized,
    PostfixOp, RawTokens, RowExpr, StringContinuation, SubqueryExpr, SubscriptExpr, TypeCastOp,
    UnaryOp, ValuesExpr, WindowSpec,
)
from ..tokenizer import ascii_upper, join_expr, tokenize


class ExpressionParserMixin:
    """Expression parsing (Pratt): operators, primaries, CASE, function calls, window specs, ORDER BY lists."""

    # ── Expression parsing (Pratt) ────────────────────────────────

    def parse_expression(self, stop_fn=None, min_prec=0):
        self.skip_blanks()
        left = self.parse_primary(stop_fn)
        while True:
            loop_start = self.pos
            self.skip_blanks()
            if self.pos != loop_start and self.pk()[0] == 'COMMENT':
                # blank line + comments after a complete expression: if what follows them is a
                # statement boundary, they are not part of this expression (nor of the
                # statement) — leave blank and comments in the stream for the next statement
                j = 0
                while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                    j += 1
                nm = self.pk(j)
                if (nm[0] in ('EOF', 'META', 'META_INLINE') or nm[1] == ';'
                        or (nm[0] in ('KW', 'ID') and nm[1] in _STATEMENT_START_KWS)):
                    self.pos = loop_start
                    break
            # Skip comments (standalone or inline) between expression terms, but only if
            # the token following all comments would NOT be stopped by stop_fn.
            # If the next meaningful token after the comments would trigger stop_fn,
            # leave the comments in the stream for the caller to pick up as trailing.
            j = 0
            while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                j += 1
            next_meaningful = self.pk(j)
            should_continue = (
                next_meaningful[0] != 'EOF'
                and next_meaningful[1] != ';'
                and not (stop_fn and stop_fn(next_meaningful))
                and next_meaningful[0] not in ('COMMA',)
            )
            # Also don't skip comments if next meaningful token is a comma or rpar
            # (those are expression terminators that the caller handles)
            if next_meaningful[1] in (',', ')') or next_meaningful[0] in ('COMMA', 'RPAR'):
                should_continue = False
            # Don't eat comments if the next operator has lower precedence than min_prec —
            # in that case the loop will break anyway and the comment belongs to the outer call.
            if (should_continue
                    and next_meaningful[0] in ('OP', 'KW')
                    and next_meaningful[1] in _INFIX_PREC
                    and _INFIX_PREC[next_meaningful[1]] < min_prec):
                should_continue = False
            pending_leading = []
            pending_trailing_inline = None
            saved_pos = self.pos  # to hand comments back if no operator follows them
            if should_continue:
                while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
                    tok = self.eat()
                    if tok[0] == 'COMMENT':
                        if len(tok) > 2 and tok[2]:
                            # Standalone comment (preceded_by_newline=True) — keep for the operator
                            pending_leading.append(
                                Comment(tok[1], is_block=tok[1].startswith('/*'), is_trailing=False)
                            )
                        elif pending_trailing_inline is None:
                            # Inline comment trailing the left operand (e.g. "cond  -- note")
                            pending_trailing_inline = tok[1]
            t = self.pk()
            if t[0] == 'EOF' or t[1] == ';':
                self.pos = saved_pos
                break
            if stop_fn and stop_fn(t):
                self.pos = saved_pos
                break
            # IS [NOT] NULL / IS TRUE / IS FALSE
            if t[1] == 'IS':
                self.eat()
                self.skip_blanks()
                negated = False
                if self.pk()[1] == 'NOT':
                    negated = True
                    self.eat()
                    self.skip_blanks()
                nxt = self.pk()[1]
                if nxt == 'NULL':
                    self.eat()
                    left = IsNullOp(left, negated)
                elif nxt in ('TRUE', 'FALSE'):
                    val = self.eat()[1]
                    op = 'IS NOT' if negated else 'IS'
                    left = BinaryOp(op, left, Literal('bool', val))
                elif self.pk()[0] == 'ID' and nxt.lower() == 'json':
                    words = [self.eat()[1].upper()]
                    if self.pk()[0] in ('ID', 'KW') and self.pk()[1].lower() in ('object', 'array', 'scalar', 'value'):
                        words.append(self.eat()[1].upper())
                    if self.pk()[1] in ('WITH', 'WITHOUT') or (self.pk()[0] == 'ID' and self.pk()[1].lower() == 'without'):
                        words.append(self.eat()[1].upper())
                        while self.pk()[0] in ('ID', 'KW') and self.pk()[1].lower() in ('unique', 'keys'):
                            words.append(self.eat()[1].upper())
                    left = BinaryOp('IS NOT' if negated else 'IS', left, Literal('kw', ' '.join(words)))
                elif self.pk()[0] in ('ID', 'KW') and (
                        nxt.lower() == 'normalized' or (nxt.lower() in ('nfc', 'nfd', 'nfkc', 'nfkd')
                                                        and self.pk(1)[1].lower() == 'normalized')):
                    words = [self.eat()[1].upper()]
                    if words[0] != 'NORMALIZED':
                        words.append(self.eat()[1].upper())
                    left = BinaryOp('IS NOT' if negated else 'IS', left, Literal('kw', ' '.join(words)))
                elif nxt == 'DISTINCT' and self.pk(1)[1] == 'FROM':
                    op_str = 'IS NOT DISTINCT FROM' if negated else 'IS DISTINCT FROM'
                    self.eat(); self.eat()
                    right = self.parse_expression(stop_fn=stop_fn, min_prec=45)
                    left = BinaryOp(op_str, left, right)
                else:
                    op_str = 'IS NOT' if negated else 'IS'
                    right = self.parse_expression(stop_fn=stop_fn, min_prec=45)
                    left = BinaryOp(op_str, left, right)
                continue
            # NOT IN / NOT BETWEEN / NOT LIKE / NOT ILIKE
            if t[1] == 'NOT':
                j = 1
                while self.pk(j)[0] == 'BLANK_LINE':
                    j += 1
                nxt = self.pk(j)[1]
                if nxt == 'IN':
                    self.eat(); self.eat()
                    self.skip_blanks()
                    left = self._parse_in_rhs(left, negated=True, stop_fn=stop_fn)
                    continue
                elif nxt == 'BETWEEN':
                    self.eat(); self.eat()
                    left = self._parse_between_rhs(left, negated=True, stop_fn=stop_fn)
                    continue
                elif nxt in ('LIKE', 'ILIKE'):
                    self.eat()
                    op = self.eat()[1]
                    self.skip_blanks()
                    right = self.parse_expression(stop_fn=stop_fn, min_prec=41)
                    left = self._like_escape(BinaryOp('NOT ' + op, left, right), stop_fn)
                    continue
                elif self._at_similar_to(j):
                    self.eat(); self.eat(); self.eat()
                    self.skip_blanks()
                    right = self.parse_expression(stop_fn=stop_fn, min_prec=41)
                    left = self._like_escape(BinaryOp('NOT SIMILAR TO', left, right), stop_fn)
                    continue
            # IN
            if t[1] == 'IN':
                self.eat()
                self.skip_blanks()
                left = self._parse_in_rhs(left, negated=False, stop_fn=stop_fn)
                continue
            # BETWEEN
            if t[1] == 'BETWEEN':
                self.eat()
                left = self._parse_between_rhs(left, negated=False, stop_fn=stop_fn)
                continue
            # LIKE / ILIKE
            if t[1] in ('LIKE', 'ILIKE'):
                op = self.eat()[1]
                right = self.parse_expression(stop_fn=stop_fn, min_prec=41)
                left = self._like_escape(BinaryOp(op, left, right), stop_fn)
                continue
            # Word operators that are plain identifiers to the tokenizer
            if t[0] == 'ID' and min_prec <= 85 and t[1].lower() == 'collate':
                self.eat()
                self.skip_blanks()
                parts = []
                while self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
                    parts.append(self.eat()[1])
                    if self.pk()[0] == 'DOT':
                        parts.append(self.eat()[1])
                        continue
                    break
                left = BinaryOp('COLLATE', left, Identifier([''.join(parts)]))
                continue
            if self._at_words('at', 'time', 'zone') and min_prec <= 70:
                self.eat(); self.eat(); self.eat()
                self.skip_blanks()
                right = self.parse_expression(stop_fn=stop_fn, min_prec=71)
                left = BinaryOp('AT TIME ZONE', left, right)
                continue
            if self._at_words('at', 'local') and min_prec <= 70:
                self.eat(); self.eat()
                left = PostfixOp(left, 'AT LOCAL')
                continue
            if t[0] == 'ID' and t[1].lower() in ('isnull', 'notnull') and min_prec <= 45:
                left = PostfixOp(left, self.eat()[1].upper())
                continue
            if t[0] == 'ID' and t[1].lower() == 'overlaps' and min_prec <= 45:
                self.eat()
                self.skip_blanks()
                right = self.parse_expression(stop_fn=stop_fn, min_prec=46)
                left = BinaryOp('OVERLAPS', left, right)
                continue
            # Field selection on a composite value: (a).b, (a).*, a.b[1].c
            if t[0] == 'DOT' and isinstance(left, (Parenthesized, SubscriptExpr, FieldExpr, SubqueryExpr)):
                self.eat()
                nxt = self.pk()
                if nxt[0] in ('ID', 'KW', 'QUOTED_ID', 'STAR'):
                    left = FieldExpr(left, self.eat()[1])
                    continue
            # SIMILAR TO (two bare words, so not covered by _INFIX_PREC)
            if self._at_similar_to():
                self.eat(); self.eat()
                self.skip_blanks()
                right = self.parse_expression(stop_fn=stop_fn, min_prec=41)
                left = self._like_escape(BinaryOp('SIMILAR TO', left, right), stop_fn)
                continue
            # Array subscript / slice: expr[i], expr[lo:hi]
            if t[0] == 'SYM' and t[1] == '[':
                left = self._parse_subscript(left)
                continue
            # ANY / ALL as postfix (= ANY(...)) — handled in infix section below
            # Infix operator
            prec = None
            op_syntax = self._operator_syntax_len()
            if op_syntax:
                # a OPERATOR(pg_catalog.+) b: precedence of "any other operator"
                if _OTHER_OP_PREC < min_prec:
                    self.pos = saved_pos
                    break
                op = self._eat_operator_syntax(op_syntax)
                self.skip_blanks()
                right = self.parse_expression(stop_fn=stop_fn, min_prec=_OTHER_OP_PREC + 1)
                left = BinaryOp(op, left, right)
                continue
            if t[0] == 'OP' and t[1] in _INFIX_PREC:
                prec = _INFIX_PREC[t[1]]
            elif t[0] == 'OP' and t[1] != '::':
                prec = _OTHER_OP_PREC  # user-defined / less common operator (<->, <<=, ===, ...)
            elif t[0] == 'KW' and t[1] in _INFIX_PREC:
                prec = _INFIX_PREC[t[1]]
            elif t[0] == 'STAR':
                # In infix position '*' is multiplication, never a select-list wildcard
                prec = _INFIX_PREC['*']
            if prec is None or prec < min_prec:
                self.pos = saved_pos  # comments after the expression belong to whatever follows
                break
            op = self.eat()[1]
            self.skip_blanks()
            # :: type cast — collect type name
            if op == '::':
                type_str = self._parse_type_name()
                left = TypeCastOp(left, type_str)
                continue
            # Check for ANY/ALL on right side
            if self.pk()[1] in ('ANY', 'ALL') and self.pk(1)[1] == '(':
                quant = self.eat()[1]
                self.eat()  # (
                # Check for ARRAY[
                if self.pk()[1] == 'ARRAY' and self.pk(1)[1] == '[':
                    self.eat()  # ARRAY
                    self.eat()  # [
                    elems = self._collect_bracket_elems()
                    inner = ArrayExpr(elems)
                    if self.pk()[1] == '::':
                        self.eat()
                        type_str = self._parse_type_name()
                        inner = TypeCastOp(inner, type_str)
                elif self._query_follows():
                    inner = SubqueryExpr(self._parse_query())
                elif self.pk()[1] == 'VALUES':
                    inner = self._parse_values_expr()
                else:
                    inner = self.parse_expression(stop_fn=lambda t: t[1] == ')')
                    if isinstance(inner, SubqueryExpr):
                        # ANY((SELECT arr ...)): a scalar subquery yielding an array, not the
                        # ANY (SELECT ...) set form; the extra parens change the meaning
                        inner.scalar_in_any = True
                self.skip_blanks()
                self._close_paren()
                right = AnyAllExpr(quant, inner)
                left = BinaryOp(op, left, right)
                continue
            right = self.parse_expression(stop_fn=stop_fn, min_prec=prec + 1)
            lc = pending_leading if op in ('AND', 'OR') else []
            ltc = pending_trailing_inline if op in ('AND', 'OR') else None
            left = BinaryOp(op, left, right, leading_comments=lc, left_trailing_comment=ltc)
        return left

    def _parse_values_expr(self):
        """VALUES (..), (..) — current token is VALUES."""
        self.eat()  # VALUES
        rows = []
        while not self.done():
            self.skip_blanks()
            if self.pk()[1] == '(':
                self.eat()
                rows.append(self.collect_raw(lambda t: t[1] == ')'))
                self._close_paren()
            if self.pk()[0] == 'COMMA':
                self.eat()
                continue
            break
        return ValuesExpr(rows)

    def _at_words(self, *words):
        for i, w in enumerate(words):
            t = self.pk(i)
            if t[0] not in ('ID', 'KW') or t[1].lower() != w:
                return False
        return True

    def _at_similar_to(self, off=0):
        a, b = self.pk(off), self.pk(off + 1)
        return (a[0] == 'ID' and a[1].lower() == 'similar'
                and b[0] == 'ID' and b[1].lower() == 'to')

    def _split_slice_colon(self):
        """In arr[1:NULL] / j['a':'b'] the tokenizer saw psql variables (`:NULL`, `:'b'`);
        inside brackets the colon is a slice separator: split the token back into `:` and
        its operand (keeping the source spans aligned for the verbatim fallback)."""
        t = self.pk()
        if t[0] != 'WORD' or not t[1].startswith(':') or len(t[1]) < 2:
            return
        rest = tokenize(t[1][1:])
        p = self.pos
        self.tok[p:p + 1] = [('SYM', ':')] + rest
        if self.spans is not None:
            a, b = self.spans[p]
            self.spans[p:p + 1] = [(a, a + 1)] + [(a + 1, b)] * len(rest)

    def _parse_subscript(self, base):
        """Parse [i], [lo:hi], [:hi], [lo:] after `base` (current token is '[')."""
        self.eat()  # [
        parts = []
        is_slice = False
        stop = lambda t: t[1] in (':', ']') or t[0] == 'EOF' or (t[0] == 'WORD' and t[1].startswith(':'))
        while True:
            self.skip_blanks()
            self._split_slice_colon()
            if self.pk()[1] in (':', ']') or self.pk()[0] == 'EOF':
                parts.append(None)
            else:
                parts.append(self.parse_expression(stop_fn=stop))
            self.skip_blanks()
            self._split_slice_colon()
            if self.pk()[1] == ':':
                self.eat()
                is_slice = True
                continue
            break
        if self.pk()[1] == ']':
            self.eat()
        return SubscriptExpr(base, parts, is_slice)

    _TYPE_INTERVAL_WORDS = frozenset({'year', 'month', 'day', 'hour', 'minute', 'second', 'to'})

    def _parse_type_name(self):
        """Parse a type name after `::` / in CAST(... AS type): `int`, `character varying(10)`,
        `timestamp(3) with time zone`, `numeric(10,2)[]`, `schema.type`, `interval day to second`.

        Only genuine type words continue the name; anything else (LIKE, IS, IN, BETWEEN, ...)
        ends it so the expression parser sees it.
        """
        t = self.pk()
        if t[0] not in ('ID', 'KW', 'QUOTED_ID') or t[1] in (
                ';', 'FROM', 'WHERE', 'AND', 'OR', 'AS', ',', 'THEN', 'ELSE', 'END', 'WHEN', 'ON', 'JOIN', 'SET'):
            return 'TEXT'
        parts = [self.eat()[1]]
        while self.pk()[0] == 'DOT' and self.pk(1)[0] in ('ID', 'KW', 'QUOTED_ID'):
            self.eat()
            parts[-1] = parts[-1] + '.' + self.eat()[1]
        base = parts[0].lower()
        while True:
            progressed = False
            if self.pk()[1] == '(':
                self.eat()
                toks = self.collect_raw(lambda t: t[1] == ')')
                self._close_paren()
                parts[-1] = parts[-1] + '(' + join_expr(toks) + ')'
                progressed = True
            nxt = self.pk()
            low = nxt[1].lower() if nxt[0] in ('ID', 'KW') else ''
            if low in ('varying', 'precision'):
                parts.append(self.eat()[1])
                progressed = True
            elif (low in ('with', 'without') and self.pk(1)[0] in ('ID', 'KW') and self.pk(1)[1].lower() == 'time'
                    and self.pk(2)[0] in ('ID', 'KW') and self.pk(2)[1].lower() == 'zone'):
                parts += [self.eat()[1], self.eat()[1], self.eat()[1]]
                progressed = True
            elif base == 'interval' and low in self._TYPE_INTERVAL_WORDS:
                parts.append(self.eat()[1])
                progressed = True
            while self.pk()[1] == '[':
                self.eat()
                dim = ''
                if self.pk()[0] == 'NUM':
                    dim = self.eat()[1]
                if self.pk()[1] == ']':
                    self.eat()
                parts[-1] = parts[-1] + '[' + dim + ']'
                progressed = True
            if not progressed:
                break
        return ascii_upper(' '.join(parts))

    def _parse_in_rhs(self, left, negated, stop_fn):
        if self.pk()[1] != '(':
            # bare IN without parens — treat as raw
            return InExpr(left, negated, [])
        self.eat()  # (
        self.skip_blanks()
        if self._query_follows():
            sub = self._parse_query()
            self.skip_blanks()
            self._close_paren()
            return InExpr(left, negated, [], sub)
        if self.pk()[1] == 'VALUES':
            start = self.pos
            values_expr = self._parse_values_expr()
            self.skip_blanks()
            if self.pk()[1] != ')':
                # IN (VALUES (1), (2) ORDER BY 1 LIMIT 1): a query, not a plain row list
                self.pos = start
                sub = self.parse_values_statement()
                self.skip_blanks()
                self._close_paren()
                return InExpr(left, negated, [], sub)
            self._close_paren()
            return InExpr(left, negated, [values_expr])
        # value list
        vals = []
        lead, trail, pending = [], [], []
        while not self.done() and self.pk()[1] != ')':
            self.skip_blanks()
            t = self.pk()
            if t[1] == ')':
                break
            if t[0] == 'COMMENT':
                self.eat()
                if not t[2] and vals and trail[-1] is None:
                    trail[-1] = t[1]        # `1, -- note` trails the value before it
                else:
                    pending.append(t[1])
                continue
            if t[1] == ',':
                self.eat()
                continue
            v = self.parse_expression(stop_fn=lambda t: t[1] in (',', ')'))
            vals.append(v)
            lead.append(pending)
            trail.append(None)
            pending = []
        self._close_paren()
        return InExpr(left, negated, vals, None, lead, trail, pending)

    def _parse_between_rhs(self, left, negated, stop_fn):
        mode = ''
        self.skip_blanks()
        if self.pk()[0] in ('ID', 'KW') and self.pk()[1].lower() in ('symmetric', 'asymmetric'):
            mode = self.eat()[1].upper()
        low = self.parse_expression(stop_fn=lambda t: t[1] == 'AND' or (stop_fn and stop_fn(t)))
        if self.pk()[1] == 'AND':
            self.eat()
        high = self.parse_expression(stop_fn=stop_fn)
        return BetweenExpr(left, negated, low, high, mode)

    _INTERVAL_FIELDS = frozenset({'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND'})

    def _multiword_type_len(self, name):
        """Number of tokens after `name` that continue a multi-word type name
        (WITH/WITHOUT TIME ZONE, PRECISION, VARYING, an optional (n) precision), else 0."""
        low = name.lower()
        word = lambda j: self.pk(j)[1].upper() if self.pk(j)[0] in ('ID', 'KW') else ''
        j = 0
        if low in ('timestamp', 'time'):
            if self.pk(0)[1] == '(' and self.pk(1)[0] == 'NUM' and self.pk(2)[1] == ')':
                j = 3
            if word(j) in ('WITH', 'WITHOUT') and word(j + 1) == 'TIME' and word(j + 2) == 'ZONE':
                j += 3
            return j
        if low == 'double' and word(0) == 'PRECISION':
            return 1
        if low in ('character', 'char', 'bit', 'national') and word(0) == 'VARYING':
            return 1
        return 0

    def _interval_qualifier(self, name):
        """INTERVAL '1' DAY / '1-2' YEAR TO MONTH / '1.5' SECOND(3): the field tokens."""
        if name.lower() != 'interval':
            return []
        word = lambda j: self.pk(j)[1].upper() if self.pk(j)[0] in ('ID', 'KW') else ''
        out = []
        if word(0) not in self._INTERVAL_FIELDS:
            return out
        while True:
            out.append(('ID', self.eat()[1].upper()))  # 'ID' so SECOND(3) stays tight
            if self.pk()[1] == '(' and self.pk(1)[0] == 'NUM' and self.pk(2)[1] == ')':
                out += [self.eat(), self.eat(), self.eat()]
            if word(0) == 'TO' and word(1) in self._INTERVAL_FIELDS:
                out.append(('KW', self.eat()[1].upper()))
                continue
            return out

    def _like_escape(self, like, stop_fn):
        """[NOT] LIKE / ILIKE / SIMILAR TO pattern ESCAPE 'c': wrap the match in the ESCAPE."""
        if self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'ESCAPE':
            self.eat()
            self.skip_blanks()
            esc = self.parse_expression(stop_fn=stop_fn, min_prec=41)
            return BinaryOp('ESCAPE', like, esc)
        return like

    def _more_name_parts(self, schema, name):
        """schema.table.column / db.schema.table.column: fold the extra dotted parts
        into `schema` so `name` is the last one."""
        while (self.pk()[0] == 'DOT' and self.pk(1)[0] in ('ID', 'KW', 'QUOTED_ID', 'STAR')
               and name != '*'):
            self.eat()
            schema, name = schema + '.' + name, self.eat()[1]
        return schema, name

    def _operator_syntax_len(self):
        """Token count of an explicit operator `OPERATOR ( [schema .] op )` starting here, else 0."""
        if not (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'OPERATOR' and self.pk(1)[1] == '('):
            return 0
        j = 2
        while self.pk(j)[0] in ('ID', 'KW', 'QUOTED_ID') and self.pk(j + 1)[0] == 'DOT':
            j += 2
        if self.pk(j)[0] in ('OP', 'STAR') and self.pk(j + 1)[1] == ')':
            return j + 2
        return 0

    def _eat_operator_syntax(self, n):
        toks = [self.eat() for _ in range(n)]
        return 'OPERATOR(' + ''.join(t[1] for t in toks[2:-1]) + ')'

    def _collect_bracket_elems(self):
        """Collect comma-separated expressions inside ARRAY[...], stopping at ]."""
        elems = []
        while not self.done() and self.pk()[1] != ']':
            self.skip_blanks()
            if self.pk()[1] == ']':
                break
            if self.pk()[1] == ',':
                self.eat()
                continue
            e = self.parse_expression(stop_fn=lambda t: t[1] in (',', ']'))
            elems.append(e)
        if self.pk()[1] == ']':
            self.eat()
        return elems

    def parse_primary(self, stop_fn=None):
        self.skip_blanks()
        # Skip INLINE comments (not preceded by newline) that appear before the expression.
        # These are trailing comments that the caller will handle; we don't return them as a primary.
        # Standalone comments (preceded by newline) in the primary slot are also skipped here
        # since parse_expression's infix loop already handles standalone ones.
        while self.pk()[0] == 'COMMENT':
            self.eat()
            self.skip_blanks()
        t = self.pk()
        if t[0] == 'EOF':
            return RawTokens([])
        # NOT (unary)
        if t[1] == 'NOT':
            self.eat()
            self.skip_blanks()
            # Check for NOT followed by EXISTS
            if self.pk()[1] == 'EXISTS':
                self.eat()
                self.skip_blanks()
                if self.pk()[1] == '(':
                    self.eat()
                    sub = self._parse_query()
                    self.skip_blanks()
                    self._close_paren()
                    return ExistsExpr(sub, negated=True)
            inner = self.parse_expression(stop_fn=stop_fn, min_prec=25)
            return UnaryOp('NOT', inner)
        if t[1] == 'EXISTS':
            self.eat()
            self.skip_blanks()
            if self.pk()[1] == '(':
                self.eat()
                sub = self._parse_query()
                self.skip_blanks()
                self._close_paren()
                return ExistsExpr(sub)
            return Identifier(['EXISTS'])
        if t[1] == 'CASE':
            return self.parse_case()
        if t[1] == 'ARRAY' and self.pk(1)[1] == '[':
            self.eat()  # ARRAY
            self.eat()  # [
            elems = []
            while not self.done() and self.pk()[1] != ']':
                self.skip_blanks()
                if self.pk()[1] == ']':
                    break
                if self.pk()[1] == ',':
                    self.eat()
                    continue
                e = self.parse_expression(stop_fn=lambda t: t[1] in (',', ']'))
                elems.append(e)
            if self.pk()[1] == ']':
                self.eat()
            return ArrayExpr(elems)
        if t[1] == '[':
            # inner dimension of ARRAY[[1, 2], [3, 4]]
            self.eat()
            return ArrayExpr(self._collect_bracket_elems(), bare=True)
        if t[1] == 'CAST' and self.pk(1)[1] == '(':
            self.eat()  # CAST
            self.eat()  # (
            expr = self.parse_expression(stop_fn=lambda t: t[1] == 'AS')
            if self.pk()[1] == 'AS':
                self.eat()
            type_str = self._parse_type_name()
            self._close_paren()
            return CastExpr(expr, type_str)
        if t[1] == 'NULL':
            self.eat()
            return Literal('null', 'NULL')
        if t[1] == 'TRUE':
            self.eat()
            return Literal('bool', 'TRUE')
        if t[1] == 'FALSE':
            self.eat()
            return Literal('bool', 'FALSE')
        if t[1] in ('ANY', 'ALL') and self.pk(1)[1] == '(':
            quant = self.eat()[1]
            self.eat()
            self.skip_blanks()
            if self._query_follows():
                inner = SubqueryExpr(self._parse_query())
            elif self.pk()[1] == 'VALUES':
                inner = self._parse_values_expr()
            else:
                inner = self.parse_expression(stop_fn=lambda t: t[1] == ')')
            self.skip_blanks()
            self._close_paren()
            return AnyAllExpr(quant, inner)
        if t[0] == 'STR':
            first = self.eat()[1]
            if (first[:2].upper() == 'U&' and self.pk()[0] in ('ID', 'KW')
                    and self.pk()[1].upper() == 'UESCAPE' and self.pk(1)[0] == 'STR'):
                self.eat()
                return RawTokens([('STR', first), ('KW', 'UESCAPE'), self.eat()])
            if self.pk()[0] != 'STR':
                return Literal('string', first)
            pieces = [first]
            while self.pk()[0] == 'STR':
                pieces.append(self.eat()[1])
            return StringContinuation(pieces)
        if t[0] == 'NUM':
            return Literal('number', self.eat()[1])
        if t[0] == 'DOLLAR_BODY':
            return Literal('dollar', self.eat()[1])
        if t[0] == 'WORD':
            if self.pk(1)[0] == 'DOT' and self.pk(2)[0] in ('ID', 'KW', 'QUOTED_ID', 'WORD', 'STAR'):
                # ${schema}.table.column: a dotted name that starts with a placeholder
                parts = [self.eat()[1]]
                while self.pk()[0] == 'DOT' and self.pk(1)[0] in ('ID', 'KW', 'QUOTED_ID', 'WORD', 'STAR'):
                    self.eat()
                    parts.append(self.eat()[1])
                return Identifier(['.'.join(parts)])
            return Literal('psql_var', self.eat()[1])
        if t[0] == 'STAR':
            self.eat()
            return Literal('star', '*')
        if t[0] == 'QUOTED_ID':
            schema = self.eat()[1]
            if self.pk()[0] == 'DOT':
                self.eat()
                name = self.eat()[1] if self.pk()[0] in ('ID', 'KW', 'STAR', 'QUOTED_ID') else schema
                schema, name = self._more_name_parts(schema, name)
                if self.pk()[1] == '(':
                    return self.parse_function_call(name, schema)
                return Identifier([schema + '.' + name])
            if self.pk()[1] == '(':
                return self.parse_function_call(schema)  # "MyFunc"(...)
            return Identifier([schema])
        if t[1] == '(':
            # subquery?
            j = 1
            while self.pk(j)[0] == 'BLANK_LINE':
                j += 1
            if self._query_follows(j) or self._paren_query_at(j) or (
                    self.pk(j)[1] == 'VALUES' and self.pk(j + 1)[1] == '(') or (
                    self.pk(j)[1] == '(' and self._query_follows(j + 1) and self._set_op_after_paren(j)):
                self.eat()  # (
                sub = self._parse_paren_body()
                self.skip_blanks()
                self._close_paren()
                return SubqueryExpr(sub)
            # Grouped expression, or a row constructor when a comma follows
            self.eat()  # (
            inner = self.parse_expression(stop_fn=lambda t: t[1] == ')')
            self.skip_blanks()
            if self.pk()[0] == 'COMMA':
                items = [inner]
                while self.pk()[0] == 'COMMA':
                    self.eat()
                    items.append(self.parse_expression(stop_fn=lambda t: t[1] == ')'))
                    self.skip_blanks()
                self._close_paren()
                return RowExpr(items)
            return Parenthesized(inner, self._close_paren())
        if t[0] == 'OP' and t[1] == '-':
            self.eat()
            inner = self.parse_expression(stop_fn=stop_fn, min_prec=65)
            return UnaryOp('-', inner)
        if t[0] == 'OP' and t[1] == '+':
            self.eat()
            inner = self.parse_expression(stop_fn=stop_fn, min_prec=65)
            return UnaryOp('+', inner)
        if (t[0] in ('ID', 'KW') and t[1].upper() == 'COLLATION' and self.pk(1)[1] == 'FOR'
                and self.pk(2)[1] == '('):
            self.eat(); self.eat()  # COLLATION FOR (expr): the collation of an expression
            return RawTokens([('KW', 'COLLATION'), ('KW', 'FOR')] + self._collect_balanced_parens_raw())
        op_syntax = self._operator_syntax_len()
        if op_syntax:
            # prefix OPERATOR(pg_catalog.-) x
            op = self._eat_operator_syntax(op_syntax)
            inner = self.parse_expression(stop_fn=stop_fn, min_prec=65)
            return UnaryOp(op, inner)
        nt = self.pk(1)
        if (t[0] == 'OP' and t[1] not in ('::', '=', '<', '>', '<=', '>=', '<>', '!=', '/', '%')
                and nt[0] not in ('COMMA', 'RPAR', 'SEMI', 'COMMENT', 'BLANK_LINE', 'EOF')
                and not (nt[0] == 'KW' and (nt[1] in _NEVER_PRIMARY_KWS or nt[1] in _CLAUSE_KWS))):
            # prefix operator: ~x, |/ 25, @ -5, !! 5, ... (a lone `@@` is a template
            # placeholder, kept by the raw fallback below)
            self.eat()
            inner = self.parse_expression(stop_fn=stop_fn, min_prec=65)
            return UnaryOp(t[1], inner)
        if t[0] == 'KW' and t[1] in _NEVER_PRIMARY_KWS and not (
                t[1] in ('DELETE', 'INSERT', 'UPDATE', 'SET') and self.pk(1)[1] == '('):
            # (hstore's delete(h, 'k') & co. are functions named like statements)
            raise SqlSyntaxError(f"Unexpected keyword '{t[1]}' where an expression was expected")
        # ID or KW (identifier or function call)
        if t[0] in ('ID', 'KW'):
            name = self.eat()[1]
            # GROUP BY special forms: ROLLUP(...), CUBE(...), GROUPING SETS(...)
            if name.upper() == 'GROUPING' and self.pk()[1].upper() == 'SETS' and self.pk(1)[1] == '(':
                toks = [('ID', name), self.eat()]  # GROUPING SETS
                toks.extend(self._collect_balanced_parens_raw())
                return RawTokens(toks)
            if name.upper() in ('ROLLUP', 'CUBE') and self.pk()[1] == '(':
                toks = [('KW', name.upper())]
                toks.extend(self._collect_balanced_parens_raw())
                return RawTokens(toks)
            # qualified name (schema.table or schema.func)
            schema = None
            if self.pk()[0] == 'DOT':
                self.eat()
                schema = name
                name = self.eat()[1] if self.pk()[0] in ('ID', 'KW', 'STAR', 'QUOTED_ID', 'WORD') else name
                schema, name = self._more_name_parts(schema, name)
            # typed literal with a multi-word type: TIMESTAMP(3) WITH TIME ZONE '...',
            # DOUBLE PRECISION '1.5', CHARACTER VARYING 'x', ...
            if schema is None:
                n = self._multiword_type_len(name)
                if n and self.pk(n)[0] == 'STR':
                    # (words as upper-case 'ID' so a following (n) stays tight: SECOND(3))
                    toks = [('ID', name.upper())] + [
                        ('ID', t[1].upper()) + t[2:] if t[0] in ('ID', 'KW') else t
                        for t in (self.eat() for _ in range(n))]
                    return RawTokens(toks + [self.eat()] + self._interval_qualifier(name))
            # typed literal with a precision: interval(2) '1 day', numeric(10, 2) '1.5'
            if self.pk()[1] == '(':
                j = 1
                while self.pk(j)[0] == 'NUM' and self.pk(j + 1)[1] in (',', ')'):
                    j += 2 if self.pk(j + 1)[1] == ',' else 1
                if j > 1 and self.pk(j - 1)[0] == 'NUM' and self.pk(j)[1] == ')' and self.pk(j + 1)[0] == 'STR':
                    head = [('ID', schema), ('DOT', '.'), ('ID', name)] if schema else [('ID', name)]
                    toks = head + [self.eat() for _ in range(j + 1)] + [self.eat()]
                    return RawTokens(toks + self._interval_qualifier(name))
            # function call
            if self.pk()[1] == '(':
                return self.parse_function_call(name, schema)
            # Typed literal: any type name followed by a string, e.g. interval '90 days',
            # date '...', point '(1,2)', int4range '[1,3)', pg_catalog.point '...'
            # (in expression position `name 'string'` can only be that)
            if self.pk()[0] == 'STR':
                str_val = self.eat()[1]
                head = [('ID', schema), ('DOT', '.'), ('ID', name)] if schema else [('ID', name)]
                return RawTokens(head + [('STR', str_val)] + self._interval_qualifier(name))
            return Identifier([schema + '.' + name] if schema else [name])
        # Fallback: collect as raw tokens
        toks = [self.eat()]
        return RawTokens(toks)

    def parse_case(self):
        self.eat()  # CASE
        gaps = {'when': [], 'else': [], 'end': []}
        pending = self._collect_gap_comments()
        operand = None
        if self.pk()[1] not in ('WHEN', 'END'):
            operand = self.parse_expression(stop_fn=lambda t: t[1] in ('WHEN', 'END'))
            pending += self._collect_gap_comments()
        branches = []
        while self.pk()[1] == 'WHEN':
            gaps['when'].append(pending)
            self.eat()  # WHEN
            when_expr = self.parse_expression(stop_fn=lambda t: t[1] == 'THEN')
            self._skip_comments()
            if self.pk()[1] == 'THEN':
                self.eat()
            then_expr = self.parse_expression(stop_fn=lambda t: t[1] in ('WHEN', 'ELSE', 'END'))
            branches.append((when_expr, then_expr))
            pending = self._collect_gap_comments()
        else_expr = None
        if self.pk()[1] == 'ELSE':
            gaps['else'] = pending
            self.eat()
            else_expr = self.parse_expression(stop_fn=lambda t: t[1] == 'END')
            pending = self._collect_gap_comments()
        gaps['end'] = pending
        if self.pk()[1] == 'END':
            self.eat()
        return CaseExpr(operand, branches, else_expr, gaps)

    def parse_function_call(self, name, schema=None):
        self.eat()  # (
        distinct = False
        star_arg = False
        args = []
        order_by = []
        filter_clause = None
        over_clause = None
        special = None
        self.skip_blanks()
        if self.pk()[1] == 'DISTINCT':
            distinct = True
            self.eat()
        args_start = self.pos
        keyword_args = False
        after_order_by = None
        if self.pk()[1] == '*' or self.pk()[0] == 'STAR':
            star_arg = True
            self.eat()
        elif self.pk()[1] != ')':
            # Check if single SELECT arg (subquery as function argument, e.g. ARRAY(SELECT ...))
            if self._query_follows():
                sub = self._parse_query()
                sq = SubqueryExpr(sub)
                sq.in_call_parens = True  # f(SELECT ...): the call's own parens enclose the query
                args.append(sq)
                self.skip_blanks()
                if self.pk()[1] != ')':
                    # JSON_ARRAY(SELECT ... RETURNING jsonb): keyword arguments after the query
                    after_order_by = self._parse_special_args(self._CALL_ARG_WORDS)
            else:
                # parse args
                arg_comments = {}
                while not self.done() and self.pk()[1] != ')':
                    self.skip_blanks()
                    if self.pk()[0] == 'COMMENT':
                        # `f(a, b -- note\n)`: keep the comment with the argument before it
                        while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
                            t = self.eat()
                            if t[0] == 'COMMENT':
                                arg_comments.setdefault(len(args) - 1, []).append(t[1])
                        continue
                    if self.pk()[1] == ')':
                        break
                    if self.pk()[1] == ',':
                        self.eat()
                        continue
                    if self.pk()[1] == 'ORDER' and self.pk(1)[1] == 'BY':
                        self.eat(); self.eat()
                        order_by = self.parse_order_by_list_until_rpar()
                        if self.pk()[1] != ')':
                            # ... ORDER BY b NULL ON NULL RETURNING jsonb (SQL/JSON aggregates)
                            after_order_by = self._parse_special_args(self._CALL_ARG_WORDS)
                        break
                    # Keyword-style argument lists: EXTRACT(f FROM x), SUBSTRING(s FROM a FOR b),
                    # TRIM(BOTH c FROM s), POSITION(a IN b), OVERLAY(s PLACING r FROM a FOR b)
                    if name.upper() in self._SPECIAL_ARG_FUNCS and not args and special is None:
                        special = self._parse_special_args()
                        break
                    if (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() in self._CALL_ARG_WORDS
                            and self.pk()[1] in _NEVER_PRIMARY_KWS):
                        keyword_args = True  # JSON_OBJECT(RETURNING json): starts with a keyword
                        break
                    arg = self.parse_expression(stop_fn=lambda t: t[1] in (',', ')') or
                                                 (t[1] == 'ORDER' and self.pk(1)[1] == 'BY'))
                    args.append(arg)
                    j = 0
                    while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
                        j += 1
                    nt = self.pk(j)
                    if not (nt[1] in (',', ')') or nt[0] == 'EOF'
                            or (nt[1] == 'ORDER' and self.pk(j + 1)[1] == 'BY')):
                        # an argument followed by a word, not a comma: keyword-style syntax
                        # (xmlelement(NAME x), VARIADIC arr, xmlexists(x PASSING BY VALUE y),
                        # json_object('k' VALUE v), ...). Re-read the whole list that way so
                        # no comma is ever inserted between its parts.
                        keyword_args = True
                        break
                if keyword_args:
                    self.pos = args_start
                    args, arg_comments = [], {}
                    special = self._parse_special_args(self._CALL_ARG_WORDS)
        self._close_paren()
        # WITHIN GROUP (ORDER BY ...): ordered-set aggregates
        within_group = None
        if (self.pk()[0] in ('ID', 'KW') and self.pk()[1].upper() == 'WITHIN' and self.pk(1)[1] == 'GROUP'
                and self.pk(2)[1] == '(' and self.pk(3)[1] == 'ORDER' and self.pk(4)[1] == 'BY'):
            for _ in range(5):
                self.eat()
            within_group = self.parse_order_by_list_until_rpar()
            self._close_paren()
        # FILTER clause
        if self.pk()[1] == 'FILTER' and self.pk(1)[1] == '(':
            self.eat()  # FILTER
            self.eat()  # (
            if self.pk()[1] == 'WHERE':
                self.eat()
            filter_clause = self.parse_expression(stop_fn=lambda t: t[1] == ')')
            self._close_paren()
        # OVER clause
        if self.pk()[1] == 'OVER':
            self.eat()
            if self.pk()[1] == '(':
                self.eat()
                over_clause = self.parse_window_spec()
            elif self.pk()[0] in ('ID', 'KW'):
                # named window
                wname = self.eat()[1]
                over_clause = WindowSpec([], [], ref_name=wname)
        # (a quoted name is case-sensitive: "MyFunc" must stay as written)
        call = FunctionCall(name if name.startswith('"') else ascii_upper(name), schema, args, distinct, star_arg,
                            order_by, filter_clause, over_clause, special)
        if not star_arg and special is None and args and 'arg_comments' in locals():
            call.arg_comments = arg_comments
        call.within_group = within_group
        call.after_order_by = after_order_by
        return call

    _SPECIAL_ARG_FUNCS = frozenset({'EXTRACT', 'SUBSTRING', 'TRIM', 'POSITION', 'OVERLAY'})

    _SPECIAL_ARG_WORDS = frozenset({
        'FROM', 'FOR', 'IN', 'PLACING', 'BOTH', 'LEADING', 'TRAILING', 'SIMILAR', 'ESCAPE',
    })

    # Words of keyword-style argument lists in general (SQL/XML, SQL/JSON, VARIADIC, ...).
    _CALL_ARG_WORDS = _SPECIAL_ARG_WORDS | frozenset({
        'VARIADIC', 'NAME', 'PASSING', 'BY', 'REF', 'VALUE', 'DOCUMENT', 'CONTENT', 'VERSION',
        'STANDALONE', 'AS', 'COLUMNS', 'PATH', 'DEFAULT', 'ON', 'ERROR', 'EMPTY', 'FORMAT',
        'JSON', 'ENCODING', 'RETURNING', 'WITH', 'WITHOUT', 'WRAPPER', 'CONDITIONAL',
        'UNCONDITIONAL', 'QUOTES', 'KEEP', 'OMIT', 'UNIQUE', 'KEYS', 'ABSENT', 'INDENT',
        'SCALAR', 'STRING', 'NESTED', 'ORDINALITY', 'EXISTS', 'ERROR',
    })

    def _parse_special_args(self, words=None):
        """Keyword-style arguments (EXTRACT/SUBSTRING/TRIM/POSITION/OVERLAY, and any call whose
        arguments aren't a plain comma list) as ('kw', W) / ('comma', ',') / ('expr', node) items."""
        items = []
        general = words is not None
        words = words if general else self._SPECIAL_ARG_WORDS
        while not self.done() and self.pk()[1] != ')':
            self.skip_blanks()
            t = self.pk()
            if t[1] == ')':
                break
            if t[0] == 'COMMENT':
                # a `--` comment would swallow the rest of the inline argument list
                raise SqlSyntaxError('comment inside a keyword-style argument list')
            if t[0] == 'COMMA':
                self.eat()
                items.append(('comma', ','))
                continue
            if general and t[0] in ('ID', 'KW') and t[1].upper() == 'COLUMNS' and self.pk(1)[1] == '(':
                # JSON_TABLE (... COLUMNS (name type PATH '..', NESTED PATH '..' COLUMNS (...)))
                self.eat()
                items.append(('kw', 'COLUMNS'))
                items.append(('expr', RawTokens(self._collect_balanced_parens_raw())))
                continue
            if t[0] in ('ID', 'KW') and t[1].upper() in words and (
                    general or not items or items[-1][0] != 'kw' or t[1].upper() in ('FROM',)):
                items.append(('kw', self.eat()[1].upper()))
                continue
            start = self.pos
            expr = self.parse_expression(
                stop_fn=lambda t: t[1] == ')' or t[0] in ('COMMA', 'COMMENT')
                or (t[0] in ('ID', 'KW') and t[1].upper() in words))
            if self.pos == start:  # nothing parsed: keep the token as written
                expr = RawTokens([self.eat()])
            items.append(('expr', expr))
        return items

    def parse_window_spec(self):
        partition_by = []
        order_by = []
        frame = None
        base_name = None
        self.skip_blanks()
        if (self.pk()[0] in ('ID', 'QUOTED_ID') and self.pk()[1].lower() not in ('rows', 'range', 'groups')
                and self.pk(1)[1] != '('):
            base_name = self.eat()[1]
        if self.pk()[1] == 'PARTITION' and self.pk(1)[1] == 'BY':
            self.eat(); self.eat()
            partition_end = _WINDOW_FRAME_KWS | {'ORDER', ')'}
            while not self.done() and self.pk()[1] not in partition_end:
                self.skip_blanks()
                if self.pk()[1] in partition_end:
                    break
                if self.pk()[1] == ',':
                    self.eat()
                    continue
                e = self.parse_expression(stop_fn=lambda t: t[1] in partition_end or t[1] == ',')
                partition_by.append(e)
        if self.pk()[1] == 'ORDER' and self.pk(1)[1] == 'BY':
            self.eat(); self.eat()
            order_by = self.parse_order_by_list_until_rpar()
        if self.pk()[1] in _WINDOW_FRAME_KWS:
            toks = self.collect_raw(lambda t: t[1] == ')')
            toks = [('KW', t[1].upper()) + t[2:] if t[0] == 'ID' and t[1].lower() in ('exclude', 'ties', 'others', 'no')
                    else t for t in toks]
            frame = join_expr(toks)
        self._close_paren()
        return WindowSpec(partition_by, order_by, frame, base_name)

    def parse_order_by_list(self):
        items = []
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[1] in _ORDER_BY_END_KWS or t[0] == 'EOF':
                break
            if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
                break  # INSERT ... SELECT ... ORDER BY x ON CONFLICT ...
            if t[0] == 'COMMENT':
                break  # leave in stream for parse_select to collect
            if t[1] == ',':
                self.eat()
                continue
            if t[1] == ')':
                break
            expr = self.parse_expression(stop_fn=lambda t: t[1] in _ORDER_ITEM_END_KWS or t[0] == 'EOF')
            direction = None
            nulls = None
            using = None
            if self.pk()[1] in ('ASC', 'DESC'):
                direction = self.eat()[1]
            elif self.pk()[1] == 'USING' and self.pk(1)[0] == 'OP':
                self.eat()
                using = self.eat()[1]
            elif self.pk()[1] == 'USING':
                self.eat()
                n = self._operator_syntax_len()  # USING operator(public.<^)
                if not n:
                    raise SqlSyntaxError('ORDER BY ... USING: operator expected')
                using = self._eat_operator_syntax(n)
            if self.pk()[1] == 'NULLS':
                self.eat()
                if self.pk()[1] in ('FIRST', 'LAST'):
                    nulls = self.eat()[1]
            items.append(OrderItem(expr, direction, nulls, using))
            if self._list_ends_here():
                break
        return items

    def _list_ends_here(self):
        """After a list item: True when the next significant token is neither a comma nor
        something that ends the list normally, i.e. the next statement starts here (the
        current one has no terminating `;`)."""
        j = 0
        while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
            j += 1
        nt = self.pk(j)
        if nt[0] in ('COMMA', 'EOF') or nt[1] in (',', ')', ';'):
            return False
        if (nt[1] in _CLAUSE_KWS or nt[1] in _QUERY_TAIL_KWS or nt[1] in _ORDER_ITEM_KWS
                or nt[1] in _WINDOW_FRAME_KWS or nt[1] in ('RETURNING', 'WINDOW', 'ON')):
            return False
        return (nt[0] in ('KW', 'ID', 'META', 'META_INLINE') and nt[1].upper() in _NEXT_STATEMENT_KWS
                or nt[0] in ('META', 'META_INLINE'))

    def parse_order_by_list_until_rpar(self):
        items = []
        # ROWS/RANGE/GROUPS mark the start of a window frame spec — stop there
        list_end = _WINDOW_FRAME_KWS | {')'}
        _stop = list_end | _ORDER_ITEM_KWS | {','}
        while not self.done() and self.pk()[1] not in list_end:
            self.skip_blanks()
            if self.pk()[1] in list_end:
                break
            if self.pk()[1] == ',':
                self.eat()
                continue
            expr = self.parse_expression(stop_fn=lambda t: t[1] in _stop or t[0] == 'EOF')
            direction = None
            nulls = None
            using = None
            if self.pk()[1] in ('ASC', 'DESC'):
                direction = self.eat()[1]
            elif self.pk()[1] == 'USING' and self.pk(1)[0] == 'OP':
                self.eat()
                using = self.eat()[1]
            elif self.pk()[1] == 'USING':
                self.eat()
                n = self._operator_syntax_len()  # USING operator(public.<^)
                if not n:
                    raise SqlSyntaxError('ORDER BY ... USING: operator expected')
                using = self._eat_operator_syntax(n)
            if self.pk()[1] == 'NULLS':
                self.eat()
                if self.pk()[1] in ('FIRST', 'LAST'):
                    nulls = self.eat()[1]
            items.append(OrderItem(expr, direction, nulls, using))
            self.skip_blanks()
            if self.pk()[1] not in list_end and self.pk()[1] != ',':
                break  # json_arrayagg(a ORDER BY b NULL ON NULL ...): keyword arguments follow
        return items

    def parse_expr_list(self, stop_fn):
        items = []
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if stop_fn(t):
                break
            if t[1] == ')':
                break
            if t[1] == ',':
                self.eat()
                continue
            e = self.parse_expression(stop_fn=lambda t: stop_fn(t) or t[1] in (',', ')'))
            items.append(e)
            if self._list_ends_here():
                break
        return items
