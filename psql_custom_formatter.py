#!/usr/bin/env python3
"""Custom PostgreSQL SQL formatter for DBeaver.

Reads SQL from stdin or a file, formats it, and outputs the result.
File mode formats in-place (for DBeaver temp file integration).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union
import collections
import re
import sys

_COMMENT_RE = re.compile(r'--[^\n]*|/\*.*?\*/', re.S)

INDENT = '    '  # 4 spaces
INLINE_SUBQUERY_MAX_CHARS = 64  # subqueries whose one-line form fits within this length are kept on a single line
INLINE_WHERE_MAX_CHARS = 100  # subquery WHERE/HAVING AND/OR chains longer than this break onto separate lines

KEYWORDS = {
    'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'ON',
    'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL', 'CROSS',
    'ORDER', 'BY', 'GROUP', 'HAVING', 'LIMIT', 'OFFSET',
    'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE',
    'AS', 'IS', 'NULL', 'BETWEEN', 'LIKE', 'ILIKE', 'EXISTS',
    'ANY', 'ARRAY',
    'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
    'UNION', 'EXCEPT', 'INTERSECT', 'ALL', 'DISTINCT', 'ASC', 'DESC',
    'SUM', 'COUNT', 'AVG', 'MIN', 'MAX',
    'COALESCE', 'NULLIF', 'CAST',
    'TRUE', 'FALSE',
    'WITH', 'RECURSIVE',
    'OVER', 'PARTITION',
    'FETCH', 'FIRST', 'NEXT', 'ONLY', 'LAST', 'NULLS',
    'RETURNING', 'CONFLICT', 'DO', 'NOTHING', 'USING',
    'CREATE', 'TABLE', 'IF', 'DROP', 'ALTER',
    'INDEX', 'UNIQUE', 'CONCURRENTLY',
    'LATERAL',
    'ROLLUP', 'CUBE', 'GROUPING', 'SETS', 'FILTER',
    'ROWS', 'RANGE', 'GROUPS', 'PRECEDING', 'FOLLOWING', 'CURRENT', 'UNBOUNDED', 'ROW',
    'WINDOW',
    'FOR', 'DEFAULT',
}

IDENTIFIER_WORDS = {'name', 'value', 'type', 'status', 'id', 'number', 'amount'}

FUNCTION_KWS = {
    'SUM', 'COUNT', 'AVG', 'MIN', 'MAX', 'COALESCE', 'NULLIF', 'CAST',
    'TRIM', 'SUBSTRING', 'EXTRACT', 'ARRAY_AGG', 'STRING_AGG',
    'ROW_NUMBER', 'RANK', 'DENSE_RANK', 'LAG', 'LEAD',
    'FIRST_VALUE', 'LAST_VALUE', 'NTH_VALUE', 'UPPER', 'LOWER',
    'CONCAT', 'LENGTH', 'REPLACE', 'ROUND', 'ABS', 'CEIL', 'FLOOR',
}

JOIN_MODIFIERS = frozenset({'LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS', 'OUTER'})

# Reserved keywords that can never stand in for an identifier/value in expression
# position. If parse_primary sees one of these, the input isn't valid SQL and we'd
# otherwise silently misparse it (e.g. treating a stray WHERE's condition as the
# literal identifier "FROM"). Keywords that are also legitimate function names
# (LEFT, RIGHT, ...) are intentionally excluded.
_NEVER_PRIMARY_KWS = frozenset({
    'SELECT', 'FROM', 'WHERE', 'GROUP', 'HAVING', 'ORDER', 'JOIN', 'ON',
    'INTO', 'VALUES', 'SET', 'RETURNING', 'WITH',
    'UNION', 'EXCEPT', 'INTERSECT',
    'INSERT', 'UPDATE', 'DELETE', 'CREATE',
    'WHEN', 'THEN', 'ELSE', 'END', 'AS',
})


# Statements that start with one of these words are "utility" statements (DDL,
# transaction control, ...) that have no dedicated formatter. They are kept on
# their own lines with keywords uppercased instead of being mangled as SQL.
UTILITY_STARTERS = frozenset({
    'ALTER', 'DROP', 'TRUNCATE', 'COPY', 'GRANT', 'REVOKE', 'COMMENT', 'SET',
    'RESET', 'SHOW', 'VACUUM', 'ANALYZE', 'ANALYSE', 'REINDEX', 'CLUSTER',
    'LOCK', 'BEGIN', 'COMMIT', 'ROLLBACK', 'START', 'END', 'ABORT',
    'SAVEPOINT', 'RELEASE', 'PREPARE', 'EXECUTE', 'DEALLOCATE', 'DISCARD',
    'LISTEN', 'NOTIFY', 'UNLISTEN', 'CALL', 'REFRESH', 'CHECKPOINT',
    'REASSIGN', 'IMPORT', 'LOAD', 'DECLARE', 'MOVE', 'CLOSE', 'SECURITY',
})
# Transaction-control statements are short and often written without a
# terminating semicolon, so a following DML keyword ends them.
_TCL_STARTERS = frozenset({
    'BEGIN', 'COMMIT', 'ROLLBACK', 'START', 'END', 'ABORT', 'SAVEPOINT',
    'RELEASE', 'CHECKPOINT',
})
_STATEMENT_START_KWS = frozenset({
    'SELECT', 'UPDATE', 'DELETE', 'INSERT', 'CREATE', 'WITH',
})
# Words uppercased inside utility statements. Unquoted identifiers fold to
# lower case in PostgreSQL, so uppercasing a word that turns out to be an
# identifier never changes meaning; _UTILITY_NAME_AFTER keeps the common cases
# (a column called `comment`) as written anyway.
UTILITY_KWS = frozenset({
    'ALTER', 'ADD', 'COLUMN', 'DROP', 'CASCADE', 'RESTRICT', 'RENAME', 'TO',
    'TRUNCATE', 'RESTART', 'CONTINUE', 'IDENTITY', 'GRANT', 'REVOKE',
    'PRIVILEGES', 'EXPLAIN', 'ANALYZE', 'ANALYSE', 'VERBOSE', 'VACUUM',
    'FREEZE', 'COPY', 'STDIN', 'STDOUT', 'PROGRAM', 'PUBLIC', 'CURRENT_USER', 'SESSION_USER', 'BEGIN', 'COMMIT',
    'ROLLBACK', 'START', 'TRANSACTION', 'SAVEPOINT', 'RELEASE', 'ABORT',
    'WORK', 'VIEW', 'REPLACE', 'MATERIALIZED', 'TEMP', 'TEMPORARY',
    'UNLOGGED', 'COMMENT', 'CONSTRAINT', 'PRIMARY', 'KEY', 'FOREIGN',
    'REFERENCES', 'CHECK', 'TABLESPACE', 'SCHEMA', 'SEQUENCE', 'EXTENSION',
    'TRIGGER', 'FUNCTION', 'PROCEDURE', 'RETURNS', 'LANGUAGE', 'EXECUTE',
    'DATABASE', 'ROLE', 'OWNER', 'RESET', 'SHOW', 'LOCK', 'MODE', 'NOWAIT',
    'REINDEX', 'CLUSTER', 'REFRESH', 'DATA', 'DISCARD', 'DEALLOCATE',
    'PREPARE', 'LISTEN', 'NOTIFY', 'UNLISTEN', 'CALL', 'ENABLE', 'DISABLE',
    'VALIDATE', 'INHERIT', 'ONLY', 'USAGE', 'TEMPLATE', 'ENCODING',
    'BEFORE', 'AFTER', 'EACH', 'STATEMENT', 'INSTEAD', 'OF', 'REFERENCING',
    'DEFERRABLE', 'INITIALLY', 'DEFERRED', 'IMMEDIATE', 'RETURN', 'SECURITY',
    'DEFINER', 'INVOKER', 'VOLATILE', 'STABLE', 'IMMUTABLE', 'STRICT',
    'COST', 'ROWS', 'PARALLEL', 'SAFE', 'UNSAFE', 'RESTRICTED', 'LOGGED',
    'CASCADED', 'LOCAL', 'GLOBAL', 'INCREMENT', 'MINVALUE', 'MAXVALUE',
    'CACHE', 'CYCLE', 'OWNED', 'INCLUDE', 'CONCURRENTLY', 'WITHOUT', 'WITH',
    'ZONE', 'TIME', 'DELETE', 'UPDATE', 'INSERT', 'SELECT', 'USING', 'ON',
    'AS', 'IF', 'NOT', 'NULL', 'EXISTS', 'DEFAULT', 'UNIQUE', 'INDEX',
    'TABLE', 'CREATE', 'FOR', 'IN', 'IS', 'AND', 'OR', 'SET', 'FROM',
    'WHERE', 'ALL', 'ANY', 'FIRST', 'LAST', 'NEXT', 'ASC', 'DESC', 'NULLS',
    'LIMIT', 'RECURSIVE', 'ROW', 'CURRENT', 'PARTITION', 'INTO', 'VALUES',
    'DO', 'NOTHING', 'ARRAY', 'AUTHORIZATION', 'INHERITS', 'OPTION', 'VALID', 'DEFAULT', 'PRIVILEGES',
    'TABLES', 'SEQUENCES', 'FUNCTIONS', 'TYPES', 'SCHEMAS', 'ROUTINES', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'TRUE',
    'FALSE', 'BY', 'ORDER', 'GROUP', 'HAVING', 'JOIN', 'LEFT', 'RIGHT',
    'INNER', 'OUTER', 'FULL', 'CROSS', 'LIKE', 'ILIKE', 'BETWEEN', 'UNION',
    'EXCEPT', 'INTERSECT', 'DISTINCT', 'FETCH', 'OFFSET', 'GENERATED',
    'ALWAYS', 'STORED', 'IDENTITY', 'MATCH', 'FULL', 'SIMPLE', 'ACTION',
    'NO', 'CHECKPOINT', 'ISOLATION', 'LEVEL', 'READ', 'WRITE', 'COMMITTED',
    'REPEATABLE', 'SERIALIZABLE', 'UNCOMMITTED', 'ONLY', 'DECLARE', 'CURSOR',
    'HOLD', 'SCROLL', 'MOVE', 'CLOSE', 'FORWARD', 'BACKWARD', 'ABSOLUTE',
    'RELATIVE', 'PUBLIC', 'SESSION', 'TRUE', 'FALSE', 'ON',
})
# After one of these the next word is an object name, not a keyword.
_UTILITY_NAME_AFTER = frozenset({
    'COLUMN', 'TABLE', 'INDEX', 'VIEW', 'SCHEMA', 'SEQUENCE', 'FUNCTION',
    'PROCEDURE', 'EXTENSION', 'DATABASE', 'ROLE', 'USER', 'TRIGGER',
    'CONSTRAINT', 'TABLESPACE', 'TYPE', 'DOMAIN', 'COPY', 'INTO', 'FROM',
    'JOIN', 'UPDATE', 'TO', 'ON', 'TRUNCATE', 'ANALYZE', 'VACUUM', 'REINDEX',
    'CLUSTER', 'LOCK', 'REFRESH', 'RENAME', 'OWNER', 'USING', 'REFERENCES',
    'INHERITS',
})
# Words that can sit between a name-taking keyword and the name itself.
_UTILITY_NAME_SKIP = frozenset({
    'IF', 'EXISTS', 'NOT', 'ONLY', 'CONCURRENTLY', 'MATERIALIZED', 'TO',
    'COLUMN', 'TABLE', 'VIEW', 'INDEX', 'SCHEMA', 'DATA', 'RECURSIVE', 'ALL',
    'IN', 'WITH', 'OR', 'REPLACE', 'UNIQUE',
})
# Never an object name even right after a name-taking keyword (COPY t FROM stdin).
_UTILITY_NEVER_NAME = frozenset({
    'STDIN', 'STDOUT', 'PROGRAM', 'CURRENT_USER', 'SESSION_USER',
    'CURRENT_ROLE', 'PUBLIC', 'TABLES', 'SEQUENCES', 'FUNCTIONS', 'TYPES',
    'SCHEMAS', 'ROUTINES', 'LARGE', 'OBJECTS',
})
_UTILITY_TYPE_WORDS = frozenset({
    'int', 'integer', 'bigint', 'smallint', 'text', 'varchar', 'char',
    'numeric', 'decimal', 'boolean', 'bool', 'date', 'time', 'timestamp',
    'timestamptz', 'timetz', 'interval', 'uuid', 'json', 'jsonb', 'serial',
    'bigserial', 'smallserial', 'real', 'float', 'double', 'precision',
    'bytea', 'inet', 'cidr', 'money', 'character', 'varying', 'bit', 'xml',
    'oid', 'regclass', 'citext', 'int2', 'int4', 'int8', 'float4', 'float8',
})


class SqlSyntaxError(Exception):
    """Raised when the token stream can't be a valid SQL statement.

    Caught by format_sql(), which returns the original input unchanged rather
    than emit a mangled best-effort parse.
    """

SELECT_CLAUSE_KWS = frozenset({
    'FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING',
    'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT',
})


def tokenize(sql):
    tokens = []
    i = 0
    n = len(sql)
    saw_newline = False
    while i < n:
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
            end = sql.find('*/', i)
            end = n if end == -1 else end + 2
            tokens.append(('COMMENT', sql[i:end], tok_preceded_by_newline))
            i = end
            continue
        # E'...' escaped string literals (keep E prefix attached)
        if sql[i] in ('E', 'e') and i + 1 < n and sql[i+1] == "'":
            j = i + 2
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j+1] == "'":
                    j += 2
                elif sql[j] == "'":
                    break
                else:
                    j += 1
            tokens.append(('STR', sql[i:j+1]))
            i = j + 1
            continue
        if sql[i] == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j+1] == "'":
                    j += 2
                elif sql[j] == "'":
                    break
                else:
                    j += 1
            tokens.append(('STR', sql[i:j+1]))
            i = j + 1
            continue
        if sql[i] == '"':
            j = i + 1
            while j < n and sql[j] != '"':
                j += 1
            tokens.append(('QUOTED_ID', sql[i:j+1]))
            i = j + 1
            continue
        if sql[i].isdigit() or (sql[i] == '.' and i + 1 < n and sql[i+1].isdigit()
                                and not (i > 0 and (sql[i-1].isalnum() or sql[i-1] in '_")'))):
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
            if j < n and (sql[j].isalpha() or sql[j] == '_'):
                # digit-led word (e.g. an unquoted name like 1433617_backup): keep it whole
                while j < n and (sql[j].isalnum() or sql[j] == '_'):
                    j += 1
                tokens.append(('ID', sql[i:j].lower()))
            else:
                tokens.append(('NUM', sql[i:j]))
            i = j
            continue
        if sql[i].isalpha() or sql[i] == '_':
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == '_'):
                j += 1
            word = sql[i:j]
            up = word.upper()
            if up in KEYWORDS and word.lower() not in IDENTIFIER_WORDS:
                tokens.append(('KW', up))
            else:
                tokens.append(('ID', word.lower()))
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
            tokens.append(('STAR', '*'))
            i += 1
        elif i + 3 < n and sql[i:i+4] == '!~~*':
            tokens.append(('OP', sql[i:i+4]))
            i += 4
        elif i + 2 < n and sql[i:i+3] in ('->>', '#>>', '!~*', '~~*', '!~~'):
            tokens.append(('OP', sql[i:i+3]))
            i += 3
        elif i + 1 < n and sql[i:i+2] in (
            '<=', '>=', '<>', '!=', '::', '->', '#>', '||', '~*', '!~',
            '@>', '<@', '?|', '?&', '&&', '<<', '>>', '@@', '@?', '#-', '~~',
        ):
            tokens.append(('OP', sql[i:i+2]))
            i += 2
        elif c in '~^&|?@#':
            tokens.append(('OP', c))
            i += 1
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
        elif c in '<>=+-/%':
            tokens.append(('OP', c))
            i += 1
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
            elif j < n and (sql[j].isalpha() or sql[j] == '_'):
                k = j
                while k < n and (sql[k].isalnum() or sql[k] == '_'):
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
        elif need_space:
            parts.append(' ')
        # Uppercase the type after cast operator (::)
        if prev_val == '::' and cur_type == 'ID':
            parts.append(cur_val.upper())
        else:
            parts.append(cur_val)
    return ''.join(parts)


# ─── AST NODES ──────────────────────────────────────────────────────────────

@dataclass
class Comment:
    text: str
    is_block: bool
    is_trailing: bool

@dataclass
class Literal:
    kind: str   # 'string', 'number', 'bool', 'null', 'dollar', 'psql_var', 'star'
    value: str

@dataclass
class Identifier:
    parts: List[str]
    alias: Optional[str] = None
    alias_quoted: bool = False

@dataclass
class BinaryOp:
    op: str
    left: Expression
    right: Expression
    leading_comments: list = field(default_factory=list)  # standalone comments before the operator
    left_trailing_comment: Optional[str] = None  # inline comment trailing the left operand

@dataclass
class UnaryOp:
    op: str
    expr: Expression

@dataclass
class IsNullOp:
    expr: Expression
    negated: bool

@dataclass
class OrderItem:
    expr: Expression
    direction: Optional[str] = None
    nulls: Optional[str] = None
    using: Optional[str] = None  # ORDER BY x USING <

@dataclass
class WindowSpec:
    partition_by: List[Expression]
    order_by: List[OrderItem]
    frame: Optional[str] = None
    base_name: Optional[str] = None  # OVER (w ORDER BY ...): refines window `w`

@dataclass
class FunctionCall:
    name: str
    schema: Optional[str]
    args: List[Expression]
    distinct: bool = False
    star_arg: bool = False
    order_by: List[OrderItem] = field(default_factory=list)
    filter_clause: Optional[Expression] = None
    over_clause: Optional[WindowSpec] = None
    # Keyword-style argument lists (TRIM(BOTH x FROM y), POSITION(a IN b), ...):
    # a sequence of ('kw', WORD) / ('expr', node) items rendered in order.
    special: Optional[list] = None

@dataclass
class CaseExpr:
    operand: Optional[Expression]
    branches: List[Tuple[Expression, Expression]]
    else_expr: Optional[Expression] = None

@dataclass
class CastExpr:
    expr: Expression
    type_str: str

@dataclass
class TypeCastOp:
    expr: Expression
    type_str: str

@dataclass
class InExpr:
    expr: Expression
    negated: bool
    values: List[Expression]
    subquery: Optional[SelectStatement] = None
    lead_comments: list = field(default_factory=list)   # per value: standalone comments above it
    trail_comments: list = field(default_factory=list)  # per value: inline comment after it
    end_comments: list = field(default_factory=list)    # comments just before the closing paren

@dataclass
class BetweenExpr:
    expr: Expression
    negated: bool
    low: Expression
    high: Expression
    mode: str = ''  # '' | 'SYMMETRIC' | 'ASYMMETRIC'

@dataclass
class PostfixOp:
    """expr ISNULL / expr NOTNULL"""
    expr: Expression
    op: str

@dataclass
class FieldExpr:
    """Field selection from a composite value: (a).b, (a).*, a.b[1].c"""
    base: Expression
    field: str

@dataclass
class ValuesExpr:
    """VALUES (..), (..) used as a subquery body inside ANY/ALL/IN."""
    rows: list  # raw token lists, one per row

@dataclass
class ExistsExpr:
    subquery: SelectStatement
    negated: bool = False

@dataclass
class SubqueryExpr:
    query: SelectStatement

@dataclass
class Parenthesized:
    expr: Expression
    close_comments: list = field(default_factory=list)  # comments just before the closing paren

@dataclass
class ArrayExpr:
    elements: List[Expression]

@dataclass
class RowExpr:
    """Parenthesized row constructor with 2+ items, e.g. (a, b) or (1, 2)."""
    items: List[Expression]

@dataclass
class SubscriptExpr:
    """Array subscript / slice: base[i], base[lo:hi], base[:hi], base[lo:].

    parts holds one expression (or None for an omitted bound) per side of the
    colon; is_slice says whether a colon was present.
    """
    base: Expression
    parts: list
    is_slice: bool

@dataclass
class AnyAllExpr:
    quantifier: str
    array: Expression

@dataclass
class RawTokens:
    tokens: list

Expression = Union[
    Literal, Identifier, BinaryOp, UnaryOp, IsNullOp,
    FunctionCall, CaseExpr, CastExpr, TypeCastOp,
    InExpr, BetweenExpr, ExistsExpr, SubqueryExpr,
    Parenthesized, ArrayExpr, AnyAllExpr, RawTokens, RowExpr, SubscriptExpr,
    PostfixOp, FieldExpr, ValuesExpr,
]

@dataclass
class SelectItem:
    expr: Expression
    alias: Optional[str] = None
    alias_quoted: bool = False
    trailing_comment: Optional[str] = None  # raw comment text
    leading_comment: Optional[str] = None   # standalone comment before this item

@dataclass
class ValuesClause:
    rows: List[List[Expression]]
    alias: str = ''
    alias_quoted: bool = False
    columns: List[str] = field(default_factory=list)

@dataclass
class TableRef:
    name: str = ''
    schema: Optional[str] = None
    alias: Optional[str] = None
    alias_quoted: bool = False
    subquery: Optional[SelectStatement] = None
    values: Optional[ValuesClause] = None
    func_call: Optional['FunctionCall'] = None
    with_ordinality: bool = False
    alias_columns: list = field(default_factory=list)  # t AS x(a, b): raw tokens, comma separated
    is_lateral: bool = False
    trailing_comment: Optional[str] = None
    leading_comments: List[str] = field(default_factory=list)  # standalone comments above this table (FROM a\n-- c\n, b)

@dataclass
class JoinClause:
    join_type: str
    table: TableRef
    on_condition: Optional[Expression] = None
    using_columns: Optional[List[str]] = None
    on_trailing_comment: Optional[str] = None  # inline comment after the ON condition
    on_leading_comments: List[str] = field(default_factory=list)  # standalone comments between ON and its condition
    leading_comments: List[str] = field(default_factory=list)  # standalone comments above the JOIN keyword
    pre_on_comments: List[str] = field(default_factory=list)  # standalone comments between the joined table and ON/USING

@dataclass
class FromClause:
    tables: List[TableRef]
    joins: List[JoinClause]
    leading_comments: List[str] = field(default_factory=list)  # standalone comments before the first table

@dataclass
class CteClause:
    name: str
    columns: List[str]
    body: SelectStatement
    leading_comments: List[str] = field(default_factory=list)
    materialized: Optional[str] = None  # 'MATERIALIZED' | 'NOT MATERIALIZED'

@dataclass
class UnionPart:
    union_type: str
    query: SelectStatement

@dataclass
class SetClause:
    target: str
    value: Expression
    trailing_comment: Optional[str] = None
    leading_comment: Optional[str] = None  # standalone comment before this item

@dataclass
class ConflictClause:
    raw_tokens: list  # conflict target (and, as a fallback, everything else) as raw tokens
    action: Optional[str] = None  # 'NOTHING' | 'UPDATE' when the DO clause was parsed structurally
    set_clauses: list = field(default_factory=list)
    where: Optional[Expression] = None
    where_trailing_comment: Optional[str] = None

@dataclass
class SelectStatement:
    distinct: bool = False
    distinct_on: List[Expression] = field(default_factory=list)
    columns: List[SelectItem] = field(default_factory=list)
    from_clause: Optional[FromClause] = None
    where: Optional[Expression] = None
    group_by: List[Expression] = field(default_factory=list)
    having: Optional[Expression] = None
    order_by: List[OrderItem] = field(default_factory=list)
    limit: Optional[RawTokens] = None
    offset: Optional[RawTokens] = None
    fetch_clause: Optional[RawTokens] = None
    for_clause: Optional[str] = None
    window_defs: list = field(default_factory=list)  # [(name, WindowSpec)]
    into: Optional[list] = None  # SELECT ... INTO [TEMP] [TABLE] name: raw tokens after INTO
    unions: List[UnionPart] = field(default_factory=list)
    trailing_comments: List[str] = field(default_factory=list)
    select_list_trailing_comments: List[str] = field(default_factory=list)
    # comments between FROM and the WHERE keyword itself (render before WHERE)
    pre_where_comments: List[str] = field(default_factory=list)
    # comments between WHERE and its first condition (render after WHERE)
    where_leading_comments: List[str] = field(default_factory=list)
    where_trailing_comment: Optional[str] = None
    group_by_leading_comments: List[str] = field(default_factory=list)
    # comments between WHERE/GROUP BY and the HAVING keyword itself
    pre_having_comments: List[str] = field(default_factory=list)
    # comments between HAVING and its first condition (render after HAVING)
    having_leading_comments: List[str] = field(default_factory=list)
    having_trailing_comment: Optional[str] = None
    order_by_leading_comments: List[str] = field(default_factory=list)
    _has_semicolon: bool = False

@dataclass
class InsertStatement:
    table: str
    schema: Optional[str] = None
    columns: List[str] = field(default_factory=list)
    values_rows: Optional[List[List[Expression]]] = None
    select: Optional[SelectStatement] = None
    on_conflict: Optional[ConflictClause] = None
    returning: List[SelectItem] = field(default_factory=list)
    _has_semicolon: bool = False

@dataclass
class UpdateStatement:
    table: str
    schema: Optional[str] = None
    alias: Optional[str] = None
    set_clauses: List[SetClause] = field(default_factory=list)
    from_clause: Optional[FromClause] = None
    where: Optional[Expression] = None
    # comments between FROM (or SET) and the WHERE keyword itself
    pre_where_comments: List[str] = field(default_factory=list)
    # comments between WHERE and its first condition
    where_leading_comments: List[str] = field(default_factory=list)
    where_trailing_comment: Optional[str] = None
    returning: List[SelectItem] = field(default_factory=list)
    _has_semicolon: bool = False

@dataclass
class DeleteStatement:
    table: str
    schema: Optional[str] = None
    alias: Optional[str] = None
    using_tables: List[TableRef] = field(default_factory=list)
    where: Optional[Expression] = None
    where_raw: Optional[RawTokens] = None  # WHERE CURRENT OF cursor (not an expression)
    pre_where_comments: List[str] = field(default_factory=list)
    where_leading_comments: List[str] = field(default_factory=list)
    where_trailing_comment: Optional[str] = None
    returning: List[SelectItem] = field(default_factory=list)
    _has_semicolon: bool = False

@dataclass
class WithStatement:
    recursive: bool
    ctes: List[CteClause]
    main_statement: Statement
    _has_semicolon: bool = False
    main_leading_comments: List[str] = field(default_factory=list)

@dataclass
class CreateTableAsStatement:
    table_name: str
    schema: Optional[str] = None
    if_not_exists: bool = False
    prefix: str = ''  # TEMP / UNLOGGED / ... between CREATE and TABLE
    with_clause: Optional[WithStatement] = None
    select: Optional[SelectStatement] = None
    raw_fallback: Optional[list] = None
    body_raw: Optional[list] = None  # AS TABLE x / AS VALUES ... (not a SELECT)
    _has_semicolon: bool = False

@dataclass
class ColumnDef:
    name: str
    type_str: str            # e.g. 'BIGINT', 'VARCHAR(200)', 'TIMESTAMP WITH TIME ZONE'
    constraint_tokens: list  # raw token tuples for column constraints (NOT NULL, DEFAULT ...)
    trailing_comment: Optional['Comment'] = None
    leading_comments: list = field(default_factory=list)  # standalone comments above this column

@dataclass
class CreateTableStatement:
    table_name: str
    schema: Optional[str] = None
    if_not_exists: bool = False
    columns: list = field(default_factory=list)            # List[ColumnDef]
    table_constraints: list = field(default_factory=list)  # List[list] of raw token lists
    constraint_leading: list = field(default_factory=list)  # parallel to table_constraints: comment lists
    constraint_trailing: list = field(default_factory=list)  # parallel: trailing comment text or None
    tail: list = field(default_factory=list)  # tokens after the closing paren (PARTITION BY, WITH (...), ...)
    prefix: str = ''  # TEMP / UNLOGGED / ... between CREATE and TABLE
    _has_semicolon: bool = False

@dataclass
class CreateIndexStatement:
    unique: bool
    raw_rest: list
    _has_semicolon: bool = False

@dataclass
class DoBlock:
    dollar_body: str
    _has_semicolon: bool = False
    language_before: Optional[str] = None  # DO LANGUAGE plpgsql $$ ... $$
    language_after: Optional[str] = None   # DO $$ ... $$ LANGUAGE plpgsql

@dataclass
class RawStatement:
    tokens: list
    _has_semicolon: bool = False

@dataclass
class MetaStatement:
    """psql meta-command line (\\echo, \\set, ...), kept verbatim."""
    text: str
    attached: bool = False  # no blank line follows -> stays tight with the next line

@dataclass
class UtilityStatement:
    """DDL / transaction-control / other statement without a dedicated formatter."""
    kind: str
    tokens: list
    _has_semicolon: bool = False

@dataclass
class ExplainStatement:
    options: list          # raw tokens between EXPLAIN and the statement
    statement: object
    _has_semicolon: bool = False

@dataclass
class CreateViewStatement:
    prefix: str            # e.g. 'OR REPLACE', 'OR REPLACE TEMP', 'MATERIALIZED'
    name: str
    columns: list          # raw tokens of the optional column list (without parens)
    options: list          # raw tokens of an optional WITH (...) storage clause
    body: object           # SelectStatement | WithStatement
    suffix: list           # raw tokens after the body (WITH [NO] DATA, WITH CHECK OPTION)
    if_not_exists: bool = False
    _has_semicolon: bool = False

@dataclass
class MergeWhen:
    matched: str           # 'MATCHED' | 'NOT MATCHED' | 'NOT MATCHED BY SOURCE' | 'NOT MATCHED BY TARGET'
    condition: Optional[object]
    action: str            # 'UPDATE' | 'DELETE' | 'INSERT' | 'DO NOTHING'
    set_clauses: list = field(default_factory=list)
    insert_columns: list = field(default_factory=list)   # raw tokens
    insert_values: list = field(default_factory=list)    # raw tokens, or [] for DEFAULT VALUES
    insert_default_values: bool = False
    leading_comments: list = field(default_factory=list)

@dataclass
class MergeStatement:
    target: object         # TableRef
    source: object         # TableRef
    on_condition: object
    whens: list
    returning: list = field(default_factory=list)
    _has_semicolon: bool = False

Statement = Union[
    SelectStatement, InsertStatement, UpdateStatement, DeleteStatement,
    WithStatement, CreateTableAsStatement, CreateTableStatement,
    CreateIndexStatement, DoBlock, RawStatement, MetaStatement, UtilityStatement,
    ExplainStatement, CreateViewStatement, MergeStatement,
]

@dataclass
class CommentGroup:
    groups: List[List[str]]
    has_trailing_blank: bool


# ─── PARSER ──────────────────────────────────────────────────────────────────

_NOT_ALIAS_KWS = frozenset({
    'FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'UNION',
    'EXCEPT', 'INTERSECT', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'FULL',
    'CROSS', 'OUTER', 'ON', 'AND', 'OR', 'NOT', 'DISTINCT', 'SELECT',
    'INTO', 'VALUES', 'SET', 'USING', 'RETURNING', 'OFFSET', 'FETCH',
    'FOR', 'LATERAL', ';',
})

_CLAUSE_KWS = frozenset({
    'FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'UNION',
    'EXCEPT', 'INTERSECT', 'WINDOW', ';',
})

_JOIN_START_KWS = frozenset({'JOIN', 'LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS', 'OUTER'})

_INFIX_PREC = {
    'OR': 10, 'AND': 20,
    '=': 45, '<': 45, '>': 45, '<=': 45, '>=': 45, '<>': 45, '!=': 45,
    '~': 45, '~*': 45, '!~': 45, '!~*': 45, '~~': 45, '~~*': 45, '!~~': 45, '!~~*': 45,
    '@>': 45, '<@': 45, '?': 45, '?|': 45, '?&': 45, '&&': 45, '@@': 45, '@?': 45,
    '<<': 45, '>>': 45,
    'LIKE': 40, 'ILIKE': 40,
    '+': 55, '-': 55, '||': 55,
    '->': 58, '->>': 58, '#>': 58, '#>>': 58, '#-': 58,
    '*': 60, '/': 60, '%': 60, '^': 60, '&': 60, '|': 60,
    '::': 80,
}

class Parser:
    def __init__(self, tokens):
        self.tok = tokens
        self.pos = 0

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

    def _is_join(self, off=0):
        t = self.pk(off)
        if t[1] == 'JOIN':
            return True
        if t[1] in JOIN_MODIFIERS:
            j = off + 1
            while self.pk(j)[1] in JOIN_MODIFIERS:
                j += 1
            return self.pk(j)[1] == 'JOIN'
        return False

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
            stmt = self.parse_statement()
            if isinstance(stmt, (UpdateStatement, DeleteStatement, InsertStatement)):
                # these parsers skip trailing comments (dropping them): give back the ones
                # after a blank line so they lead the next statement. (Raw/utility statements
                # keep comment tokens in their own token list, so they must NOT do this.)
                self._give_back_comments_after_blank()
            results.append(stmt)
            try:
                setattr(stmt, '_src_comments',
                        [t[1] for t in self.tok[start_pos:self.pos] if t[0] == 'COMMENT'])
            except AttributeError:
                pass
            while self.pk()[0] == 'META_INLINE':
                tail = self.eat()[1]
                target = stmt
                setattr(target, 'meta_suffix', (getattr(target, 'meta_suffix', '') + ' ' + tail).strip())

        return results

    def parse_statement(self):
        self.skip_blanks()
        t = self.pk()
        if t[1] == 'SELECT':
            return self.parse_select()
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
            return self.parse_raw_statement()

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

    def _parse_query(self):
        """A parenthesized query body: SELECT ... or WITH ... SELECT ..."""
        if self.pk()[1] == 'WITH':
            return self.parse_with()
        return self.parse_select(stop_at_rpar=True)

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
        if nxt[1] in (';', 'LIMIT', 'OFFSET', 'FETCH', 'FOR', 'UNION', 'EXCEPT', 'INTERSECT',
                      'RETURNING', ')') or (nxt[1] == 'ON' and self.pk(1)[1] == 'CONFLICT'):
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

    def parse_select(self, stop_at_rpar=False):
        stmt = SelectStatement()
        self.eat()  # SELECT
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
            toks = self.collect_raw(lambda t: t[1] in (';', 'OFFSET', 'FETCH', 'FOR') or t[0] == 'EOF')
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
        # UNION/EXCEPT/INTERSECT
        self._comments_before(stmt, ('UNION', 'EXCEPT', 'INTERSECT'))
        while self.pk()[1] in ('UNION', 'EXCEPT', 'INTERSECT'):
            op = self.eat()[1]
            self.skip_blanks()
            if self.pk()[1] == 'ALL':
                self.eat()
                op = op + ' ALL'
            self.skip_blanks()
            sub = self.parse_select(stop_at_rpar=stop_at_rpar)
            stmt.unions.append(UnionPart(op, sub))
        return stmt

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
            if t[0] == 'EOF' or t[1] in (';', ')', 'UNION', 'EXCEPT', 'INTERSECT'):
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
                parts.append(word.upper())
        out = ' '.join(parts)
        return out.replace(' , ', ', ').replace(' .', '.').replace('. ', '.')

    def _where_stop(self, t):
        if t[1] in ('GROUP', 'ORDER', 'HAVING', 'WINDOW', 'LIMIT', 'OFFSET', 'FETCH',
                     'FOR', 'UNION', 'EXCEPT', 'INTERSECT', 'RETURNING', ';'):
            return True
        if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
            return True
        return t[0] == 'EOF'

    def _group_stop(self, t):
        if t[1] in ('HAVING', 'WINDOW', 'ORDER', 'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT',
                     ';', 'WHERE', 'FROM', 'SELECT', 'RETURNING', 'CREATE'):
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
            if t[1] == 'INTO':
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
                pending_leading_comment = self.eat()[1]
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
                                 and self.pk(j + 1)[1].lower() in ('no', 'data', 'check', 'local', 'cascaded')))
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
        # alias
        if self.pk()[1] == 'AS':
            self.eat()
            if self.pk()[0] == 'QUOTED_ID':
                item.alias = self.eat()[1].strip('"')
                item.alias_quoted = True
            elif self.pk()[0] in ('ID', 'KW'):
                item.alias = self.eat()[1]
        elif (self.pk()[0] in ('ID', 'QUOTED_ID') and
              self.pk()[1] not in _NOT_ALIAS_KWS and
              self.pk()[1] not in _CLAUSE_KWS):
            if self.pk()[0] == 'QUOTED_ID':
                item.alias = self.eat()[1].strip('"')
                item.alias_quoted = True
            else:
                item.alias = self.eat()[1]
        # trailing comment after alias
        if not item.trailing_comment and self.pk()[0] == 'COMMENT' and not self.pk()[2]:
            item.trailing_comment = self.eat()[1]
        return item

    def _at_view_suffix(self):
        """At `WITH NO DATA` / `WITH [LOCAL|CASCADED] CHECK OPTION` after a view body."""
        return (self.pk()[1] == 'WITH' and self.pk(1)[0] in ('ID', 'KW')
                and self.pk(1)[1].lower() in ('no', 'data', 'check', 'local', 'cascaded'))

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
                    left = BinaryOp('NOT ' + op, left, right)
                    continue
                elif self._at_similar_to(j):
                    self.eat(); self.eat(); self.eat()
                    self.skip_blanks()
                    right = self.parse_expression(stop_fn=stop_fn, min_prec=41)
                    left = BinaryOp('NOT SIMILAR TO', left, right)
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
                left = BinaryOp(op, left, right)
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
                left = BinaryOp('SIMILAR TO', left, right)
                continue
            # Array subscript / slice: expr[i], expr[lo:hi]
            if t[0] == 'SYM' and t[1] == '[':
                left = self._parse_subscript(left)
                continue
            # ANY / ALL as postfix (= ANY(...)) — handled in infix section below
            # Infix operator
            prec = None
            if t[0] == 'OP' and t[1] in _INFIX_PREC:
                prec = _INFIX_PREC[t[1]]
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
                elif self.pk()[1] in ('SELECT', 'WITH'):
                    inner = SubqueryExpr(self._parse_query())
                elif self.pk()[1] == 'VALUES':
                    inner = self._parse_values_expr()
                else:
                    inner = self.parse_expression(stop_fn=lambda t: t[1] == ')')
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

    def _parse_subscript(self, base):
        """Parse [i], [lo:hi], [:hi], [lo:] after `base` (current token is '[')."""
        self.eat()  # [
        parts = []
        is_slice = False
        stop = lambda t: t[1] in (':', ']') or t[0] == 'EOF'
        while True:
            self.skip_blanks()
            if self.pk()[1] in (':', ']') or self.pk()[0] == 'EOF':
                parts.append(None)
            else:
                parts.append(self.parse_expression(stop_fn=stop))
            self.skip_blanks()
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
        return ' '.join(parts).upper()

    def _parse_in_rhs(self, left, negated, stop_fn):
        if self.pk()[1] != '(':
            # bare IN without parens — treat as raw
            return InExpr(left, negated, [])
        self.eat()  # (
        self.skip_blanks()
        if self.pk()[1] in ('SELECT', 'WITH'):
            sub = self._parse_query()
            self.skip_blanks()
            self._close_paren()
            return InExpr(left, negated, [], sub)
        if self.pk()[1] == 'VALUES':
            values_expr = self._parse_values_expr()
            self.skip_blanks()
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
            if self.pk()[1] in ('SELECT', 'WITH'):
                inner = SubqueryExpr(self._parse_query())
            elif self.pk()[1] == 'VALUES':
                inner = self._parse_values_expr()
            else:
                inner = self.parse_expression(stop_fn=lambda t: t[1] == ')')
            self.skip_blanks()
            self._close_paren()
            return AnyAllExpr(quant, inner)
        if t[0] == 'STR':
            return Literal('string', self.eat()[1])
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
                if self.pk()[1] == '(':
                    return self.parse_function_call(name, schema)
                return Identifier([schema + '.' + name])
            return Identifier([schema])
        if t[1] == '(':
            # subquery?
            j = 1
            while self.pk(j)[0] == 'BLANK_LINE':
                j += 1
            if self.pk(j)[1] in ('SELECT', 'WITH'):
                self.eat()  # (
                sub = self._parse_query()
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
        if t[0] == 'KW' and t[1] in _NEVER_PRIMARY_KWS:
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
            # function call
            if self.pk()[1] == '(':
                return self.parse_function_call(name, schema)
            # PostgreSQL type-literal: identifier followed by string literal
            # e.g. interval '90 days', timestamp '2024-01-01', date '...', etc.
            if (self.pk()[0] == 'STR' and schema is None and
                    name.lower() in ('interval', 'timestamp', 'date', 'time', 'timestamptz',
                                     'timetz', 'varchar', 'char', 'numeric', 'decimal',
                                     'money', 'inet', 'cidr', 'macaddr', 'uuid', 'json',
                                     'jsonb', 'xml', 'bytea', 'bit', 'varbit', 'boolean',
                                     'int', 'integer', 'bigint', 'smallint', 'float',
                                     'real', 'double')):
                str_val = self.eat()[1]
                return RawTokens([('ID', name), ('STR', str_val)])
            return Identifier([schema + '.' + name] if schema else [name])
        # Fallback: collect as raw tokens
        toks = [self.eat()]
        return RawTokens(toks)

    def _skip_comments(self):
        """Skip comments/blank lines between the parts of a construct (the safety net keeps them)."""
        while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
            self.eat()

    def parse_case(self):
        self.eat()  # CASE
        self.skip_blanks()
        operand = None
        if self.pk()[1] not in ('WHEN', 'END'):
            operand = self.parse_expression(stop_fn=lambda t: t[1] in ('WHEN', 'END'))
        branches = []
        self._skip_comments()
        while self.pk()[1] == 'WHEN':
            self.eat()  # WHEN
            when_expr = self.parse_expression(stop_fn=lambda t: t[1] == 'THEN')
            self._skip_comments()
            if self.pk()[1] == 'THEN':
                self.eat()
            then_expr = self.parse_expression(stop_fn=lambda t: t[1] in ('WHEN', 'ELSE', 'END'))
            branches.append((when_expr, then_expr))
            self._skip_comments()
        else_expr = None
        if self.pk()[1] == 'ELSE':
            self.eat()
            else_expr = self.parse_expression(stop_fn=lambda t: t[1] == 'END')
            self._skip_comments()
        if self.pk()[1] == 'END':
            self.eat()
        return CaseExpr(operand, branches, else_expr)

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
        if self.pk()[1] == '*' or self.pk()[0] == 'STAR':
            star_arg = True
            self.eat()
        elif self.pk()[1] != ')':
            # Check if single SELECT arg (subquery as function argument, e.g. ARRAY(SELECT ...))
            if self.pk()[1] == 'SELECT':
                sub = self._parse_query()
                sq = SubqueryExpr(sub)
                sq.in_call_parens = True  # f(SELECT ...): the call's own parens enclose the query
                args.append(sq)
            else:
                # parse args
                while not self.done() and self.pk()[1] != ')':
                    self.skip_blanks()
                    if self.pk()[1] == ')':
                        break
                    if self.pk()[1] == ',':
                        self.eat()
                        continue
                    if self.pk()[1] == 'ORDER' and self.pk(1)[1] == 'BY':
                        self.eat(); self.eat()
                        order_by = self.parse_order_by_list_until_rpar()
                        break
                    # Keyword-style argument lists: EXTRACT(f FROM x), SUBSTRING(s FROM a FOR b),
                    # TRIM(BOTH c FROM s), POSITION(a IN b), OVERLAY(s PLACING r FROM a FOR b)
                    if name.upper() in self._SPECIAL_ARG_FUNCS and not args and special is None:
                        special = self._parse_special_args()
                        break
                    arg = self.parse_expression(stop_fn=lambda t: t[1] in (',', ')') or
                                                 (t[1] == 'ORDER' and self.pk(1)[1] == 'BY'))
                    args.append(arg)
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
                over_clause = WindowSpec([], [], wname)
        return FunctionCall(name.upper(), schema, args, distinct, star_arg, order_by, filter_clause, over_clause,
                            special)

    _SPECIAL_ARG_FUNCS = frozenset({'EXTRACT', 'SUBSTRING', 'TRIM', 'POSITION', 'OVERLAY'})
    _SPECIAL_ARG_WORDS = frozenset({
        'FROM', 'FOR', 'IN', 'PLACING', 'BOTH', 'LEADING', 'TRAILING', 'SIMILAR', 'ESCAPE',
    })

    def _parse_special_args(self):
        """Arguments of EXTRACT/SUBSTRING/TRIM/POSITION/OVERLAY as ('kw', W) / ('expr', node) items."""
        items = []
        words = self._SPECIAL_ARG_WORDS
        while not self.done() and self.pk()[1] != ')':
            self.skip_blanks()
            t = self.pk()
            if t[1] == ')':
                break
            if t[0] == 'COMMA':
                self.eat()
                items.append(('comma', ','))
                continue
            if t[0] in ('ID', 'KW') and t[1].upper() in words and (
                    not items or items[-1][0] != 'kw' or t[1].upper() in ('FROM',)):
                items.append(('kw', self.eat()[1].upper()))
                continue
            items.append(('expr', self.parse_expression(
                stop_fn=lambda t: t[1] == ')' or t[0] == 'COMMA'
                or (t[0] in ('ID', 'KW') and t[1].upper() in words))))
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
            while not self.done() and self.pk()[1] not in ('ORDER', 'ROWS', 'RANGE', 'GROUPS', ')'):
                self.skip_blanks()
                if self.pk()[1] in ('ORDER', 'ROWS', 'RANGE', 'GROUPS', ')'):
                    break
                if self.pk()[1] == ',':
                    self.eat()
                    continue
                e = self.parse_expression(stop_fn=lambda t: t[1] in (',', 'ORDER', 'ROWS', 'RANGE', 'GROUPS', ')'))
                partition_by.append(e)
        if self.pk()[1] == 'ORDER' and self.pk(1)[1] == 'BY':
            self.eat(); self.eat()
            order_by = self.parse_order_by_list_until_rpar()
        if self.pk()[1] in ('ROWS', 'RANGE', 'GROUPS'):
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
            if t[1] in ('HAVING', 'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT', ';',
                         'WHERE', 'RETURNING', 'FETCH', 'OFFSET', 'FOR') or t[0] == 'EOF':
                break
            if t[0] == 'COMMENT':
                break  # leave in stream for parse_select to collect
            if t[1] == ',':
                self.eat()
                continue
            if t[1] == ')':
                break
            expr = self.parse_expression(stop_fn=lambda t: t[1] in (',', 'ASC', 'DESC', 'NULLS', 'USING', 'WINDOW',
                                                                       'HAVING', 'LIMIT', 'UNION',
                                                                       'EXCEPT', 'INTERSECT', ';',
                                                                       'RETURNING', 'FETCH', 'OFFSET')
                                          or t[0] == 'EOF')
            direction = None
            nulls = None
            using = None
            if self.pk()[1] in ('ASC', 'DESC'):
                direction = self.eat()[1]
            elif self.pk()[1] == 'USING' and self.pk(1)[0] == 'OP':
                self.eat()
                using = self.eat()[1]
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
        if nt[1] in _CLAUSE_KWS or nt[1] in ('LIMIT', 'OFFSET', 'FETCH', 'FOR', 'RETURNING', 'WINDOW', 'ON',
                                               'ASC', 'DESC', 'NULLS', 'USING', 'ROWS', 'RANGE', 'GROUPS'):
            return False
        return nt[0] in ('KW', 'ID', 'META', 'META_INLINE') and nt[1].upper() in (
            _STATEMENT_START_KWS | frozenset({'DROP', 'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE', 'COPY', 'SET', 'BEGIN',
                                              'COMMIT', 'ROLLBACK', 'EXPLAIN', 'MERGE', 'VACUUM', 'ANALYZE'})
        ) or nt[0] in ('META', 'META_INLINE')

    def parse_order_by_list_until_rpar(self):
        items = []
        # ROWS/RANGE/GROUPS mark the start of a window frame spec — stop there
        _stop = (',', 'ASC', 'DESC', 'NULLS', 'USING', ')', 'ROWS', 'RANGE', 'GROUPS')
        while not self.done() and self.pk()[1] not in (')', 'ROWS', 'RANGE', 'GROUPS'):
            self.skip_blanks()
            if self.pk()[1] in (')', 'ROWS', 'RANGE', 'GROUPS'):
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
            if self.pk()[1] == 'NULLS':
                self.eat()
                if self.pk()[1] in ('FIRST', 'LAST'):
                    nulls = self.eat()[1]
            items.append(OrderItem(expr, direction, nulls, using))
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
        if self.pk()[1] == '(':
            # subquery or VALUES
            j = 1
            while self.pk(j)[0] == 'BLANK_LINE':
                j += 1
            if self.pk(j)[1] in ('SELECT', 'WITH'):
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
        self.skip_blanks()
        if (self.pk()[1] == 'WITH' and self.pk(1)[0] in ('ID', 'KW')
                and self.pk(1)[1].lower() == 'ordinality'):
            self.eat(); self.eat()
            ref.with_ordinality = True
        # alias
        self.skip_blanks()
        if self.pk()[1] == 'AS':
            self.eat()
            if self.pk()[0] == 'QUOTED_ID':
                ref.alias = self.eat()[1].strip('"')
                ref.alias_quoted = True
            elif self.pk()[0] in ('ID', 'KW'):
                ref.alias = self.eat()[1]
        elif (self.pk()[0] in ('ID', 'QUOTED_ID') and
              self.pk()[1] not in _NOT_ALIAS_KWS and
              not self._is_join() and
              self.pk()[1] not in (',', ')', ';')):
            if self.pk()[0] == 'QUOTED_ID':
                ref.alias = self.eat()[1].strip('"')
                ref.alias_quoted = True
            else:
                ref.alias = self.eat()[1]
        # alias column list: x(a, b)
        if ref.alias and self.pk()[1] == '(':
            self.eat()
            ref.alias_columns = self.collect_raw(lambda t: t[1] == ')')
            self._close_paren()
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
        while not self.done():
            self.skip_blanks()
            if self.pk()[1] == ',':
                self.eat()
                self.skip_blanks()
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
        vc = ValuesClause(rows=[])
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
        return JoinClause(join_type, table, on_cond, using_cols, on_trailing_comment, on_leading_comments,
                          pre_on_comments=pre_on_comments)

    def _join_on_stop(self, t):
        if t[1] in ('WHERE', 'GROUP', 'ORDER', 'HAVING', 'WINDOW', 'LIMIT', 'SELECT', 'FROM', ';'):
            return True
        if t[0] == 'EOF':
            return True
        if self._is_join():
            return True
        return False

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
            stmt.where = self.parse_expression(stop_fn=self._where_stop)
            if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                stmt.where_trailing_comment = self.eat()[1]
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

    def parse_set_clauses(self, extra_stops=()):
        clauses = []
        pending_leading_comment = None
        stoppers = ('WHERE', 'FROM', 'RETURNING', ';', 'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                    'CREATE', 'WITH') + tuple(extra_stops)
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
                pending_leading_comment = self.eat()[1]
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
            val = self.parse_expression(stop_fn=lambda t: t[1] in (',', 'WHERE', 'FROM', 'RETURNING', ';') or t[1] in extra_stops or t[0] == 'EOF')
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
        # column list
        if self.pk()[1] == '(':
            self.eat()
            while not self.done() and self.pk()[1] != ')':
                self.skip_blanks()
                if self.pk()[1] == ')':
                    break
                if self.pk()[1] == ',':
                    self.eat()
                    continue
                stmt.columns.append(self.eat()[1])
            self._close_paren()
        self.skip_blanks()
        if self.pk()[1] == 'SELECT':
            stmt.select = self.parse_select()
        elif self.pk()[1] == 'VALUES':
            self.eat()
            rows = []
            while not self.done():
                self.skip_blanks()
                if self.pk()[1] != '(':
                    break
                self.eat()  # (
                row_toks = self.collect_raw(lambda t: t[1] == ')')
                self._close_paren()
                rows.append(row_toks)
                self.skip_blanks()
                if self.pk()[1] == ',':
                    self.eat()
                else:
                    break
            stmt.values_rows = rows  # list of raw token lists
        # ON CONFLICT
        self.skip_blanks()
        if self.pk()[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
            self.eat(); self.eat()
            stmt.on_conflict = self.parse_on_conflict()
        self.skip_blanks()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

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
        self.skip_blanks()
        if self.pk()[1] == 'USING':
            self.eat()
            self.skip_blanks()
            stmt.using_tables.append(self.parse_table_ref())
            while self.pk()[1] == ',':
                self.eat()
                stmt.using_tables.append(self.parse_table_ref())
        pending_comments = self._collect_comments()
        if self.pk()[1] == 'WHERE':
            stmt.pre_where_comments = pending_comments
            pending_comments = []
            self.eat()
            stmt.where_leading_comments = self._collect_comments()
            if self.pk()[1] == 'CURRENT' and self.pk(1)[1].lower() == 'of':
                toks = self.collect_raw(lambda t: t[1] in (';', 'RETURNING') or t[0] == 'EOF')
                if len(toks) > 1 and toks[1][0] == 'ID' and toks[1][1].lower() == 'of':
                    toks[1] = ('KW', 'OF')
                stmt.where_raw = RawTokens(toks)
            else:
                stmt.where = self.parse_expression(stop_fn=self._where_stop)
                if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                    stmt.where_trailing_comment = self.eat()[1]
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

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
            if self.pk()[1] in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', ';') or self.pk()[0] == 'EOF':
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
                self.skip_blanks_and_comments()
                if self.pk()[1] in ('INSERT', 'UPDATE', 'DELETE', 'WITH'):
                    # data-modifying CTE: WITH x AS (INSERT/UPDATE/DELETE ... RETURNING ...)
                    body = self.parse_statement()
                elif self.pk()[1] in ('VALUES', 'TABLE'):
                    # VALUES (..), (..) / TABLE t as a CTE body: keep as written (it is not a SELECT)
                    body = RawStatement(self.collect_raw(lambda t: t[1] == ')'))
                else:
                    body = self._parse_query()
                self.skip_blanks()
                self._close_paren()
            else:
                body = SelectStatement()
            stmt.ctes.append(CteClause(name=cte_name, columns=columns, body=body,
                                       leading_comments=pending_comments, materialized=materialized))
            self.skip_blanks()
            if self.pk()[1] == ',':
                self.eat()
            if self.pos == loop_start:
                # nothing consumed: not a well-formed CTE list; fail instead of looping forever
                raise SqlSyntaxError("Malformed WITH clause")
        self.skip_blanks()
        if self.pk()[1] in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
            stmt.main_statement = self.parse_statement()
            stmt._has_semicolon = getattr(stmt.main_statement, '_has_semicolon', False)
        elif self.pk()[1] == ';':
            # `WITH x AS (...);` with no main query (not valid SQL, but the `;` must survive)
            self.eat()
            stmt._has_semicolon = True
        return stmt

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
        if self.pk()[0] == 'DOT':
            self.eat()
            stmt.schema = stmt.table_name
            stmt.table_name = self.eat()[1] if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID') else stmt.table_name
        # Check for CREATE TABLE (col defs) vs CREATE TABLE ... AS SELECT
        self.skip_blanks()
        if self.pk()[1] == '(':
            return self.parse_create_table_columns(
                stmt.table_name, stmt.schema, stmt.if_not_exists, prefix)
        if (not self.done() and self.pk()[1] not in ('AS', ';', 'SELECT') and
                self.pk()[0] not in ('EOF', 'BLANK_LINE')):
            toks = []
            while not self.done():
                t = self.pk()
                if t[0] == 'BLANK_LINE':
                    self.eat()
                    continue
                if t[1] == ';':
                    toks.append(self.eat())
                    break
                if t[1] in ('SELECT', 'UPDATE', 'DELETE', 'INSERT', 'CREATE', 'WITH'):
                    break
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
        while not self.done():
            t = self.pk()
            if t[0] == 'BLANK_LINE':
                self.eat()
                continue
            if t[1] == ';' or t[0] in ('META', 'META_INLINE', 'COMMENT'):
                break
            if t[1] in ('SELECT', 'UPDATE', 'DELETE', 'INSERT', 'CREATE'):
                break
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
                upcased.append((t[0], t[1].upper()) + t[2:])
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
                    and t[0] in ('KW', 'ID') and t[1].upper() in _STATEMENT_START_KWS):
                break
            if t[1] in ('(', '['):
                depth += 1
            elif t[1] in (')', ']'):
                depth = max(0, depth - 1)
            stmt.tokens.append(self.eat())
        return stmt

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
            while not self.done() and self.pk()[1] != ';':
                if self.pk()[0] == 'BLANK_LINE':
                    self.eat()
                    continue
                stmt.suffix.append(self.eat())
            if self.pk()[1] == ';':
                self.eat()
                stmt._has_semicolon = True
        elif self.pk()[1] == ';':
            self.eat()
            stmt._has_semicolon = True
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
        on_cond = None
        if self.pk()[1] == 'ON':
            self.eat()
            on_cond = self.parse_expression(stop_fn=lambda t: t[1] in ('WHEN', 'RETURNING', ';') or t[0] == 'EOF')
        stmt = MergeStatement(target=target, source=source, on_condition=on_cond, whens=[])
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
                    self.eat()
                    w.insert_columns = self.collect_raw(lambda t: t[1] == ')')
                    self._close_paren()
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
                        self.eat()
                        w.insert_values = self.collect_raw(lambda t: t[1] == ')')
                        self._close_paren()
            else:
                raise SqlSyntaxError("Unrecognised MERGE action")
            stmt.whens.append(w)
        if not stmt.whens:
            raise SqlSyntaxError("MERGE without WHEN clause")
        self.skip_blanks()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
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
            if not toks and t[1] in ('SELECT', 'UPDATE', 'DELETE', 'INSERT', 'CREATE', 'WITH'):
                break
            if toks and t[1] in ('SELECT', 'UPDATE', 'DELETE', 'INSERT', 'CREATE', 'WITH'):
                break
            toks.append(self.eat())
        return RawStatement(toks)


# ─── AST FORMATTER ────────────────────────────────────────────────────────────

class ASTFormatter:
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
        sub = ASTFormatter()
        sub.format_statement(query)
        text = ''.join(sub.out).rstrip(';')
        self.w('\n'.join((INDENT * base + ln) if ln.strip() else ln for ln in text.split('\n')))

    def _inline_subquery(self, query, max_chars=INLINE_SUBQUERY_MAX_CHARS):
        """Return one-line rendering of subquery if it fits within max_chars (incl. parens), else None."""
        if not isinstance(query, SelectStatement):
            return None
        scratch = ASTFormatter()
        scratch.format_select(query, base=0, is_subquery=True)
        rendered = ''.join(scratch.out)
        one_line = ''
        for line in rendered.splitlines():
            line = line.strip()
            if not line:
                continue
            one_line += (line if line.startswith(',') or not one_line else ' ' + line)
        full = '(' + one_line + ')'
        return full if len(full) <= max_chars else None

    def _fits_inline(self, expr, ci, max_chars=INLINE_WHERE_MAX_CHARS):
        """Whether expr's one-line rendering (at indent level ci) fits within max_chars."""
        scratch = ASTFormatter()
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
                self.format_statement(item)
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
        elif isinstance(stmt, RawStatement):
            self.w('\n'.join(self._render_token_lines(stmt.tokens)))
            if stmt._has_semicolon:
                self._semi()

    def format_select(self, stmt, base=0, is_subquery=False):
        self.w(self.ind(base) + 'SELECT')
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
        first = True
        for item in stmt.columns:
            if first:
                self.nl(ci)
                first = False
                if item.leading_comment:
                    self.w(item.leading_comment)
                    self.nl(ci)
                self.format_select_item(item, ci)
            else:
                if item.leading_comment:
                    self.nl(ci)
                    self.w(item.leading_comment)
                self.nl(ci)
                self.w(', ')
                self.format_select_item(item, ci)
            continue
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
        if stmt._has_semicolon:
            if stmt.trailing_comments or self._last_was_comment:
                self.nl(base)
            self._semi()
        for u in stmt.unions:
            self.w('\n')
            self.w(self.ind(base) + u.union_type)
            self.w('\n')
            self.format_select(u.query, base, is_subquery=is_subquery)

    def format_select_item(self, item, ci):
        self.format_expression(item.expr, ci, inline=True)
        if item.alias:
            self.w(' AS ')
            if item.alias_quoted:
                self.w('"' + item.alias + '"')
            else:
                self.w(item.alias)
        if item.trailing_comment:
            self._emit_trailing_comment(item.trailing_comment)

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
                if isinstance(expr.expr, UnaryOp) and expr.expr.op in ('-', '+'):
                    self.w(' ')
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
            self.w('::' + expr.type_str.upper())
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
            self.w('ARRAY[')
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
            elif isinstance(inner, SubqueryExpr):
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
        self.w('CASE')
        if expr.operand is not None:
            self.w(' ')
            self.format_expression(expr.operand, ci, inline=True)
        for (when_e, then_e) in expr.branches:
            self.nl(ci + 1)
            self.w('WHEN ')
            self.format_expression(when_e, ci + 1, inline=True)
            self.w(' THEN ')
            self.format_expression(then_e, ci + 1, inline=True)
        if expr.else_expr is not None:
            self.nl(ci + 1)
            self.w('ELSE ')
            self.format_expression(expr.else_expr, ci + 1, inline=True)
        self.nl(ci + 1)
        self.w('END')

    def format_function_call(self, call, ci):
        name = call.name
        if call.schema:
            name = call.schema + '.' + name
        self.w(name + '(')
        if call.distinct:
            self.w('DISTINCT ')
        if call.special is not None:
            prev = None
            for kind, val in call.special:
                if kind == 'comma':
                    self.w(',')
                elif kind == 'kw':
                    self.w(('' if prev is None else ' ') + val)
                else:
                    self.w('' if prev is None else ' ')
                    self.format_expression(val, ci, inline=True)
                prev = kind
        elif call.star_arg:
            self.w('*')
        else:
            for i, arg in enumerate(call.args):
                if i > 0:
                    self.w(', ')
                # SubqueryExpr inside a function call: the function parens serve
                # as the outer parens, so format the SELECT directly (no extra parens)
                if isinstance(arg, SubqueryExpr) and getattr(arg, 'in_call_parens', False):
                    self.w('\n')
                    self._format_subquery_body(arg.query, ci + 1)
                    self.nl(ci)
                else:
                    self.format_expression(arg, ci, inline=True)
        if call.order_by:
            self.w(' ORDER BY ')
            self._format_order_items(call.order_by, ci)
        self.w(')')
        if call.filter_clause:
            self.w(' FILTER (WHERE ')
            self.format_expression(call.filter_clause, ci, inline=True)
            self.w(')')
        if call.over_clause:
            ws = call.over_clause
            # named window reference
            if isinstance(ws.frame, str) and not ws.partition_by and not ws.order_by:
                self.w(' OVER ' + ws.frame)
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

    def format_from_clause(self, clause, base):
        ci = base + 1
        for comment in clause.leading_comments:
            self.nl(ci)
            self.w(comment)
        self.nl(ci)
        if clause.tables:
            self.format_table_ref(clause.tables[0], ci)
        for table in clause.tables[1:]:
            for comment in table.leading_comments:
                self.nl(ci)
                self.w(comment)
            self.nl(ci)
            self.w(', ')
            self.format_table_ref(table, ci)
        for join in clause.joins:
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
            self.format_function_call(ref.func_call, ci)
        else:
            name = ref.name
            if ref.schema:
                name = ref.schema + '.' + name
            self.w(name)
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
        if ref.trailing_comment:
            self._emit_trailing_comment(ref.trailing_comment)

    def format_values_table_ref(self, vc, ci):
        self.w('(\n')
        self.w(self.ind(ci) + 'VALUES')
        raw_rows = getattr(vc, '_raw_rows', [])
        first = True
        for row_toks in raw_rows:
            self.nl(ci + 1)
            row_str = '(' + join_expr(row_toks) + ')'
            if first:
                self.w(row_str)
                first = False
            else:
                self.w(', ' + row_str)
        self.w('\n' + self.ind(ci) + ')')
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
        if join.pre_on_comments:
            # comments between the joined table and ON/USING: own lines, with the
            # keyword dropped back to the JOIN's column so it still reads as part of this join
            for comment in join.pre_on_comments:
                self.nl(ci + 1)
                self.w(comment)
            self.nl(ci)
        if join.on_condition is not None:
            # ON condition always goes on next line (double-indented)
            self.w('ON' if join.pre_on_comments else ' ON')
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
            self.w(('' if join.pre_on_comments else ' ') + 'USING (' + ', '.join(join.using_columns) + ')')

    def _has_top_level_and_or(self, expr):
        return isinstance(expr, BinaryOp) and expr.op in ('AND', 'OR')

    def format_update(self, stmt):
        self.w('UPDATE')
        self.nl(1)
        name = stmt.table
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(name)
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
        if stmt.where is not None:
            for comment in stmt.pre_where_comments:
                self.nl(0)
                self.w(comment)
            self.nl(0)
            self.w('WHERE')
            for comment in stmt.where_leading_comments:
                self.nl(1)
                self.w(comment)
            self.nl(1)
            self.format_where_expr(stmt.where, 1, inline_and=False,
                                    final_trailing_comment=stmt.where_trailing_comment)
        if stmt.returning:
            self.nl(0)
            self.w('RETURNING')
            self._format_returning(stmt.returning, 1)
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
                    self.w(sc.leading_comment)
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
        if stmt.columns:
            self.w(' (')
            self._format_raw_column_list(stmt.columns, 1)
            self.nl(0)
            self.w(')')
        if stmt.values_rows is not None:
            self.nl(0)
            self.w('VALUES')
            for i, row_toks in enumerate(stmt.values_rows):
                self.w(' (')
                self.w(join_expr(row_toks))
                self.w(')')
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
            self._format_returning(stmt.returning, 1)
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

    def _format_returning(self, items, ci):
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
        self.w(name)
        if stmt.alias:
            self.w(' ' + stmt.alias)
        if stmt.using_tables:
            self.nl(0)
            self.w('USING')
            first = True
            for t in stmt.using_tables:
                if first:
                    self.nl(1)
                    first = False
                else:
                    self.nl(1)
                    self.w(', ')
                self.format_table_ref(t, 1)
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
            self._format_returning(stmt.returning, 1)
        if stmt._has_semicolon:
            self._semi()

    def format_with(self, stmt):
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
            if isinstance(cte.body, SelectStatement):
                self.format_select(cte.body, 1)
            else:
                # INSERT/UPDATE/DELETE (or nested WITH) body: render at column 0, then indent
                sub = ASTFormatter()
                sub.format_statement(cte.body)
                text = ''.join(sub.out).rstrip(';')
                self.w('\n'.join((INDENT + ln) if ln.strip() else ln for ln in text.split('\n')))
            self.w('\n)')
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

    # Keywords to uppercase inside column constraints and table constraints
    _CONSTRAINT_KWS = frozenset({
        'NULL', 'NOT', 'DEFAULT', 'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES',
        'UNIQUE', 'CHECK', 'CONSTRAINT', 'ON', 'DELETE', 'UPDATE', 'CASCADE',
        'RESTRICT', 'NO', 'ACTION', 'GENERATED', 'ALWAYS', 'IDENTITY',
        'STORED', 'WITH', 'TIME', 'ZONE', 'WITHOUT', 'ONLY', 'MATCH',
        'PARTIAL', 'SIMPLE', 'FULL', 'DEFERRED', 'IMMEDIATE', 'DEFERRABLE',
        'INITIALLY', 'USING', 'INDEX', 'WHERE', 'COLLATE', 'NULLS',
        'FIRST', 'LAST', 'ASC', 'DESC', 'LIKE', 'INCLUDING', 'EXCLUDING',
        'ALL', 'DEFAULTS', 'COMMENTS', 'INDEXES', 'STORAGE', 'STATISTICS',
        'CONSTRAINTS', 'IDENTITY', 'GENERATED', 'COMPRESSION',
    })

    def _format_constraint_tokens(self, toks):
        """Render constraint tokens with SQL keywords uppercased.

        Constraint keywords are emitted as KW type so join_expr never
        suppresses the space before '(' — which it would for ID tokens
        (to handle function calls). This gives 'PRIMARY KEY (id)' and
        'CHECK (expr)' instead of 'PRIMARY KEY(id)'.
        """
        result = []
        for t in toks:
            if t[0] == 'KW':
                result.append(t)
            elif t[0] == 'ID' and t[1].upper() in self._CONSTRAINT_KWS:
                result.append(('KW', t[1].upper()) + t[2:])
            else:
                result.append(t)
        return join_expr(result)

    def format_create_table(self, stmt):
        self.w('CREATE ' + (stmt.prefix + ' ' if stmt.prefix else '') + 'TABLE')
        if stmt.if_not_exists:
            self.w(' IF NOT EXISTS')
        self.nl(1)
        name = stmt.table_name
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(name)

        # Column name padding: align type names to a consistent column
        pad_to = max((len(col.name) for col in stmt.columns), default=0) + 1

        constraint_leading = stmt.constraint_leading or [[] for _ in stmt.table_constraints]
        constraint_trailing = stmt.constraint_trailing or [None for _ in stmt.table_constraints]
        all_items = (
            [(True, col, col.leading_comments, col.trailing_comment.text if col.trailing_comment else None)
             for col in stmt.columns] +
            [(False, tc, constraint_leading[k], constraint_trailing[k])
             for k, tc in enumerate(stmt.table_constraints)]
        )
        # a synthetic empty slot only carries comments that sat right before ')'
        real_idx = [k for k, it in enumerate(all_items) if it[0] or it[1]]
        last_real = real_idx[-1] if real_idx else -1
        self.w('\n(')
        for i, (is_col, item, leading, trailing) in enumerate(all_items):
            for c in leading:
                self.w('\n' + INDENT + c)
            if not is_col and not item:
                continue
            self.w('\n' + INDENT)
            if is_col:
                self.w(item.name.ljust(pad_to))
                self.w(item.type_str)
                if item.constraint_tokens:
                    self.w(' ' + self._format_constraint_tokens(item.constraint_tokens))
            else:
                self.w(self._format_constraint_tokens(item))
            if i != last_real:
                self.w(',')
            if trailing:
                last_line = self._last_line()
                self.w(self._comment_tabs(last_line) + trailing)
        self.w('\n)')
        if stmt.tail:
            toks = self._utility_prepare(stmt.tail)
            self.w(' ' + ' '.join(self._render_token_lines(toks)))
        if stmt._has_semicolon:
            self._semi()

    def format_create_table_as(self, stmt):
        self.w('CREATE ' + (stmt.prefix + ' ' if stmt.prefix else '') + 'TABLE')
        if stmt.if_not_exists:
            self.w(' IF NOT EXISTS')
        self.nl(1)
        name = stmt.table_name
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(name)
        if stmt.raw_fallback is not None:
            self.w(join_expr(stmt.raw_fallback))
            return
        self.w(' AS')
        if stmt.with_clause:
            self.w('\n')
            self.format_with(stmt.with_clause)
        elif stmt.select:
            self.w('\n')
            self.format_select(stmt.select, 1)
        elif stmt.body_raw:
            self.nl(1)
            self._write_lines(self._render_token_lines(self._utility_prepare(stmt.body_raw)), 1)
        if stmt._has_semicolon and not (stmt.select and stmt.select._has_semicolon):
            self._semi()

    # ── Utility / EXPLAIN / CREATE VIEW / MERGE ───────────────────

    @staticmethod
    def _utility_prepare(toks):
        """Uppercase keywords / types and mark object names, for utility statements."""
        out = []
        name_next = False
        paren_stack = []
        n = len(toks)
        for idx, t in enumerate(toks):
            typ, val = t[0], t[1]
            nxt = toks[idx + 1] if idx + 1 < n else ('EOF', '')
            prev = out[-1] if out else ('', '')
            new = t
            consumed_name = False
            if typ in ('ID', 'KW'):
                up = val.upper()
                if prev[0] == 'DOT' or nxt[0] == 'DOT':
                    new = ('NAME', val) + t[2:]
                elif (typ == 'ID' and name_next and up not in _UTILITY_NAME_SKIP
                        and up not in _UTILITY_NEVER_NAME
                        and not (prev[1] == 'TYPE' and val in _UTILITY_TYPE_WORDS)):
                    new = ('NAME', val) + t[2:]
                    consumed_name = True
                elif (typ == 'ID' and prev[0] in ('LPAR', 'COMMA') and nxt[0] in ('COMMA', 'RPAR')
                        and up not in ('TRUE', 'FALSE', 'NULL', 'DEFAULT', 'VERBOSE', 'ANALYZE',
                                       'ANALYSE', 'FREEZE', 'FULL')):
                    new = ('NAME', val) + t[2:]  # bare list element: (key, data)
                elif (typ == 'ID' and up == 'TYPE' and nxt[0] not in ('COMMA', 'RPAR', 'EOF')
                        and nxt[1] != '=' and (prev[0] == 'NAME' or prev[1] == 'DATA')):
                    new = ('KW', 'TYPE') + t[2:]  # ALTER COLUMN c TYPE ... / SET DATA TYPE
                elif typ == 'ID' and up in UTILITY_KWS:
                    new = ('KW', up) + t[2:]
                elif typ == 'ID' and val in _UTILITY_TYPE_WORDS:
                    new = ('KW', up) + t[2:]
                if typ == 'ID' and name_next and prev[1] in ('FUNCTION', 'PROCEDURE') and nxt[1] == '(':
                    new = t  # CREATE FUNCTION f(...): a call-shaped name, keep tight
                # decide whether the *next* word is an object name
                if consumed_name:
                    name_next = False
                elif up in _UTILITY_NAME_AFTER and new[0] == 'KW':
                    name_next = True
                elif not (name_next and up in _UTILITY_NAME_SKIP):
                    name_next = False
            else:
                name_next = False if typ not in ('COMMENT',) else name_next
            out.append(new)
        return out

    def _render_token_lines(self, toks, prepare=False):
        """Join tokens into output lines without ever letting a `--` comment
        swallow code: a line comment ends its line, standalone comments get their own."""
        if prepare:
            toks = self._utility_prepare(toks)
        lines = []
        seg = []

        def flush(comment=None, own_line=False):
            nonlocal seg
            text = join_expr(seg) if seg else ''
            if comment is not None:
                if own_line:
                    if text:
                        lines.append(text)
                    lines.append(comment)
                else:
                    lines.append((text + self._comment_gap(text) if text else '') + comment)
            elif text:
                lines.append(text)
            seg = []

        for t in toks:
            if t[0] == 'BLANK_LINE':
                continue
            if t[0] == 'COMMENT':
                if t[1].lstrip().startswith('--'):
                    flush(t[1], own_line=bool(len(t) > 2 and t[2]) or not seg)
                else:
                    seg.append(t)
                continue
            seg.append(t)
        flush()
        return lines

    def _comment_gap(self, text):
        return self._comment_tabs(text) if hasattr(self, '_comment_tabs') else '\t'

    def _write_lines(self, lines, base=0):
        for i, ln in enumerate(lines):
            if i > 0:
                self.nl(base)
            self.w(ln)

    def _end_statement(self, lines_end_in_comment, has_semicolon, base=0):
        if has_semicolon:
            if lines_end_in_comment:
                self.nl(base)
            self._semi()

    def format_utility(self, stmt):
        toks = self._utility_prepare(stmt.tokens)
        lines = None
        if stmt.kind == 'ALTER' and len(toks) > 2 and toks[1][1].upper() == 'TABLE':
            lines = self._alter_table_lines(toks)
        if lines is None:
            lines = self._render_token_lines(toks)
        self._write_lines(lines)
        self._end_statement(bool(lines) and '--' in lines[-1] and self._ends_with_line_comment(stmt.tokens),
                            stmt._has_semicolon)

    @staticmethod
    def _ends_with_line_comment(toks):
        for t in reversed(toks):
            if t[0] == 'BLANK_LINE':
                continue
            return t[0] == 'COMMENT' and t[1].lstrip().startswith('--')
        return False

    _ALTER_ACTION_STARTERS = frozenset({
        'ADD', 'DROP', 'ALTER', 'RENAME', 'SET', 'RESET', 'OWNER', 'ENABLE',
        'DISABLE', 'VALIDATE', 'INHERIT', 'NO', 'CLUSTER', 'ATTACH', 'DETACH',
        'REPLICA', 'FORCE', 'OF', 'NOT', 'SET',
    })

    def _alter_table_lines(self, toks):
        """ALTER TABLE name <action>[, <action>...]: one action per line when there are several."""
        i = 2
        # IF EXISTS / ONLY
        while i < len(toks) and toks[i][1].upper() in ('IF', 'EXISTS', 'ONLY'):
            i += 1
        # table name (possibly schema.name, optionally followed by '*')
        while i < len(toks) and (toks[i][0] in ('NAME', 'ID', 'QUOTED_ID', 'DOT', 'STAR')):
            i += 1
        head, rest = toks[:i], toks[i:]
        actions = []
        cur = []
        depth = 0
        skip = 0
        for idx, t in enumerate(rest):
            if skip:
                skip -= 1
                continue
            if t[1] in ('(', '['):
                depth += 1
            elif t[1] in (')', ']'):
                depth -= 1
            if depth == 0 and t[0] == 'COMMA':
                nxt = rest[idx + 1] if idx + 1 < len(rest) else None
                if nxt is not None and nxt[0] == 'COMMENT' and not (len(nxt) > 2 and nxt[2]):
                    cur.append(nxt)  # `, -- note` trails the action before the comma
                    skip = 1
                actions.append(cur)
                cur = []
                continue
            cur.append(t)
        if cur:
            actions.append(cur)
        if len(actions) < 2:
            return None
        out = self._render_token_lines(head)
        for k, act in enumerate(actions):
            # standalone comments in front of an action go on their own lines above it
            lead = 0
            while lead < len(act) and act[lead][0] == 'COMMENT' and len(act[lead]) > 2 and act[lead][2]:
                out.append(INDENT + act[lead][1])
                lead += 1
            sub = self._render_token_lines(act[lead:])
            for j, ln in enumerate(sub):
                if j == 0:
                    out.append(INDENT + (', ' if k > 0 else '') + ln)
                else:
                    out.append(INDENT + ('  ' if k > 0 else '') + ln)
        return out

    def format_explain(self, stmt):
        self.w('EXPLAIN')
        if stmt.options:
            opts = []
            for t in stmt.options:
                if t[0] in ('ID', 'KW'):
                    opts.append(('KW', t[1].upper()) + t[2:])
                else:
                    opts.append(t)
            self.w(' ' + join_expr(opts))
        inner = stmt.statement
        if isinstance(inner, RawStatement) and not inner.tokens:
            if stmt._has_semicolon:
                self._semi()
            return
        self.nl(0)
        self.format_statement(inner)
        if stmt._has_semicolon and not getattr(inner, '_has_semicolon', False):
            self._semi()

    def format_create_view(self, stmt):
        head = 'CREATE ' + (stmt.prefix + ' ' if stmt.prefix else '') + 'VIEW'
        if stmt.if_not_exists:
            head += ' IF NOT EXISTS'
        self.w(head)
        self.nl(1)
        self.w(stmt.name)
        if stmt.columns:
            self.w(' (' + join_expr(stmt.columns) + ')')
        if stmt.options:
            opts = self._utility_prepare(stmt.options)
            self.w(' ' + join_expr(opts))
        self.w(' AS')
        self.w('\n')
        body = stmt.body
        if isinstance(body, WithStatement):
            self.format_with(body)
        else:
            self.format_select(body, 1)
        inner_semi = getattr(body, '_has_semicolon', False)
        if stmt.suffix:
            self.nl(0)
            self.w(join_expr(self._utility_prepare(stmt.suffix)))
        if stmt._has_semicolon and not (inner_semi and not stmt.suffix):
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
            self._format_returning(stmt.returning, 1)
        if stmt._has_semicolon:
            self._semi()

    def format_create_index(self, stmt):
        toks = list(stmt.raw_rest)
        semi = bool(toks) and toks[-1][1] == ';'
        if semi:
            toks.pop()
        lines = self._render_token_lines(self._utility_prepare(toks))
        self._write_lines(lines)
        self._end_statement(self._ends_with_line_comment(toks), semi)

    def format_do_block(self, stmt):
        self.w('DO ')
        if stmt.language_before:
            self.w('LANGUAGE ' + stmt.language_before + ' ')
        self.w(stmt.dollar_body)
        if stmt.language_after:
            self.w(' LANGUAGE ' + stmt.language_after)
        if stmt._has_semicolon:
            self._semi()


def format_sql(sql):
    """Format SQL, returning original unchanged if any error occurs."""
    try:
        tokens = tokenize(sql)
        parser = Parser(tokens)
        results = parser.parse_all()
        formatter = ASTFormatter()
        return formatter.format_all(results)
    except Exception:
        return sql


def main():
    import argparse
    import difflib

    parser = argparse.ArgumentParser(
        description='Custom PostgreSQL SQL formatter for DBeaver.')
    parser.add_argument('file', nargs='?', default=None,
                        help='SQL file to format (in-place unless --check or --diff)')
    parser.add_argument('--check', action='store_true',
                        help='Check if file is already formatted (exit 0=yes, 1=no)')
    parser.add_argument('--diff', action='store_true',
                        help='Show diff between original and formatted output')
    args = parser.parse_args()

    # Read SQL from file or stdin
    label = args.file or 'stdin'
    if args.file:
        with open(args.file, 'r') as f:
            sql = f.read()
    else:
        sql = sys.stdin.read()

    result = format_sql(sql)

    if args.check:
        sys.exit(0 if sql == result else 1)

    if args.diff:
        if sql == result:
            sys.exit(0)
        diff = difflib.unified_diff(
            sql.splitlines(keepends=True),
            result.splitlines(keepends=True),
            fromfile=label,
            tofile=label + ' (formatted)',
        )
        sys.stdout.writelines(diff)
        sys.exit(1)

    # Default: format in-place for files, stdout for stdin
    if args.file:
        with open(args.file, 'w') as f:
            f.write(result)
    else:
        sys.stdout.write(result)


if __name__ == '__main__':
    main()
