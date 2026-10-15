"""Lexer: raw SQL -> (type, value[, preceded_by_newline]) tokens; join_expr() renders raw token runs."""

from __future__ import annotations
from .constants import FUNCTION_KWS, IDENTIFIER_WORDS, KEYWORDS, _OP_CHARS, _OP_SPECIAL


def _scan_operator(sql, i):
    """End offset of the operator starting at sql[i], following PostgreSQL's lexer:
    the longest run of operator characters, cut before a `--` / `/*` comment start;
    a multi-character operator may only end in `+` or `-` if it also contains one of
    ~ ! @ # % ^ & | ` ?  (so `=-1` is `=` then `-1`, but `@-` stays one operator)."""
    n = len(sql)
    j = i
    while j < n and sql[j] in _OP_CHARS:
        if j > i and sql[j:j + 2] in ('--', '/*'):
            break
        j += 1
    if j - i > 1 and not any(ch in _OP_SPECIAL for ch in sql[i:j]):
        while j - i > 1 and sql[j - 1] in '+-':
            j -= 1
    return j


_ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
_ASCII_UPPER = str.maketrans('abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')


def ascii_lower(s):
    """Lowercase an unquoted identifier the way PostgreSQL folds it: ASCII letters only.
    A name with non-ASCII characters is kept as written (PostgreSQL folds DESCRIÇÃO to
    descriÇÃo; Python's lower() would give descrição, a different identifier, and the
    half-folded form is unreadable)."""
    return s.translate(_ASCII_LOWER) if s.isascii() else s


def ascii_upper(s):
    """Uppercase for display without changing which object an unquoted name refers to
    (non-ASCII names kept as written, see ascii_lower)."""
    return s.translate(_ASCII_UPPER) if s.isascii() else s


def _ident_start(c):
    """PostgreSQL identifier start: a letter, `_`, or any non-ASCII character."""
    return c.isalpha() or c == '_' or ord(c) > 127


def _ident_cont(c, dollar=True):
    """PostgreSQL identifier continuation: also digits and (except in a dollar-quote tag) `$`."""
    return c.isalnum() or c == '_' or ord(c) > 127 or (dollar and c == '$')


def _string_prefix(sql, i):
    """The prefix of a string literal starting at sql[i] ('' for a plain '...'), or None."""
    if sql[i] == "'":
        return ''
    if sql[i] in 'eEbBxXnN' and sql[i + 1:i + 2] == "'":
        return sql[i]
    if sql[i] in 'uU' and sql[i + 1:i + 3] == "&'":
        return sql[i:i + 2]
    return None


def _scan_quoted(sql, i, quote, backslash=False):
    """End offset of the quoted text whose opening `quote` is at sql[i]. A doubled
    quote is an escaped one; with backslash=True (E'...') so is a backslash pair."""
    n = len(sql)
    j = i + 1
    while j < n:
        c = sql[j]
        if backslash and c == '\\':
            j += 2
        elif c == quote and sql[j + 1:j + 2] == quote:
            j += 2
        elif c == quote:
            return j + 1
        else:
            j += 1
    return n


def tokenize(sql, spans=None):
    """Lex `sql` into token tuples. If `spans` is a list, it is filled with the
    (start, end) source offsets of each token (used for verbatim fallback)."""
    tokens = []
    i = 0
    n = len(sql)
    saw_newline = False
    iter_start = 0
    while i < n:
        if spans is not None:
            while len(spans) < len(tokens):
                spans.append((iter_start, i))
            iter_start = i
        if sql[i] in ' \t\n\r':
            # Detect blank lines (2+ newlines) to preserve comment group gaps
            if sql[i] == '\n':
                saw_newline = True
                j = i + 1
                newline_count = 1
                while j < n and sql[j] in ' \t\n\r':
                    if sql[j] == '\n':
                        newline_count += 1
                    j += 1
                if newline_count >= 2:
                    tokens.append(('BLANK_LINE', ''))
                    i = j
                    continue
            i += 1
            continue
        # Capture whether this token is preceded by a newline, then reset.
        # COMMENT tokens store this as a 3rd element to distinguish separator
        # comments (on their own line) from inline trailing comments.
        tok_preceded_by_newline = saw_newline
        saw_newline = False
        if sql[i] == '\\':
            # psql meta-command: the rest of the line is one opaque token, kept
            # verbatim. Mid-line (`SELECT ... \gset`) it is META_INLINE and gets
            # attached to the statement it follows.
            line_start = sql.rfind('\n', 0, i) + 1
            end = sql.find('\n', i)
            if end == -1:
                end = n
            if sql[line_start:i].strip() == '':
                tokens.append(('META', sql[i:end].rstrip(), tok_preceded_by_newline))
                i = end
                continue
            tokens.append(('META_INLINE', sql[i:end].rstrip(), False))
            i = end
            continue
        if sql[i:i+2] == '--':
            end = sql.find('\n', i)
            if end == -1:
                end = n
            tokens.append(('COMMENT', sql[i:end].rstrip(), tok_preceded_by_newline))
            i = end
            continue
        if sql[i:i+2] == '/*':
            # block comments nest in PostgreSQL: /* a /* b */ still a comment */
            depth, end = 1, i + 2
            while end < n and depth:
                if sql[end:end + 2] == '/*':
                    depth, end = depth + 1, end + 2
                elif sql[end:end + 2] == '*/':
                    depth, end = depth - 1, end + 2
                else:
                    end += 1
            tokens.append(('COMMENT', sql[i:end], tok_preceded_by_newline))
            i = end
            continue
        # String literals, with their prefix kept attached: '...', E'...' (backslash escapes),
        # B'0101' / X'1F' (bit strings), N'...' (national), U&'...' (Unicode escapes)
        pre = _string_prefix(sql, i)
        if pre is not None:
            j = _scan_quoted(sql, i + len(pre), "'", backslash=pre.upper() == 'E')
            tokens.append(('STR', sql[i:j]))
            i = j
            continue
        # Quoted identifiers ("a""b" is one identifier), optionally U&"..."
        if sql[i] == '"' or (sql[i] in 'uU' and sql[i + 1:i + 3] == '&"'):
            start = i + (2 if sql[i] != '"' else 0)
            j = _scan_quoted(sql, start, '"')
            tokens.append(('QUOTED_ID', sql[i:j]))
            i = j
            continue
        if sql[i].isdigit() or (sql[i] == '.' and i + 1 < n and sql[i+1].isdigit()
                                and not (i > 0 and (_ident_cont(sql[i-1]) or sql[i-1] in '")'))):
            # (a '.' glued to a preceding name is a qualifier dot, not a decimal point)
            j = i
            if sql[i] == '0' and i + 1 < n and sql[i+1] in 'xXoObB':
                j = i + 2  # 0x1F / 0o17 / 0b101
                while j < n and (sql[j].isalnum() or sql[j] == '_'):
                    j += 1
            else:
                while j < n and (sql[j].isdigit() or sql[j] == '.' or (
                        sql[j] == '_' and j + 1 < n and sql[j+1].isdigit())):
                    j += 1
                # exponent: 1e10, 1.5E-3
                if j < n and sql[j] in 'eE':
                    k = j + 1
                    if k < n and sql[k] in '+-':
                        k += 1
                    if k < n and sql[k].isdigit():
                        while k < n and sql[k].isdigit():
                            k += 1
                        j = k
            if j < n and _ident_start(sql[j]):
                # digit-led word (e.g. an unquoted name like 1433617_backup): keep it whole
                while j < n and _ident_cont(sql[j]):
                    j += 1
                tokens.append(('ID', ascii_lower(sql[i:j])))
            else:
                tokens.append(('NUM', sql[i:j]))
            i = j
            continue
        if _ident_start(sql[i]):
            j = i
            while j < n and _ident_cont(sql[j]):  # has$dollar, naïve·name: one identifier
                j += 1
            word = sql[i:j]
            up = word.upper()
            if up in KEYWORDS and word.lower() not in IDENTIFIER_WORDS:
                tokens.append(('KW', up))
            else:
                tokens.append(('ID', ascii_lower(word)))
            i = j
            continue
        c = sql[i]
        if c == ',':
            tokens.append(('COMMA', ','))
            i += 1
        elif c == ';':
            tokens.append(('SEMI', ';'))
            i += 1
        elif c == '(':
            tokens.append(('LPAR', '('))
            i += 1
        elif c == ')':
            tokens.append(('RPAR', ')'))
            i += 1
        elif c == '.':
            tokens.append(('DOT', '.'))
            i += 1
        elif c == '*':
            # `*` alone (SELECT *, count(*), a * b) is STAR; `*<`, `*<=`, `*=` ... are operators
            j = _scan_operator(sql, i)
            if j - i > 1:
                tokens.append(('OP', sql[i:j]))
                i = j
            else:
                tokens.append(('STAR', '*'))
                i += 1
        elif c == ':' and i + 1 < n and sql[i+1] == ':':
            tokens.append(('OP', '::'))
            i += 2
        elif c == ':' and i + 1 < n and sql[i+1] == '=':
            tokens.append(('OP', ':='))  # named argument f(a := 1) / PL/pgSQL assignment
            i += 2
        elif c in _OP_CHARS:
            j = _scan_operator(sql, i)
            tokens.append(('OP', sql[i:j]))
            i = j
        elif c == ':' and i + 1 < n and (sql[i+1].isalpha() or sql[i+1] == '_'):
            # psql :variable — keep colon fused with identifier
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == '_'):
                j += 1
            tokens.append(('WORD', sql[i:j]))
            i = j
        elif c == ':' and i + 1 < n and sql[i+1] in ("'", '"'):
            # psql :'variable' or :"variable" quoting forms
            quote = sql[i+1]
            j = i + 2
            while j < n and sql[j] != quote:
                j += 1
            tokens.append(('WORD', sql[i:j+1]))
            i = j + 1
        elif c == '$':
            # Dollar-quoting: $$ or $tag$
            j = i + 1
            if j < n and sql[j] == '$':
                delim = '$$'
                body_start = i + 2
            elif j < n and sql[j] == '{' and sql.find('}', j) != -1 and '\n' not in sql[j:sql.find('}', j)]:
                # DBeaver / template placeholder ${name}: one opaque word
                k = sql.find('}', j) + 1
                tokens.append(('WORD', sql[i:k]))
                i = k
                continue
            elif j < n and sql[j].isdigit():
                # Positional parameter ($1, $2, ...) — keep the '$' attached
                k = j
                while k < n and sql[k].isdigit():
                    k += 1
                tokens.append(('WORD', sql[i:k]))
                i = k
                continue
            elif j < n and _ident_start(sql[j]):
                k = j
                while k < n and _ident_cont(sql[k], dollar=False):
                    k += 1
                if k < n and sql[k] == '$':
                    delim = sql[i:k+1]
                    body_start = k + 1
                else:
                    tokens.append(('SYM', '$'))
                    i += 1
                    continue
            else:
                tokens.append(('SYM', '$'))
                i += 1
                continue
            end = sql.find(delim, body_start)
            if end == -1:
                tokens.append(('DOLLAR_BODY', sql[i:n]))
                i = n
            else:
                end += len(delim)
                tokens.append(('DOLLAR_BODY', sql[i:end]))
                i = end
        else:
            tokens.append(('SYM', sql[i]))
            i += 1
    if spans is not None:
        while len(spans) < len(tokens):
            spans.append((iter_start, i))
    return tokens


def join_expr(toks):
    """Join a list of tokens into a properly spaced expression string."""
    if not toks:
        return ''
    parts = [toks[0][1]]
    for i in range(1, len(toks)):
        prev_type = toks[i - 1][0]
        prev_val = toks[i - 1][1]
        cur_type = toks[i][0]
        cur_val = toks[i][1]
        need_space = True
        before = toks[i - 2] if i >= 2 else None
        unary_sign = (prev_val in ('-', '+') and prev_type == 'OP'
                      and (before is None or before[1] in ('(', ',', '[') or before[0] in ('OP', 'COMMA'))
                      and cur_type in ('NUM', 'ID', 'KW', 'WORD', 'QUOTED_ID', 'LPAR'))
        if unary_sign:
            need_space = False
        elif prev_type == 'DOT' or cur_type == 'DOT':
            need_space = False
        elif prev_val == '(':
            need_space = False
        elif cur_val == ')':
            need_space = False
        elif cur_val == '(' and prev_val.upper() in FUNCTION_KWS:
            need_space = False
        elif cur_val == '(' and prev_type in ('ID', 'QUOTED_ID'):
            need_space = False
        elif prev_val == ')' and cur_type == 'DOT':
            need_space = False
        elif prev_val == '::' or cur_val == '::':
            need_space = False
        elif cur_val in ('[', ']'):
            need_space = False
        elif prev_val == '[':
            need_space = False
        elif prev_type == 'SYM' and cur_type == 'SYM':
            need_space = False
        elif cur_type == 'COMMA':
            need_space = False
        # A line comment runs to the end of its line: whatever follows (a token OR
        # another comment) must start a new line or it would be swallowed by it.
        after_line_comment = prev_type == 'COMMENT' and prev_val.lstrip().startswith('--')
        # Tab-align line comments; keep block comments inline with a space
        if cur_type == 'COMMENT':
            if after_line_comment:
                parts.append('\n')
            elif cur_val.lstrip().startswith('--'):
                parts.append('\t')
            else:
                parts.append(' ')
            parts.append(cur_val)
            continue
        if after_line_comment:
            parts.append('\n')
        elif prev_type == 'STR' and cur_type == 'STR':
            # 'a'<newline>'b' is one continued literal; on one line it is a syntax error
            parts.append('\n')
        elif need_space:
            parts.append(' ')
        # Uppercase the type after cast operator (::)
        if prev_val == '::' and cur_type == 'ID':
            parts.append(ascii_upper(cur_val))
        else:
            parts.append(cur_val)
    return ''.join(parts)
