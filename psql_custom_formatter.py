#!/usr/bin/env python3
"""Custom PostgreSQL SQL formatter for DBeaver.

Reads SQL from stdin or a file, formats it, and outputs the result.
File mode formats in-place (for DBeaver temp file integration).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union
import sys

INDENT = '    '  # 4 spaces

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
    'REPLACE', 'FUNCTION', 'PROCEDURE', 'VIEW',
    'RETURNS', 'LANGUAGE', 'IMMUTABLE', 'STABLE', 'VOLATILE', 'STRICT',
    'LATERAL',
    'ROLLUP', 'CUBE', 'GROUPING', 'SETS', 'FILTER',
    'ROWS', 'RANGE', 'GROUPS', 'PRECEDING', 'FOLLOWING', 'CURRENT', 'UNBOUNDED', 'ROW',
    'WINDOW',
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
        if sql[i].isdigit() or (sql[i] == '.' and i + 1 < n and sql[i+1].isdigit()):
            j = i
            while j < n and (sql[j].isdigit() or sql[j] == '.'):
                j += 1
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
        elif i + 2 < n and sql[i:i+3] in ('->>', '#>>'):
            tokens.append(('OP', sql[i:i+3]))
            i += 3
        elif i + 1 < n and sql[i:i+2] in ('<=', '>=', '<>', '!=', '::', '->', '#>', '||'):
            tokens.append(('OP', sql[i:i+2]))
            i += 2
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
            elif j < n and (sql[j].isalpha() or sql[j] == '_'):
                k = j
                while k < n and (sql[k].isalnum() or sql[k] == '_'):
                    k += 1
                if k < n and sql[k] == '$':
                    delim = sql[i:k+1]
                    body_start = k + 1
                else:
                    i += 1
                    continue
            else:
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
        if prev_type == 'DOT' or cur_type == 'DOT':
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
        elif cur_type in ('COMMA', 'SEMI'):
            need_space = False
        # Tab-align line comments; keep block comments inline with a space
        if cur_type == 'COMMENT':
            if cur_val.lstrip().startswith('--'):
                parts.append('\t')
            else:
                parts.append(' ')
            parts.append(cur_val)
            continue
        if need_space:
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

@dataclass
class WindowSpec:
    partition_by: List[Expression]
    order_by: List[OrderItem]
    frame: Optional[str] = None

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

@dataclass
class BetweenExpr:
    expr: Expression
    negated: bool
    low: Expression
    high: Expression

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

@dataclass
class ArrayExpr:
    elements: List[Expression]

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
    Parenthesized, ArrayExpr, AnyAllExpr, RawTokens,
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
    is_lateral: bool = False
    trailing_comment: Optional[str] = None

@dataclass
class JoinClause:
    join_type: str
    table: TableRef
    on_condition: Optional[Expression] = None
    using_columns: Optional[List[str]] = None

@dataclass
class FromClause:
    tables: List[TableRef]
    joins: List[JoinClause]

@dataclass
class CteClause:
    name: str
    columns: List[str]
    body: SelectStatement

@dataclass
class UnionPart:
    union_type: str
    query: SelectStatement

@dataclass
class SetClause:
    target: str
    value: Expression
    trailing_comment: Optional[str] = None

@dataclass
class ConflictClause:
    raw_tokens: list

@dataclass
class SelectStatement:
    distinct: bool = False
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
    unions: List[UnionPart] = field(default_factory=list)
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
    returning: List[SelectItem] = field(default_factory=list)
    _has_semicolon: bool = False

@dataclass
class DeleteStatement:
    table: str
    schema: Optional[str] = None
    alias: Optional[str] = None
    using_tables: List[TableRef] = field(default_factory=list)
    where: Optional[RawTokens] = None
    returning: List[SelectItem] = field(default_factory=list)
    _has_semicolon: bool = False

@dataclass
class WithStatement:
    recursive: bool
    ctes: List[CteClause]
    main_statement: Statement
    _has_semicolon: bool = False

@dataclass
class CreateTableAsStatement:
    table_name: str
    schema: Optional[str] = None
    if_not_exists: bool = False
    with_clause: Optional[WithStatement] = None
    select: Optional[SelectStatement] = None
    raw_fallback: Optional[list] = None
    _has_semicolon: bool = False

@dataclass
class ColumnDef:
    name: str
    type_str: str            # e.g. 'BIGINT', 'VARCHAR(200)', 'TIMESTAMP WITH TIME ZONE'
    constraint_tokens: list  # raw token tuples for column constraints (NOT NULL, DEFAULT ...)
    trailing_comment: Optional['Comment'] = None

@dataclass
class CreateTableStatement:
    table_name: str
    schema: Optional[str] = None
    if_not_exists: bool = False
    columns: list = field(default_factory=list)            # List[ColumnDef]
    table_constraints: list = field(default_factory=list)  # List[list] of raw token lists
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

@dataclass
class RawStatement:
    tokens: list
    _has_semicolon: bool = False

Statement = Union[
    SelectStatement, InsertStatement, UpdateStatement, DeleteStatement,
    WithStatement, CreateTableAsStatement, CreateTableStatement,
    CreateIndexStatement, DoBlock, RawStatement,
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
    'EXCEPT', 'INTERSECT', ';',
})

_JOIN_START_KWS = frozenset({'JOIN', 'LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS', 'OUTER'})

_INFIX_PREC = {
    'OR': 10, 'AND': 20,
    '=': 45, '<': 45, '>': 45, '<=': 45, '>=': 45, '<>': 45, '!=': 45,
    'LIKE': 40, 'ILIKE': 40,
    '+': 55, '-': 55, '||': 55,
    '->': 58, '->>': 58, '#>': 58, '#>>': 58,
    '*': 60, '/': 60, '%': 60,
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

            stmt = self.parse_statement()
            results.append(stmt)

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
        elif t[1] == 'DO' and self.pk(1)[0] == 'DOLLAR_BODY':
            return self.parse_do_block()
        elif t[0] == 'DOLLAR_BODY':
            return RawStatement([self.eat()])
        else:
            return self.parse_raw_statement()

    def parse_select(self, stop_at_rpar=False):
        stmt = SelectStatement()
        self.eat()  # SELECT
        self.skip_blanks()
        if self.pk()[1] == 'DISTINCT':
            stmt.distinct = True
            self.eat()
        stmt.columns = self.parse_select_list()
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'FROM':
            self.eat()
            stmt.from_clause = self.parse_from_clause()
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'WHERE':
            self.eat()
            self.skip_blanks_and_comments()
            stmt.where = self.parse_expression(stop_fn=self._where_stop)
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'GROUP' and self.pk(1)[1] == 'BY':
            self.eat(); self.eat()
            stmt.group_by = self.parse_expr_list(self._group_stop)
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'HAVING':
            self.eat()
            self.skip_blanks_and_comments()
            stmt.having = self.parse_expression(stop_fn=self._group_stop)
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'ORDER' and self.pk(1)[1] == 'BY':
            self.eat(); self.eat()
            stmt.order_by = self.parse_order_by_list()
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'LIMIT':
            self.eat()
            toks = self.collect_raw(lambda t: t[1] in (';', 'OFFSET', 'FETCH') or t[0] == 'EOF')
            stmt.limit = RawTokens(toks)
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'OFFSET':
            self.eat()
            toks = self.collect_raw(lambda t: t[1] in (';', 'FETCH') or t[0] == 'EOF')
            stmt.offset = RawTokens(toks)
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'FETCH':
            toks = [self.eat()]  # FETCH
            while not self.done() and self.pk()[1] not in (';',) and self.pk()[0] != 'EOF':
                toks.append(self.eat())
            stmt.fetch_clause = RawTokens(toks)
        self.skip_blanks_and_comments()
        if self.pk()[1] == 'FOR':
            parts = []
            while not self.done() and self.pk()[1] not in (';',) and self.pk()[0] != 'EOF' and self.pk()[1] not in ('UNION', 'EXCEPT', 'INTERSECT'):
                parts.append(self.eat()[1])
            stmt.for_clause = ' '.join(parts)
        self.skip_blanks_and_comments()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        # UNION/EXCEPT/INTERSECT
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

    def _where_stop(self, t):
        if t[1] in ('GROUP', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'FETCH',
                     'FOR', 'UNION', 'EXCEPT', 'INTERSECT', 'RETURNING', ';'):
            return True
        if t[1] == 'ON' and self.pk(1)[1] == 'CONFLICT':
            return True
        return t[0] == 'EOF'

    def _group_stop(self, t):
        if t[1] in ('HAVING', 'ORDER', 'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT',
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
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[1] in _CLAUSE_KWS or t[1] == ')' or t[0] == 'EOF':
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
                    # Comments before clause end — attach as trailing to last item
                    while self.pk()[0] == 'COMMENT':
                        c = self.eat()[1]
                        if items and items[-1].trailing_comment is None:
                            items[-1].trailing_comment = c
                    break
                # Between-column comment — store as leading comment of next item
                pending_leading_comment = self.eat()[1]
                continue
            item = self.parse_select_item()
            if pending_leading_comment is not None:
                item.leading_comment = pending_leading_comment
                pending_leading_comment = None
            items.append(item)
        return items

    def parse_select_item(self):
        expr = self.parse_expression(stop_fn=self._select_item_stop)
        item = SelectItem(expr=expr)
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

    def _select_item_stop(self, t):
        if t[1] in _CLAUSE_KWS or t[1] == ')' or t[0] == 'EOF' or t[1] == ',':
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
            self.skip_blanks()
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
            if should_continue:
                while self.pk()[0] in ('COMMENT', 'BLANK_LINE'):
                    self.eat()
            t = self.pk()
            if t[0] == 'EOF' or t[1] == ';':
                break
            if stop_fn and stop_fn(t):
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
            # ANY / ALL as postfix (= ANY(...)) — handled in infix section below
            # Infix operator
            prec = None
            if t[0] == 'OP' and t[1] in _INFIX_PREC:
                prec = _INFIX_PREC[t[1]]
            elif t[0] == 'KW' and t[1] in _INFIX_PREC:
                prec = _INFIX_PREC[t[1]]
            if prec is None or prec < min_prec:
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
                else:
                    inner = self.parse_expression(stop_fn=lambda t: t[1] == ')')
                    if self.pk()[1] == ')':
                        self.eat()
                right = AnyAllExpr(quant, inner)
                left = BinaryOp(op, left, right)
                continue
            right = self.parse_expression(stop_fn=stop_fn, min_prec=prec + 1)
            left = BinaryOp(op, left, right)
        return left

    def _parse_type_name(self):
        """Parse a type name after :: — may be multi-word like 'character varying'."""
        parts = []
        while not self.done():
            t = self.pk()
            if t[0] in ('ID', 'KW') and t[1] not in (';', 'FROM', 'WHERE', 'AND', 'OR',
                                                        'AS', ',', 'THEN', 'ELSE', 'END',
                                                        'WHEN', 'ON', 'JOIN', 'SET'):
                parts.append(self.eat()[1])
                # Handle things like int[] or varchar(n)
                if self.pk()[1] == '[':
                    self.eat()
                    if self.pk()[1] == ']':
                        self.eat()
                    parts[-1] = parts[-1] + '[]'
                elif self.pk()[1] == '(':
                    self.eat()
                    toks = self.collect_raw(lambda t: t[1] == ')')
                    if self.pk()[1] == ')':
                        self.eat()
                    parts[-1] = parts[-1] + '(' + join_expr(toks) + ')'
                # character varying, double precision, etc.
                if self.pk()[0] in ('ID', 'KW') and self.pk()[1].lower() in ('varying', 'precision'):
                    parts.append(self.eat()[1])
            else:
                break
        return ' '.join(parts).upper() if parts else 'TEXT'

    def _parse_in_rhs(self, left, negated, stop_fn):
        if self.pk()[1] != '(':
            # bare IN without parens — treat as raw
            return InExpr(left, negated, [])
        self.eat()  # (
        self.skip_blanks()
        if self.pk()[1] == 'SELECT':
            sub = self.parse_select(stop_at_rpar=True)
            self.skip_blanks()
            if self.pk()[1] == ')':
                self.eat()
            return InExpr(left, negated, [], sub)
        # value list
        vals = []
        while not self.done() and self.pk()[1] != ')':
            self.skip_blanks()
            if self.pk()[1] == ')':
                break
            if self.pk()[1] == ',':
                self.eat()
                continue
            v = self.parse_expression(stop_fn=lambda t: t[1] in (',', ')'))
            vals.append(v)
        if self.pk()[1] == ')':
            self.eat()
        return InExpr(left, negated, vals)

    def _parse_between_rhs(self, left, negated, stop_fn):
        low = self.parse_expression(stop_fn=lambda t: t[1] == 'AND' or (stop_fn and stop_fn(t)))
        if self.pk()[1] == 'AND':
            self.eat()
        high = self.parse_expression(stop_fn=stop_fn)
        return BetweenExpr(left, negated, low, high)

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
        # eat closing ) of ANY(ARRAY[...])
        if not self.done() and self.pk()[1] == ')':
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
                    sub = self.parse_select(stop_at_rpar=True)
                    self.skip_blanks()
                    if self.pk()[1] == ')':
                        self.eat()
                    return ExistsExpr(sub, negated=True)
            inner = self.parse_expression(stop_fn=stop_fn, min_prec=25)
            return UnaryOp('NOT', inner)
        if t[1] == 'EXISTS':
            self.eat()
            self.skip_blanks()
            if self.pk()[1] == '(':
                self.eat()
                sub = self.parse_select(stop_at_rpar=True)
                self.skip_blanks()
                if self.pk()[1] == ')':
                    self.eat()
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
            if self.pk()[1] == ')':
                self.eat()
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
            inner = self.parse_expression(stop_fn=lambda t: t[1] == ')')
            if self.pk()[1] == ')':
                self.eat()
            return AnyAllExpr(quant, inner)
        if t[0] == 'STR':
            return Literal('string', self.eat()[1])
        if t[0] == 'NUM':
            return Literal('number', self.eat()[1])
        if t[0] == 'DOLLAR_BODY':
            return Literal('dollar', self.eat()[1])
        if t[0] == 'WORD':
            return Literal('psql_var', self.eat()[1])
        if t[0] == 'STAR':
            self.eat()
            return Literal('star', '*')
        if t[0] == 'QUOTED_ID':
            val = self.eat()[1]
            return Identifier([val])
        if t[1] == '(':
            # subquery?
            j = 1
            while self.pk(j)[0] == 'BLANK_LINE':
                j += 1
            if self.pk(j)[1] == 'SELECT':
                self.eat()  # (
                sub = self.parse_select(stop_at_rpar=True)
                self.skip_blanks()
                if self.pk()[1] == ')':
                    self.eat()
                return SubqueryExpr(sub)
            # Grouped expression
            self.eat()  # (
            inner = self.parse_expression(stop_fn=lambda t: t[1] == ')')
            if self.pk()[1] == ')':
                self.eat()
            return Parenthesized(inner)
        if t[0] == 'OP' and t[1] == '-':
            self.eat()
            inner = self.parse_expression(stop_fn=stop_fn, min_prec=65)
            return UnaryOp('-', inner)
        if t[0] == 'OP' and t[1] == '+':
            self.eat()
            return self.parse_expression(stop_fn=stop_fn, min_prec=65)
        # ID or KW (identifier or function call)
        if t[0] in ('ID', 'KW'):
            name = self.eat()[1]
            # GROUP BY special forms: ROLLUP(...), CUBE(...), GROUPING SETS(...)
            if name.upper() == 'GROUPING' and self.pk()[1].upper() == 'SETS' and self.pk(1)[1] == '(':
                toks = [('ID', name), self.eat()]  # GROUPING SETS
                toks.extend(self._collect_balanced_parens_raw())
                return RawTokens(toks)
            if name.upper() in ('ROLLUP', 'CUBE') and self.pk()[1] == '(':
                toks = [('ID', name)]
                toks.extend(self._collect_balanced_parens_raw())
                return RawTokens(toks)
            # qualified name (schema.table or schema.func)
            schema = None
            if self.pk()[0] == 'DOT':
                self.eat()
                schema = name
                name = self.eat()[1] if self.pk()[0] in ('ID', 'KW', 'STAR') else name
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

    def parse_case(self):
        self.eat()  # CASE
        self.skip_blanks()
        operand = None
        if self.pk()[1] not in ('WHEN', 'END'):
            operand = self.parse_expression(stop_fn=lambda t: t[1] in ('WHEN', 'END'))
        branches = []
        while self.pk()[1] == 'WHEN':
            self.eat()  # WHEN
            when_expr = self.parse_expression(stop_fn=lambda t: t[1] == 'THEN')
            if self.pk()[1] == 'THEN':
                self.eat()
            then_expr = self.parse_expression(stop_fn=lambda t: t[1] in ('WHEN', 'ELSE', 'END'))
            branches.append((when_expr, then_expr))
        else_expr = None
        if self.pk()[1] == 'ELSE':
            self.eat()
            else_expr = self.parse_expression(stop_fn=lambda t: t[1] == 'END')
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
                sub = self.parse_select(stop_at_rpar=True)
                args.append(SubqueryExpr(sub))
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
                    # EXTRACT special: EXTRACT(field FROM expr) — field is a KW/ID
                    if name.upper() == 'EXTRACT' and not args:
                        # collect field FROM expr as raw
                        toks = self.collect_raw(lambda t: t[1] == ')')
                        args.append(RawTokens(toks))
                        break
                    arg = self.parse_expression(stop_fn=lambda t: t[1] in (',', ')') or
                                                 (t[1] == 'ORDER' and self.pk(1)[1] == 'BY'))
                    args.append(arg)
        if self.pk()[1] == ')':
            self.eat()
        # FILTER clause
        if self.pk()[1] == 'FILTER' and self.pk(1)[1] == '(':
            self.eat()  # FILTER
            self.eat()  # (
            if self.pk()[1] == 'WHERE':
                self.eat()
            filter_clause = self.parse_expression(stop_fn=lambda t: t[1] == ')')
            if self.pk()[1] == ')':
                self.eat()
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
        return FunctionCall(name.upper(), schema, args, distinct, star_arg, order_by, filter_clause, over_clause)

    def parse_window_spec(self):
        partition_by = []
        order_by = []
        frame = None
        self.skip_blanks()
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
            frame = join_expr(toks)
        if self.pk()[1] == ')':
            self.eat()
        return WindowSpec(partition_by, order_by, frame)

    def parse_order_by_list(self):
        items = []
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[1] in ('HAVING', 'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT', ';',
                         'WHERE', 'RETURNING', 'FETCH', 'OFFSET', 'FOR') or t[0] == 'EOF':
                break
            if t[1] == ',':
                self.eat()
                continue
            if t[1] == ')':
                break
            expr = self.parse_expression(stop_fn=lambda t: t[1] in (',', 'ASC', 'DESC', 'NULLS',
                                                                       'HAVING', 'LIMIT', 'UNION',
                                                                       'EXCEPT', 'INTERSECT', ';',
                                                                       'RETURNING', 'FETCH', 'OFFSET')
                                          or t[0] == 'EOF')
            direction = None
            nulls = None
            if self.pk()[1] in ('ASC', 'DESC'):
                direction = self.eat()[1]
            if self.pk()[1] == 'NULLS':
                self.eat()
                if self.pk()[1] in ('FIRST', 'LAST'):
                    nulls = self.eat()[1]
            items.append(OrderItem(expr, direction, nulls))
        return items

    def parse_order_by_list_until_rpar(self):
        items = []
        # ROWS/RANGE/GROUPS mark the start of a window frame spec — stop there
        _stop = (',', 'ASC', 'DESC', 'NULLS', ')', 'ROWS', 'RANGE', 'GROUPS')
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
            if self.pk()[1] in ('ASC', 'DESC'):
                direction = self.eat()[1]
            if self.pk()[1] == 'NULLS':
                self.eat()
                if self.pk()[1] in ('FIRST', 'LAST'):
                    nulls = self.eat()[1]
            items.append(OrderItem(expr, direction, nulls))
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
        return items

    # ── FROM clause ───────────────────────────────────────────────

    def parse_from_clause(self):
        tables = []
        joins = []
        self.skip_blanks()
        # Skip standalone comments before first table
        while self.pk()[0] == 'COMMENT':
            self.eat()
            self.skip_blanks()
        t = self.parse_table_ref()
        tables.append(t)
        while not self.done():
            self.skip_blanks()
            # Skip standalone comments
            while self.pk()[0] == 'COMMENT':
                self.eat()
                self.skip_blanks()
            if self.pk()[1] == ',':
                self.eat()
                self.skip_blanks()
                tables.append(self.parse_table_ref())
                continue
            if self._is_join():
                joins.append(self.parse_join())
                continue
            break
        return FromClause(tables, joins)

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
            if self.pk(j)[1] == 'SELECT':
                self.eat()  # (
                sub = self.parse_select(stop_at_rpar=True)
                self.skip_blanks()
                if self.pk()[1] == ')':
                    self.eat()
                ref.subquery = sub
            elif self.pk(j)[1] == 'VALUES':
                ref.values = self.parse_values_table_ref()
            else:
                # grouped table ref (rare) — treat as subquery fallback
                toks = self._collect_balanced_parens_raw()
                ref.name = join_expr(toks)
        else:
            # regular table name
            if self.pk()[0] in ('ID', 'KW', 'QUOTED_ID'):
                ref.name = self.eat()[1]
            while self.pk()[0] == 'DOT':
                self.eat()
                ref.schema = ref.name
                ref.name = self.eat()[1] if self.pk()[0] in ('ID', 'KW', 'STAR', 'QUOTED_ID') else ref.name
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
            if self.pk()[1] == ')':
                self.eat()
            rows.append(row_toks)
        # outer )
        self.skip_blanks()
        if self.pk()[1] == ')':
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
            if self.pk()[1] == ')':
                self.eat()
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
        self.skip_blanks()
        # skip standalone comments before ON
        while self.pk()[0] == 'COMMENT':
            self.eat()
            self.skip_blanks()
        if self.pk()[1] == 'ON':
            self.eat()
            self.skip_blanks()
            # Capture inline comment after ON (e.g., "ON  -- the join" in formatted output)
            # and attach it to the table ref so round-trips preserve it.
            if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                table.trailing_comment = self.eat()[1]
                self.skip_blanks()
            on_cond = self.parse_expression(stop_fn=self._join_on_stop)
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
                if self.pk()[1] == ')':
                    self.eat()
        return JoinClause(join_type, table, on_cond, using_cols)

    def _join_on_stop(self, t):
        if t[1] in ('WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'SELECT', 'FROM', ';'):
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
        self.skip_blanks()
        if self.pk()[1] == 'FROM':
            self.eat()
            stmt.from_clause = self.parse_from_clause()
        self.skip_blanks()
        if self.pk()[1] == 'WHERE':
            self.eat()
            self.skip_blanks()
            stmt.where = self.parse_expression(stop_fn=self._where_stop)
        self.skip_blanks()
        if self.pk()[1] == 'RETURNING':
            self.eat()
            stmt.returning = self.parse_returning_list()
        self.skip_blanks()
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
        return stmt

    def parse_set_clauses(self):
        clauses = []
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[1] in ('WHERE', 'FROM', ';') or t[0] in ('EOF', 'BLANK_LINE'):
                break
            if t[0] == 'COMMENT':
                self.eat()
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
            val = self.parse_expression(stop_fn=lambda t: t[1] in (',', 'WHERE', 'FROM', ';') or t[0] == 'EOF')
            sc = SetClause(target=target, value=val)
            # trailing comment
            if self.pk()[0] == 'COMMENT' and not self.pk()[2]:
                sc.trailing_comment = self.eat()[1]
            clauses.append(sc)
        return clauses

    def parse_returning_list(self):
        items = []
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[1] in (';',) or t[0] == 'EOF':
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
            stmt.table = self.eat()[1] if self.pk()[0] in ('ID', 'KW') else stmt.table
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
            if self.pk()[1] == ')':
                self.eat()
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
                if self.pk()[1] == ')':
                    self.eat()
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
            toks = self.collect_raw(lambda t: t[1] in (';', 'RETURNING') or t[0] == 'EOF')
            stmt.on_conflict = ConflictClause(toks)
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
        self.skip_blanks()
        if self.pk()[1] == 'WHERE':
            self.eat()
            toks = self.collect_raw(lambda t: t[1] == ';' or t[0] == 'EOF')
            stmt.where = RawTokens(toks)
        self.skip_blanks()
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
            self.skip_blanks()
            if self.pk()[1] in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', ';') or self.pk()[0] == 'EOF':
                break
            if not first_cte:
                # skip comments between CTEs
                while self.pk()[0] == 'COMMENT':
                    self.eat()
                    self.skip_blanks()
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
                    if self.pk()[1] == ')':
                        self.eat()
            if self.pk()[1] == 'AS':
                self.eat()
            self.skip_blanks()
            if self.pk()[1] == '(':
                self.eat()
                self.skip_blanks()
                body = self.parse_select(stop_at_rpar=True)
                self.skip_blanks()
                if self.pk()[1] == ')':
                    self.eat()
            else:
                body = SelectStatement()
            stmt.ctes.append(CteClause(name=cte_name, columns=columns, body=body))
            self.skip_blanks()
            if self.pk()[1] == ',':
                self.eat()
        self.skip_blanks()
        if self.pk()[1] in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
            stmt.main_statement = self.parse_statement()
            stmt._has_semicolon = getattr(stmt.main_statement, '_has_semicolon', False)
        return stmt

    def parse_create(self):
        self.eat()  # CREATE
        unique = False
        if self.pk()[1] == 'UNIQUE':
            unique = True
            self.eat()
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
        # CREATE TABLE — everything else (FUNCTION, VIEW, PROCEDURE, etc.) is raw
        if self.pk()[1] != 'TABLE':
            raw = [('KW', 'CREATE')]
            if unique:
                raw.append(('KW', 'UNIQUE'))
            while not self.done():
                t = self.pk()
                if t[0] == 'BLANK_LINE':
                    self.eat()
                    continue
                if t[1] == ';':
                    raw.append(self.eat())
                    break
                if t[0] == 'EOF':
                    break
                raw.append(self.eat())
            return RawStatement(raw)
        self.eat()  # TABLE
        stmt = CreateTableAsStatement(table_name='')
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
            stmt.table_name = self.eat()[1] if self.pk()[0] in ('ID', 'KW') else stmt.table_name
        # Check for CREATE TABLE (col defs) vs CREATE TABLE ... AS SELECT
        self.skip_blanks()
        if self.pk()[1] == '(':
            return self.parse_create_table_columns(
                stmt.table_name, stmt.schema, stmt.if_not_exists)
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
        'PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK', 'CONSTRAINT', 'EXCLUDE',
    })

    def parse_create_table_columns(self, table_name, schema, if_not_exists):
        """Parse CREATE TABLE name ( col defs ... ) [;]"""
        stmt = CreateTableStatement(
            table_name=table_name, schema=schema, if_not_exists=if_not_exists)
        self.eat()  # consume '('
        while not self.done():
            self.skip_blanks()
            t = self.pk()
            if t[0] == 'COMMENT':
                self.eat()  # drop standalone inter-column comments for now
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
                    stmt.table_constraints.append(tc)
            else:
                col = self.parse_column_def()
                if col is not None:
                    stmt.columns.append(col)
        self.skip_blanks()
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
        body = self.eat()[1]  # DOLLAR_BODY
        stmt = DoBlock(dollar_body=body)
        if self.pk()[1] == ';':
            stmt._has_semicolon = True
            self.eat()
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

    def w(self, s):
        self.out.append(s)

    def nl(self, level):
        self.w('\n' + INDENT * level)

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

    def _emit_trailing_comment(self, text):
        last_line = self._last_line()
        self.w(self._comment_tabs(last_line) + text)

    def format_all(self, results):
        # Track whether we need a 3-blank-line separator before the next item.
        # When a CommentGroup has has_trailing_blank=False, it's "attached" to
        # the next statement — no separator between them.
        needs_sep = False
        for item in results:
            if isinstance(item, CommentGroup):
                if needs_sep:
                    self.w('\n\n\n\n')
                    needs_sep = False
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
                    self.w('\n\n\n\n')
                needs_sep = True
                self.format_statement(item)
        result = ''.join(self.out)
        # Ensure output ends with exactly one newline
        if result and not result.endswith('\n'):
            result += '\n'
        return result

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
        elif isinstance(stmt, RawStatement):
            self.w(join_expr(stmt.tokens))

    def format_select(self, stmt, base=0, is_subquery=False):
        self.w(self.ind(base) + 'SELECT')
        if stmt.distinct:
            self.w(' DISTINCT')
        ci = base + 1
        first = True
        for item in stmt.columns:
            if first:
                self.nl(ci)
                first = False
                self.format_select_item(item, ci)
            else:
                if item.leading_comment:
                    self.nl(ci)
                    self.w(item.leading_comment)
                self.nl(ci)
                self.w(', ')
                self.format_select_item(item, ci)
            continue
        if stmt.from_clause:
            self.nl(base)
            self.w('FROM')
            self.format_from_clause(stmt.from_clause, base)
        if stmt.where is not None:
            self.nl(base)
            self.w('WHERE')
            self.nl(base + 1)
            self.format_where_expr(stmt.where, base + 1, inline_and=is_subquery)
        if stmt.group_by:
            self.nl(base)
            self.w('GROUP BY')
            self._format_expr_list_leading_comma(stmt.group_by, base + 1)
        if stmt.having is not None:
            self.nl(base)
            self.w('HAVING')
            self.nl(base + 1)
            self.format_where_expr(stmt.having, base + 1, inline_and=is_subquery)
        if stmt.order_by:
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
        if stmt._has_semicolon:
            self.w(';')
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
                    first = True
                    for (op, part_expr) in parts:
                        if not first:
                            self.nl(ci)
                            self.w(op + ' ')
                        self.format_expression(part_expr, ci, inline=True)
                        first = False
                else:
                    self.format_expression(expr.left, ci, inline)
                    if expr.op:
                        self.w(' ' + expr.op + ' ')
                    self.format_expression(expr.right, ci, inline)
        elif isinstance(expr, UnaryOp):
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
            self.format_expression(expr.low, ci, inline)
            self.w(' AND ')
            self.format_expression(expr.high, ci, inline)
        elif isinstance(expr, ExistsExpr):
            prefix = 'NOT EXISTS (' if expr.negated else 'EXISTS ('
            self.w(prefix)
            self.w('\n')
            self.format_select(expr.subquery, ci + 1, is_subquery=True)
            self.nl(ci)
            self.w(')')
        elif isinstance(expr, SubqueryExpr):
            self.w('(')
            self.w('\n')
            self.format_select(expr.query, ci + 1, is_subquery=True)
            self.nl(ci)
            self.w(')')
        elif isinstance(expr, Parenthesized):
            self.w('(')
            self.format_expression(expr.expr, ci, inline=True)
            self.w(')')
        elif isinstance(expr, ArrayExpr):
            self.w('ARRAY[')
            for i, el in enumerate(expr.elements):
                if i > 0:
                    self.w(', ')
                self.format_expression(el, ci, inline=True)
            self.w(']')
        elif isinstance(expr, AnyAllExpr):
            self.w(expr.quantifier + '(')
            self.format_expression(expr.array, ci, inline=True)
            self.w(')')
        elif isinstance(expr, RawTokens):
            self.w(join_expr(expr.tokens))

    def _flatten_conditions(self, expr):
        """Flatten top-level AND/OR tree into [(op_or_None, sub_expr)] list."""
        if isinstance(expr, BinaryOp) and expr.op in ('AND', 'OR'):
            left_parts = self._flatten_conditions(expr.left)
            return left_parts + [(expr.op, expr.right)]
        return [(None, expr)]

    def format_where_expr(self, expr, ci, inline_and=False):
        if inline_and:
            self.format_expression(expr, ci, inline=True)
        else:
            parts = self._flatten_conditions(expr)
            first = True
            for (op, part_expr) in parts:
                if not first:
                    self.nl(ci)
                    self.w(op + ' ')
                self.format_expression(part_expr, ci, inline=True)
                first = False

    def format_in_expr(self, expr, ci):
        self.format_expression(expr.expr, ci, inline=True)
        self.w(' NOT IN' if expr.negated else ' IN')
        if expr.subquery:
            self.w(' (')
            self.w('\n')
            self.format_select(expr.subquery, ci + 1, is_subquery=True)
            self.nl(ci)
            self.w(')')
        elif len(expr.values) > 3:
            self.w(' (')
            for i, val in enumerate(expr.values):
                self.nl(ci + 1)
                if i > 0:
                    self.w(', ')
                self.format_expression(val, ci + 1, inline=True)
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
        if call.star_arg:
            self.w('*')
        else:
            for i, arg in enumerate(call.args):
                if i > 0:
                    self.w(', ')
                # SubqueryExpr inside a function call: the function parens serve
                # as the outer parens, so format the SELECT directly (no extra parens)
                if isinstance(arg, SubqueryExpr):
                    self.w('\n')
                    self.format_select(arg.query, ci + 1, is_subquery=True)
                    self.nl(ci)
                else:
                    self.format_expression(arg, ci, inline=True)
        if call.order_by:
            self.w(' ORDER BY ')
            for i, ob in enumerate(call.order_by):
                if i > 0:
                    self.w(', ')
                self.format_expression(ob.expr, ci, inline=True)
                if ob.direction:
                    self.w(' ' + ob.direction)
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
                self.w(' OVER (')
                first_part = True
                if ws.partition_by:
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
                    for i, ob in enumerate(ws.order_by):
                        if i > 0:
                            self.w(', ')
                        self.format_expression(ob.expr, ci, inline=True)
                        if ob.direction:
                            self.w(' ' + ob.direction)
                if ws.frame:
                    self.w(' ' + ws.frame)
                self.w(')')

    def format_from_clause(self, clause, base):
        ci = base + 1
        self.nl(ci)
        if clause.tables:
            self.format_table_ref(clause.tables[0], ci)
        for table in clause.tables[1:]:
            self.nl(ci - 1)
            self.w(', ')
            self.format_table_ref(table, ci)
        for join in clause.joins:
            self.nl(ci)
            self.format_join(join, ci)

    def format_table_ref(self, ref, ci):
        if ref.is_lateral:
            self.w('LATERAL ')
        if ref.subquery:
            self.w('(\n')
            self.format_select(ref.subquery, ci, is_subquery=True)
            self.w('\n')
            self.w(self.ind(ci) + ')')
        elif ref.values:
            self.format_values_table_ref(ref.values, ci)
        else:
            name = ref.name
            if ref.schema:
                name = ref.schema + '.' + name
            self.w(name)
        if ref.alias:
            # Table aliases don't use AS keyword
            if ref.alias_quoted:
                self.w(' "' + ref.alias + '"')
            else:
                self.w(' ' + ref.alias)
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
        if join.on_condition is not None:
            # ON condition always goes on next line (double-indented)
            self.w(' ON')
            if saved_comment:
                self._emit_trailing_comment(saved_comment)
            self.nl(ci + 1)
            self.format_where_expr(join.on_condition, ci + 1, inline_and=False)
        else:
            if saved_comment:
                self._emit_trailing_comment(saved_comment)
        if join.using_columns:
            self.w(' USING (' + ', '.join(join.using_columns) + ')')

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
            first = True
            for sc in stmt.set_clauses:
                if first:
                    self.nl(1)
                    first = False
                else:
                    self.nl(0)
                    self.w(', ')
                self.w(sc.target + ' = ')
                self.format_expression(sc.value, 1, inline=True)
                if sc.trailing_comment:
                    self._emit_trailing_comment(sc.trailing_comment)
        if stmt.from_clause:
            self.nl(0)
            self.w('FROM')
            self.format_from_clause(stmt.from_clause, 0)
        if stmt.where is not None:
            self.nl(0)
            self.w('WHERE')
            self.nl(1)
            self.format_where_expr(stmt.where, 1, inline_and=False)
        if stmt.returning:
            self.nl(0)
            self.w('RETURNING')
            self._format_returning(stmt.returning, 1)
        if stmt._has_semicolon:
            self.w(';')

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
            if stmt.on_conflict.raw_tokens:
                self.w(' ' + join_expr(stmt.on_conflict.raw_tokens))
        if stmt.returning:
            self.nl(0)
            self.w('RETURNING')
            self._format_returning(stmt.returning, 1)
        if stmt._has_semicolon:
            self.w(';')

    def _format_raw_column_list(self, cols, ci):
        first = True
        for col in cols:
            if first:
                self.nl(ci)
                first = False
            else:
                self.nl(ci - 1)
                self.w(', ')
            self.w(col)

    def _format_returning(self, items, ci):
        first = True
        for item in items:
            if first:
                self.nl(ci)
                first = False
            else:
                self.nl(ci - 1)
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
                    self.w(',')
                    self.nl(1)
                self.format_table_ref(t, 1)
        if stmt.where is not None:
            self.nl(0)
            self.w('WHERE')
            self.nl(1)
            self.w(join_expr(stmt.where.tokens))
        if stmt.returning:
            self.nl(0)
            self.w('RETURNING')
            self._format_returning(stmt.returning, 1)
        if stmt._has_semicolon:
            self.w(';')

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
            self.w(cte.name)
            if cte.columns:
                self.w(' (' + ', '.join(cte.columns) + ')')
            self.w(' AS (')
            self.w('\n')
            self.format_select(cte.body, 1)
            self.w('\n)')
            if cte is not stmt.ctes[-1]:
                self.w(',')
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
        'FIRST', 'LAST', 'ASC', 'DESC',
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
        self.w('CREATE TABLE')
        if stmt.if_not_exists:
            self.w(' IF NOT EXISTS')
        self.nl(1)
        name = stmt.table_name
        if stmt.schema:
            name = stmt.schema + '.' + name
        self.w(name)

        # Column name padding: align type names to a consistent column
        pad_to = max((len(col.name) for col in stmt.columns), default=0) + 1

        all_items = (
            [(True, col) for col in stmt.columns] +
            [(False, tc) for tc in stmt.table_constraints]
        )
        self.w('\n(')
        for i, (is_col, item) in enumerate(all_items):
            self.w('\n' + INDENT)
            if is_col:
                self.w(item.name.ljust(pad_to))
                self.w(item.type_str)
                if item.constraint_tokens:
                    self.w(' ' + self._format_constraint_tokens(item.constraint_tokens))
            else:
                self.w(self._format_constraint_tokens(item))
            if i < len(all_items) - 1:
                self.w(',')
            if is_col and item.trailing_comment:
                last_line = self._last_line()
                self.w(self._comment_tabs(last_line) + item.trailing_comment.text)
        self.w('\n)')
        if stmt._has_semicolon:
            self.w(';')

    def format_create_table_as(self, stmt):
        self.w('CREATE TABLE')
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
        if stmt._has_semicolon and not (stmt.select and stmt.select._has_semicolon):
            self.w(';')

    def format_create_index(self, stmt):
        # Raw passthrough
        self.w(join_expr(stmt.raw_rest))

    def format_do_block(self, stmt):
        self.w('DO ')
        self.w(stmt.dollar_body)
        if stmt._has_semicolon:
            self.w(';')


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
