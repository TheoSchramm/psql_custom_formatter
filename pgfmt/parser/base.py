"""Parser core: token cursor, comment helpers, statement loop and dispatch, error fallback."""

from __future__ import annotations
from ..constants import UTILITY_STARTERS, _QUERY_TAIL_KWS, _SET_OP_KWS
from ..nodes import (
    CommentGroup, DeleteStatement, ExpressionFragment, InsertStatement, MetaStatement,
    RawStatement, UpdateStatement, VerbatimStatement,
)


class BaseParserMixin:
    """Parser core: token cursor, comment helpers, statement loop and dispatch, error fallback."""

    def __init__(self, tokens, src=None, spans=None):
        self.tok = tokens
        self.pos = 0
        # source text + token offsets: when given, a statement that fails to parse
        # becomes a VerbatimStatement instead of failing the whole file
        self.src = src
        self.spans = spans

    def pk(self, off=0):
        p = self.pos + off
        return self.tok[p] if p < len(self.tok) else ('EOF', '')

    def eat(self):
        t = self.tok[self.pos]
        self.pos += 1
        return t

    def done(self):
        return self.pos >= len(self.tok)

    def skip_blanks(self):
        while not self.done() and self.pk()[0] == 'BLANK_LINE':
            self.eat()

    def skip_blanks_and_comments(self):
        """Skip blank lines and standalone comments between SQL clauses."""
        while not self.done() and self.pk()[0] in ('BLANK_LINE', 'COMMENT'):
            self.eat()

    def _collect_comments(self):
        """Consume blank lines and comments between clauses, returning comment texts in order."""
        out = []
        while not self.done() and self.pk()[0] in ('BLANK_LINE', 'COMMENT'):
            tok = self.eat()
            if tok[0] == 'COMMENT':
                out.append(tok[1])
        return out

    def parse_all(self):
        results = []
        while not self.done():
            if self.pk()[1] == ';':
                self.eat()
                continue
            if self.pk()[0] == 'BLANK_LINE':
                self.eat()
                continue

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

            while not self.done() and self.pk()[1] == ';':
                self.eat()

            if comment_groups:
                results.append(CommentGroup(comment_groups, comments_had_trailing_blank))

            if self.done():
                break

            start_pos = self.pos
            try:
                stmt = self.parse_statement()
            except Exception:
                if self.spans is None:
                    raise
                stmt = self._verbatim_statement(start_pos)
            if isinstance(stmt, (UpdateStatement, DeleteStatement, InsertStatement)):
                # these parsers skip trailing comments (dropping them): give back the ones
                # after a blank line so they lead the next statement. (Raw/utility statements
                # keep comment tokens in their own token list, so they must NOT do this.)
                self._give_back_comments_after_blank()
            results.append(stmt)
            try:
                setattr(stmt, '_src_comments',
                        [t[1] for t in self.tok[start_pos:self.pos] if t[0] == 'COMMENT'])
                if self.spans is not None:
                    setattr(stmt, '_src_text', self._source_text(start_pos, self.pos))
            except AttributeError:
                pass
            while self.pk()[0] == 'META_INLINE':
                tail = self.eat()[1]
                target = stmt
                setattr(target, 'meta_suffix', (getattr(target, 'meta_suffix', '') + ' ' + tail).strip())

        return results

    def _source_text(self, start, end):
        """Source text of tokens [start, end), trailing blank lines excluded."""
        while end > start and self.tok[end - 1][0] == 'BLANK_LINE':
            end -= 1
        if end <= start:
            return ''
        return self.src[self.spans[start][0]:self.spans[end - 1][1]].strip()

    def _verbatim_statement(self, start_pos):
        """Fallback for a statement that failed to parse: take everything up to
        and including the next `;` (or up to a psql meta-command / EOF), plus a
        trailing comment on the same line, and keep it as written."""
        self.pos = start_pos
        while not self.done():
            t = self.eat()
            if t[0] == 'SEMI':
                break
            if self.pk()[0] in ('META', 'META_INLINE'):
                break
        while (not self.done() and self.pk()[0] == 'COMMENT' and len(self.pk()) > 2
               and not self.pk()[2]):
            self.eat()
        return VerbatimStatement(self._source_text(start_pos, self.pos))

    def parse_statement(self):
        self.skip_blanks()
        t = self.pk()
        if t[1] == 'SELECT':
            return self.parse_select()
        elif t[1] == 'VALUES' and self.pk(1)[1] == '(':
            return self.parse_values_statement()
        elif t[1] == '(' and (self._query_follows(1) or self._paren_query_at(1) or self._paren_query_at(0)):
            return self.parse_paren_select()
        elif t[1] == 'TABLE' and self.pk(1)[0] in ('ID', 'KW', 'QUOTED_ID'):
            return self.parse_utility()  # TABLE [ONLY] name [*]: shorthand for SELECT * FROM name
        elif t[1] == 'WITH':
            return self.parse_with()
        elif t[1] == 'INSERT':
            return self.parse_insert()
        elif t[1] == 'UPDATE':
            return self.parse_update()
        elif t[1] == 'DELETE':
            return self.parse_delete()
        elif t[1] == 'CREATE':
            return self.parse_create()
        elif t[1] == 'DO' and (self.pk(1)[0] in ('DOLLAR_BODY', 'STR') or (
                self.pk(1)[0] in ('ID', 'KW') and self.pk(1)[1].lower() == 'language')):
            return self.parse_do_block()
        elif t[0] == 'DOLLAR_BODY':
            stmt = RawStatement([self.eat()])
            self.skip_blanks()
            if self.pk()[1] == ';':
                self.eat()
                stmt._has_semicolon = True
            return stmt
        elif t[0] in ('META', 'META_INLINE'):
            self.eat()
            return MetaStatement(t[1], attached=self.pk()[0] not in ('BLANK_LINE', 'EOF'))
        elif t[0] in ('ID', 'KW') and t[1].upper() == 'EXPLAIN':
            return self.parse_explain()
        elif t[0] in ('ID', 'KW') and t[1].upper() == 'MERGE' and self.pk(1)[1] == 'INTO':
            return self.parse_merge()
        elif t[0] in ('ID', 'KW') and t[1].upper() in UTILITY_STARTERS:
            return self.parse_utility()
        else:
            frag = self._try_expression_fragment()
            if frag is not None:
                return frag
            return self.parse_raw_statement()

    def _try_expression_fragment(self):
        """Parse `CASE ...` / `func(...)` up to `;` or EOF as a select-list fragment.
        Returns None (position unchanged) if it isn't one."""
        t, nxt = self.pk(), self.pk(1)
        if not (t[1] == 'CASE' or (t[0] in ('ID', 'KW') and nxt[1] == '(')):
            return None
        start = self.pos
        try:
            items = self.parse_select_list()
            extra = list(self._select_list_extra_comments)
            self.skip_blanks()
        except Exception:
            items = None
        if not items or self.pk()[0] not in ('EOF', 'SEMI'):
            self.pos = start
            return None
        frag = ExpressionFragment(items, extra)
        if self.pk()[0] == 'SEMI':
            self.eat()
            frag._has_semicolon = True
        return frag

    def _close_paren(self):
        """Consume `)`, tolerating comments/blank lines before it.

        A line comment before a closing paren (`(a = 1 -- note\n)`) used to leave the
        `)` unconsumed and mis-nest everything after it (and could spin a loop forever).
        Returns the comments that sat before the paren; [] when the next token isn't `)`.
        """
        j = 0
        while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
            j += 1
        if self.pk(j)[1] != ')':
            return []
        comments = []
        for _ in range(j):
            tok = self.eat()
            if tok[0] == 'COMMENT':
                comments.append(tok[1])
        self.eat()
        return comments

    def _cte_follows(self):
        """Whether the WITH here starts a query (WITH [RECURSIVE] name [(cols)] AS ...)."""
        n1, n2 = self.pk(1), self.pk(2)
        if n1[1] == 'RECURSIVE':
            return True
        return n1[0] in ('ID', 'KW', 'QUOTED_ID') and (n2[1] == 'AS' or n2[1] == '(')

    def _paren_query_at(self, off=0):
        """Whether pk(off) is `(` opening a query that _parse_paren_body handles beyond a
        plain SELECT/WITH: VALUES, or more parentheses around a query."""
        if self.pk(off)[1] != '(':
            return False
        j, opened = off, 0
        while self.pk(j)[1] == '(':
            j += 1
            opened += 1
            while self.pk(j)[0] in ('BLANK_LINE', 'COMMENT'):
                j += 1
        return self.pk(j)[1] in ('SELECT', 'WITH', 'VALUES') and (opened > 1 or self.pk(j)[1] == 'VALUES')

    def _parse_paren_body(self):
        """The query inside `(` ... `)` (the `(` already consumed, the `)` left): a
        SELECT / WITH query, VALUES rows, or a further parenthesized query with set
        operations, e.g. ((SELECT 1) UNION (VALUES (2)))."""
        j = 0
        while self.pk(j)[0] in ('BLANK_LINE', 'COMMENT'):
            j += 1
        if self.pk(j)[1] == '(' and (self._query_follows(j + 1) or self._paren_query_at(j)):
            self.skip_blanks()
            return self.parse_paren_select()
        if self.pk(j)[1] == 'VALUES' and self.pk(j + 1)[1] == '(':
            self.skip_blanks()
            return self.parse_values_statement()
        return self._parse_query()

    def _set_op_after_paren(self, off):
        """pk(off) is `(`: whether UNION / INTERSECT / EXCEPT follows its matching `)`."""
        depth, j = 0, off
        while self.pk(j)[0] != 'EOF':
            if self.pk(j)[1] == '(':
                depth += 1
            elif self.pk(j)[1] == ')':
                depth -= 1
                if depth == 0:
                    j += 1
                    while self.pk(j)[0] in ('BLANK_LINE', 'COMMENT'):
                        j += 1
                    return self.pk(j)[1] in _SET_OP_KWS
            j += 1
        return False

    def _query_follows(self, off=0):
        """Whether a SELECT/WITH query starts at `off`, past blank lines and comments
        (e.g. "(\\n    -- note\\n    SELECT ..."). Comments themselves are not consumed."""
        while self.pk(off)[0] in ('BLANK_LINE', 'COMMENT'):
            off += 1
        return self.pk(off)[1] in ('SELECT', 'WITH')

    def _parse_query(self):
        """A parenthesized query body: SELECT ... or WITH ... SELECT ...

        Comments between "(" and the first keyword become the query's leading_comments,
        rendered on their own lines above SELECT/WITH."""
        comments = self._collect_comments()
        if self.pk()[1] == 'WITH':
            query = self.parse_with()
        else:
            query = self.parse_select(stop_at_rpar=True)
        query.leading_comments = comments + query.leading_comments
        return query

    def _comments_before(self, stmt, kws):
        """If one of `kws` follows (past blank lines/comments), take those comments as the
        statement's own; otherwise leave the stream untouched."""
        j = 0
        while self.pk(j)[0] in ('COMMENT', 'BLANK_LINE'):
            j += 1
        if j and self.pk(j)[1] in kws:
            for _ in range(j):
                tok = self.eat()
                if tok[0] == 'COMMENT':
                    stmt.trailing_comments.append(tok[1])

    def _release_next_statement_comments(self, comments):
        """Comments that follow a blank line after the statement's last real token lead the
        NEXT statement. Give them back to the stream (and drop them from `comments`).

        Inline comments right after the last token (before any blank line) stay with the
        statement; so do comments in front of a clause that continues it.
        """
        nxt = self.pk()
        if (nxt[1] in _QUERY_TAIL_KWS or nxt[1] in _SET_OP_KWS or nxt[1] in (';', 'RETURNING', ')')
                or (nxt[1] == 'ON' and self.pk(1)[1] == 'CONFLICT')):
            return comments
        k = self.pos
        while k > 0 and self.tok[k - 1][0] in ('COMMENT', 'BLANK_LINE'):
            k -= 1
        for idx in range(k, self.pos):
            if self.tok[idx][0] == 'BLANK_LINE':
                after = sum(1 for t in self.tok[idx:self.pos] if t[0] == 'COMMENT')
                if after:
                    self.pos = idx
                    comments = comments[:max(0, len(comments) - after)]
                break
        return comments

    def _give_back_comments_after_blank(self):
        """Hand back trailing comments that follow a blank line after the last real token
        (for statements whose parser dropped them)."""
        k = self.pos
        while k > 0 and self.tok[k - 1][0] in ('COMMENT', 'BLANK_LINE'):
            k -= 1
        for idx in range(k, self.pos):
            if self.tok[idx][0] == 'BLANK_LINE':
                if any(t[0] == 'COMMENT' for t in self.tok[idx:self.pos]):
                    self.pos = idx
                break

    def collect_raw(self, stop_fn):
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

    def _skip_comments(self):
        """Skip comments/blank lines between the parts of a construct (the safety net keeps them)."""
        while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
            self.eat()

    def _collect_gap_comments(self):
        """Consume comments/blank lines; return the comments as (text, on_own_line)."""
        out = []
        while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
            t = self.eat()
            if t[0] == 'COMMENT':
                out.append((t[1], len(t) > 2 and bool(t[2])))
        return out
