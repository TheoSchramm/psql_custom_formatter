"""Shared tables: layout limits, operators and precedence, keyword vocabulary, clause
boundaries, utility-statement words, and the shared syntax-error type.

Rule of thumb: a table lives here when more than one module uses it, or when it is
SQL-language knowledge (keywords, operators, precedence). A table used by a single
method stays next to that method as a class attribute.
"""

from __future__ import annotations


# ── Layout ────────────────────────────────────────────────────────────────────

INDENT = '    '  # 4 spaces

INLINE_SUBQUERY_MAX_CHARS = 64  # subqueries whose one-line form fits within this length are kept on a single line

INLINE_WHERE_MAX_CHARS = 100  # subquery WHERE/HAVING AND/OR chains longer than this break onto separate lines

# Joins several stacked comments kept as one item's leading comment (never occurs in SQL;
# a block comment may itself contain newlines, so '\n' can't be the separator).
COMMENT_SEP = '\x1f'


# ── Operators ─────────────────────────────────────────────────────────────────

# Characters an operator is made of (PostgreSQL lexer rules; see tokenizer._scan_operator).
_OP_CHARS = frozenset('+-*/<>=~!@#%^&|?')

# A multi-character operator may only end in + or - if it contains one of these.
_OP_SPECIAL = frozenset('~!@#%^&|`?')

# Binding power of infix operators / keywords in the Pratt parser (higher binds tighter).
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

# Precedence of any operator not listed above (PostgreSQL: between comparison and +/-).
_OTHER_OP_PREC = 50


# ── Keyword vocabulary ────────────────────────────────────────────────────────

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


# Words that end a FROM item / select item: never taken as an alias.
_NOT_ALIAS_KWS = frozenset({
    'FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'UNION',
    'EXCEPT', 'INTERSECT', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'FULL',
    'CROSS', 'OUTER', 'ON', 'AND', 'OR', 'NOT', 'DISTINCT', 'SELECT',
    'INTO', 'VALUES', 'SET', 'USING', 'RETURNING', 'OFFSET', 'FETCH',
    'FOR', 'LATERAL', ';',
})


# ── Statement starts ──────────────────────────────────────────────────────────

_STATEMENT_START_KWS = frozenset({
    'SELECT', 'UPDATE', 'DELETE', 'INSERT', 'CREATE', 'WITH',
})

# Statements that can follow WITH ... (the main statement of a WITH query).
_WITH_MAIN_KWS = frozenset({'SELECT', 'INSERT', 'UPDATE', 'DELETE'})

# Words that start the next statement when a list runs into it with no `;`.
_NEXT_STATEMENT_KWS = _STATEMENT_START_KWS | frozenset({
    'DROP', 'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE', 'COPY', 'SET', 'BEGIN',
    'COMMIT', 'ROLLBACK', 'EXPLAIN', 'MERGE', 'VACUUM', 'ANALYZE',
})


# ── Clause boundaries ─────────────────────────────────────────────────────────
# Each clause parser stops at the keywords that can follow it. They are built from
# the shared pieces below so a new clause keyword is added in one place.

_SET_OP_KWS = frozenset({'UNION', 'EXCEPT', 'INTERSECT'})

# Clauses that come after ORDER BY.
_QUERY_TAIL_KWS = frozenset({'LIMIT', 'OFFSET', 'FETCH', 'FOR'})

# Window frame starts: ROWS / RANGE / GROUPS ... inside OVER (...).
_WINDOW_FRAME_KWS = frozenset({'ROWS', 'RANGE', 'GROUPS'})

# Words that can follow an ORDER BY item.
_ORDER_ITEM_KWS = frozenset({'ASC', 'DESC', 'NULLS', 'USING'})

# `WITH NO DATA` / `WITH [CASCADED | LOCAL] CHECK OPTION` after a view / CREATE TABLE AS query.
_VIEW_SUFFIX_WORDS = frozenset({'no', 'data', 'check', 'local', 'cascaded'})

_CLAUSE_KWS = frozenset({
    'FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'WINDOW', ';',
}) | _SET_OP_KWS

# What can follow a WHERE condition (also the base set for the other clause ends).
_WHERE_END_KWS = frozenset({'GROUP', 'ORDER', 'HAVING', 'WINDOW', 'RETURNING', ';'}) \
    | _QUERY_TAIL_KWS | _SET_OP_KWS

# GROUP BY items. (GROUP itself is handled separately: GROUP BY starts a new list.)
_GROUP_END_KWS = (_WHERE_END_KWS - {'GROUP'}) | frozenset({'WHERE', 'FROM', 'SELECT', 'CREATE'})

# A JOIN ... ON condition.
_JOIN_ON_END_KWS = _WHERE_END_KWS | frozenset({'WHERE', 'SELECT', 'FROM'})

# ORDER BY lists, and each item's expression.
_ORDER_BY_END_KWS = _WHERE_END_KWS | frozenset({'WHERE'})
_ORDER_ITEM_END_KWS = _ORDER_BY_END_KWS | _ORDER_ITEM_KWS | frozenset({','})

# UPDATE ... SET a = 1, b = 2: the SET list, and each value's expression.
_SET_ITEM_END_KWS = frozenset({'WHERE', 'FROM', 'RETURNING', ';'})
_SET_LIST_END_KWS = _SET_ITEM_END_KWS | _STATEMENT_START_KWS


# ── Utility statements ────────────────────────────────────────────────────────

# Statements that start with one of these words are "utility" statements (DDL,
# transaction control, ...) that have no dedicated formatter. They are kept on
# their own lines with keywords uppercased instead of being mangled as SQL.
UTILITY_STARTERS = frozenset({
    'ALTER', 'DROP', 'TRUNCATE', 'COPY', 'GRANT', 'REVOKE', 'COMMENT', 'SET',
    'RESET', 'SHOW', 'VACUUM', 'ANALYZE', 'ANALYSE', 'REINDEX', 'CLUSTER',
    'LOCK', 'BEGIN', 'COMMIT', 'ROLLBACK', 'START', 'END', 'ABORT',
    'SAVEPOINT', 'RELEASE', 'PREPARE', 'EXECUTE', 'DEALLOCATE', 'DISCARD',
    'LISTEN', 'NOTIFY', 'UNLISTEN', 'CALL', 'REFRESH', 'CHECKPOINT',
    'REASSIGN', 'IMPORT', 'LOAD', 'DECLARE', 'MOVE', 'CLOSE', 'SECURITY', 'FETCH',
})


# Transaction-control statements are short and often written without a
# terminating semicolon, so a following DML keyword ends them.
_TCL_STARTERS = frozenset({
    'BEGIN', 'COMMIT', 'ROLLBACK', 'START', 'END', 'ABORT', 'SAVEPOINT',
    'RELEASE', 'CHECKPOINT',
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
    'OPERATOR', 'AGGREGATE', 'COLLATION', 'ENUM', 'MODULUS', 'REMAINDER', 'PRIOR',
    'SEARCH', 'DEPTH', 'BREADTH', 'CYCLE', 'OLD', 'NEW', 'SHARE', 'EXCLUSIVE', 'ACCESS',
    'LIST', 'HASH',
})


# After one of these the next word is an object name, not a keyword.
_UTILITY_NAME_AFTER = frozenset({
    'COLUMN', 'TABLE', 'INDEX', 'VIEW', 'SCHEMA', 'SEQUENCE', 'FUNCTION',
    'PROCEDURE', 'EXTENSION', 'DATABASE', 'ROLE', 'USER', 'TRIGGER',
    'CONSTRAINT', 'TABLESPACE', 'TYPE', 'DOMAIN', 'COPY', 'INTO', 'FROM',
    'JOIN', 'UPDATE', 'TO', 'ON', 'TRUNCATE', 'ANALYZE', 'VACUUM', 'REINDEX',
    'CLUSTER', 'LOCK', 'REFRESH', 'RENAME', 'OWNER', 'USING', 'REFERENCES',
    'INHERITS', 'AGGREGATE', 'COLLATION',
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
    'SCHEMAS', 'ROUTINES', 'LARGE', 'OBJECTS', 'COMMIT', 'EXCLUSIVE',
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
