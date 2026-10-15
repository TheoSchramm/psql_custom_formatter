"""Formatter core: output buffer, indentation, comments, statement loop and dispatch, inlining checks."""

from __future__ import annotations
import collections
from ..constants import (
    COMMENT_SEP, INDENT, INLINE_SUBQUERY_MAX_CHARS, INLINE_WHERE_MAX_CHARS, SqlSyntaxError,
)
from ..nodes import (
    CommentGroup, CreateIndexStatement, CreateTableAsStatement, CreateTableStatement,
    CreateViewStatement, DeleteStatement, DoBlock, ExplainStatement, ExpressionFragment,
    InsertStatement, MergeStatement, MetaStatement, RawStatement, SelectStatement,
    UpdateStatement, UtilityStatement, ValuesStatement, VerbatimStatement, WithStatement,
)
from ..tokenizer import tokenize


_FOLD = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')


def _significant_tokens(sql):
    """The tokens that carry meaning, normalized the way formatting is allowed to change
    them: no whitespace/comments, case-folded words, and no AS (aliases gain/lose it)."""
    out = []
    for t in tokenize(sql):
        kind, val = t[0], t[1]
        if kind in ('BLANK_LINE', 'COMMENT'):
            continue
        if kind in ('KW', 'ID', 'WORD'):
            val = val.translate(_FOLD)  # PostgreSQL folds only ASCII: DESCRIÇÃO != descrição
            if val == 'as':
                continue
        elif kind in ('META', 'META_INLINE'):
            val = ' '.join(val.split())
        elif kind == 'SEMI' and out and out[-1] == ';':
            continue  # `;;` is an empty statement: dropping it changes nothing
        out.append(val)
    return out


def _same_tokens(src, rendered):
    return _significant_tokens(src) == _significant_tokens(rendered)


class BaseFormatterMixin:
    """Formatter core: output buffer, indentation, comments, statement loop and dispatch, inlining checks."""

    def __init__(self):
        self.out = []
        self._last_was_comment = False

    def w(self, s):
        self.out.append(s)

    def _format_subquery_body(self, query, base):
        """Format the query inside parentheses. A WITH ... body is rendered on its own at
        column 0 and then indented, since format_with is written for the top level."""
        if isinstance(query, SelectStatement):
            self.format_select(query, base, is_subquery=True)
            return
        sub = type(self)()
        sub.format_statement(query)
        text = ''.join(sub.out).rstrip(';')
        self.w('\n'.join((INDENT * base + ln) if ln.strip() else ln for ln in text.split('\n')))

    def _inline_subquery(self, query, max_chars=INLINE_SUBQUERY_MAX_CHARS):
        """Return one-line rendering of subquery if it fits within max_chars (incl. parens), else None."""
        if not isinstance(query, SelectStatement) or query.leading_comments:
            return None
        scratch = type(self)()
        scratch.format_select(query, base=0, is_subquery=True)
        if getattr(scratch, '_unjoinable', False):
            return None  # line breaks that are part of the SQL (string continuation)
        rendered = ''.join(scratch.out)
        one_line = ''
        for line in rendered.splitlines():
            line = line.strip()
            if not line:
                continue
            if self._line_ends_in_comment(line):
                return None  # a `--` comment would swallow everything joined after it
            one_line += (line if line.startswith(',') or not one_line else ' ' + line)
        full = '(' + one_line + ')'
        return full if len(full) <= max_chars else None

    def _fits_inline(self, expr, ci, max_chars=INLINE_WHERE_MAX_CHARS):
        """Whether expr's one-line rendering (at indent level ci) fits within max_chars."""
        scratch = type(self)()
        scratch.format_expression(expr, ci, inline=True)
        rendered = ''.join(scratch.out)
        if '\n' in rendered:
            return False
        return len(INDENT) * ci + len(rendered) <= max_chars

    def nl(self, level):
        self.w('\n' + INDENT * level)
        self._last_was_comment = False

    def ind(self, level):
        return INDENT * level

    def _last_line(self):
        for i in range(len(self.out) - 1, -1, -1):
            chunk = self.out[i]
            nl = chunk.rfind('\n')
            if nl >= 0:
                tail = chunk[nl + 1:]
                for j in range(i + 1, len(self.out)):
                    tail += self.out[j]
                return tail
        return ''.join(self.out)

    def _comment_tabs(self, line):
        col = len(line)
        target = 32
        if col >= target:
            return '\t'
        tab_size = 4
        num_tabs = (target - col + tab_size - 1) // tab_size
        return '\t' * num_tabs

    @staticmethod
    def _line_ends_in_comment(line):
        """True if `line` contains a `--` comment outside string/quoted-identifier literals."""
        quote = None
        i = 0
        while i < len(line):
            ch = line[i]
            if quote:
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
            elif ch == '-' and line[i:i + 2] == '--':
                return True
            i += 1
        return False

    def _semi(self, base=0):
        """Write the statement terminator, never on a line that ends in a `--` comment
        (it would be commented out and the statement would run into the next one)."""
        if self._last_was_comment or self._line_ends_in_comment(self._last_line()):
            self.nl(base)
        self.w(';')

    def _write_comment_lines(self, text, level):
        """One or more own-line comments (joined with COMMENT_SEP) at `level`."""
        for k, line in enumerate(text.split(COMMENT_SEP)):
            if k:
                self.nl(level)
            self.w(line)

    def _emit_list_comment(self, tok, level):
        """A comment token kept between list items: on its own line at `level` when it was
        written on its own line, else trailing the current line."""
        if len(tok) > 2 and tok[2]:
            self.nl(level)
            self.w(tok[1])
            self._last_was_comment = tok[1].lstrip().startswith('--')
        else:
            self._emit_trailing_comment(tok[1])

    def _emit_trailing_comment(self, text):
        last_line = self._last_line()
        self.w(self._comment_tabs(last_line) + text)
        self._last_was_comment = True

    def format_all(self, results):
        # Track whether we need a 3-blank-line separator before the next item.
        # When a CommentGroup has has_trailing_blank=False, it's "attached" to
        # the next statement — no separator between them.
        needs_sep = False
        attached_prev = False
        for item in results:
            if isinstance(item, CommentGroup):
                if needs_sep:
                    self.w('\n' if attached_prev else '\n\n\n\n')
                    needs_sep = False
                attached_prev = False
                for gi, group in enumerate(item.groups):
                    if gi > 0:
                        self.w('\n\n\n\n')
                    self.w('\n'.join(group))
                if item.has_trailing_blank:
                    # Comment block had a trailing blank line — standalone
                    self.w('\n\n\n\n')
                    needs_sep = False  # separator already emitted
                else:
                    # Comment directly precedes the next statement
                    self.w('\n')
                    needs_sep = False  # don't add separator; comment is attached
            else:
                if needs_sep:
                    self.w('\n' if attached_prev else '\n\n\n\n')
                needs_sep = True
                mark = len(self.out)
                src_text = getattr(item, '_src_text', None)
                try:
                    self.format_statement(item)
                    # safety net: formatting may only change whitespace, keyword case,
                    # comments' placement and AS. Anything else (a dropped `...`, an invented
                    # keyword) means the statement wasn't understood: keep it as written.
                    if src_text is not None and not _same_tokens(src_text, ''.join(self.out[mark:])):
                        raise SqlSyntaxError('formatting would change the statement')
                except Exception:
                    if src_text is None:
                        raise
                    del self.out[mark:]
                    self.w(src_text)
                self._rescue_lost_comments(item, mark)
                if getattr(item, 'meta_suffix', ''):
                    self.w(' ' + item.meta_suffix)
                attached_prev = isinstance(item, MetaStatement) and item.attached
        result = ''.join(self.out)
        # Ensure output ends with exactly one newline
        if result and not result.endswith('\n'):
            result += '\n'
        return result

    def _rescue_lost_comments(self, stmt, mark):
        """Safety net: a comment is user content and must never vanish silently.

        If the statement formatter did not render some comment that was in the
        statement's source, put it on its own line above the statement (the
        original position is unknown at that point, but nothing is lost).
        """
        src = getattr(stmt, '_src_comments', None)
        if not src:
            return
        rendered = ''.join(self.out[mark:])
        # count with the real tokenizer: a `--` or `/*` inside a string literal is not a comment
        have = collections.Counter(t[1] for t in tokenize(rendered) if t[0] == 'COMMENT')
        lost = []
        for text in src:
            if have[text] > 0:
                have[text] -= 1
            else:
                lost.append(text)
        if lost:
            self.out.insert(mark, '\n'.join(lost) + '\n')

    def format_statement(self, stmt):
        if isinstance(stmt, SelectStatement):
            self.format_select(stmt, base=0)
        elif isinstance(stmt, UpdateStatement):
            self.format_update(stmt)
        elif isinstance(stmt, DeleteStatement):
            self.format_delete(stmt)
        elif isinstance(stmt, InsertStatement):
            self.format_insert(stmt)
        elif isinstance(stmt, WithStatement):
            self.format_with(stmt)
        elif isinstance(stmt, CreateTableStatement):
            self.format_create_table(stmt)
        elif isinstance(stmt, CreateTableAsStatement):
            self.format_create_table_as(stmt)
        elif isinstance(stmt, CreateIndexStatement):
            self.format_create_index(stmt)
        elif isinstance(stmt, DoBlock):
            self.format_do_block(stmt)
        elif isinstance(stmt, MetaStatement):
            self.w(stmt.text)
        elif isinstance(stmt, UtilityStatement):
            self.format_utility(stmt)
        elif isinstance(stmt, ExplainStatement):
            self.format_explain(stmt)
        elif isinstance(stmt, CreateViewStatement):
            self.format_create_view(stmt)
        elif isinstance(stmt, MergeStatement):
            self.format_merge(stmt)
        elif isinstance(stmt, ValuesStatement):
            self.format_values_statement(stmt)
        elif isinstance(stmt, RawStatement):
            self.w('\n'.join(self._render_token_lines(stmt.tokens)))
            if stmt._has_semicolon:
                self._semi()
        elif isinstance(stmt, VerbatimStatement):
            self.w(stmt.text)
        elif isinstance(stmt, ExpressionFragment):
            # the select-list layout at level 0; the first nl() would add a leading newline
            mark = len(self.out)
            self._format_select_columns(stmt.items, 0)
            if mark < len(self.out) and self.out[mark].startswith('\n'):
                self.out[mark] = self.out[mark][1:]
            for comment in stmt.extra_comments:
                self.nl(0)
                self.w(comment)
            if stmt._has_semicolon:
                self._semi()
