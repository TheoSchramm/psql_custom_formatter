"""AST node dataclasses produced by the parser and consumed by the formatter."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union


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
class StringContinuation:
    """Adjacent string literals ('a'<newline>'b'): PostgreSQL concatenates them.
    The pieces must stay on separate lines (on one line it is a syntax error)."""
    pieces: List[str]


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
class WindowSpec:  # (ref_name set: `OVER w`, a reference to a named window)
    partition_by: List[Expression]
    order_by: List[OrderItem]
    frame: Optional[str] = None
    base_name: Optional[str] = None  # OVER (w ORDER BY ...): refines window `w`
    ref_name: Optional[str] = None


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
    # comments that followed each argument (index -1: before the first one)
    arg_comments: dict = field(default_factory=dict)
    within_group: Optional[List[OrderItem]] = None  # percentile_cont(0.5) WITHIN GROUP (ORDER BY x)
    after_order_by: Optional[list] = None  # keyword-style items after ORDER BY (NULL ON NULL RETURNING ...)


@dataclass
class CaseExpr:
    operand: Optional[Expression]
    branches: List[Tuple[Expression, Expression]]
    else_expr: Optional[Expression] = None
    # comments before each WHEN (one list per branch), before ELSE and before END,
    # as (text, on_own_line) pairs
    gap_comments: Optional[dict] = None


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
    bare: bool = False  # inner [..] of a multidimensional ARRAY[[1, 2], [3, 4]] (no ARRAY keyword)


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
    pre_alias_comments: List[str] = field(default_factory=list)  # own-line comments before AS alias


@dataclass
class ValuesClause:
    rows: List[List[Expression]]
    alias: str = ''
    alias_quoted: bool = False
    columns: List[str] = field(default_factory=list)
    row_comments: dict = field(default_factory=dict)  # row index -> comments after it


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
    only: bool = False          # FROM ONLY t: this table, not its inheritance children
    descendants: bool = False   # FROM t *: explicitly including children
    tablesample: Optional[list] = None  # TABLESAMPLE method (args) [REPEATABLE (seed)]: raw tokens
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
    using_alias: Optional[str] = None  # JOIN ... USING (a, b) AS j
    # a JOIN b JOIN c ON x ON y: the right operand is itself a join (b JOIN c ON x)
    nested_joins: list = field(default_factory=list)
    # index into FromClause.tables of the comma item this JOIN follows: in
    # `a JOIN b ON .., c JOIN d ON ..` the JOIN to d belongs to c (the order is semantic)
    after_table: int = 0


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
    # standalone comments between "AS (" and the body (render inside the parens, above the body)
    body_leading_comments: List[str] = field(default_factory=list)
    # SEARCH {BREADTH|DEPTH} FIRST BY ... SET col / CYCLE ... SET ... USING ...: raw tokens
    search_cycle: List[list] = field(default_factory=list)


@dataclass
class UnionPart:
    union_type: str
    query: SelectStatement
    parenthesized: bool = False  # UNION (SELECT ...)


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
    # `(SELECT ...) UNION ...`: the statement starts with a parenthesized query (then
    # the SELECT fields below are unused)
    paren_query: Optional[object] = None
    # ORDER BY / LIMIT / ... after a parenthesized last set operand: raw tokens
    set_tail: list = field(default_factory=list)
    all_rows: bool = False  # SELECT ALL
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
    # standalone comments between a subquery's "(" and its SELECT (render above SELECT)
    leading_comments: List[str] = field(default_factory=list)
    _has_semicolon: bool = False


@dataclass
class InsertStatement:
    table: str
    schema: Optional[str] = None
    alias: Optional[str] = None            # INSERT INTO t AS alias
    columns: List[str] = field(default_factory=list)
    overriding: Optional[str] = None       # OVERRIDING SYSTEM VALUE / OVERRIDING USER VALUE
    default_values: bool = False           # INSERT INTO t DEFAULT VALUES
    values_rows: Optional[List[List[Expression]]] = None
    values_row_comments: dict = field(default_factory=dict)  # row index -> comments after its comma
    select: Optional[SelectStatement] = None
    with_body: Optional[WithStatement] = None  # INSERT INTO t WITH x AS (...) SELECT ...
    on_conflict: Optional[ConflictClause] = None
    returning: List[SelectItem] = field(default_factory=list)
    returning_with: Optional[list] = None  # RETURNING WITH (OLD AS o, NEW AS n): raw tokens
    _has_semicolon: bool = False


@dataclass
class UpdateStatement:
    table: str
    schema: Optional[str] = None
    alias: Optional[str] = None
    only: bool = False
    descendants: bool = False
    set_clauses: List[SetClause] = field(default_factory=list)
    from_clause: Optional[FromClause] = None
    where: Optional[Expression] = None
    # comments between FROM (or SET) and the WHERE keyword itself
    pre_where_comments: List[str] = field(default_factory=list)
    # comments between WHERE and its first condition
    where_leading_comments: List[str] = field(default_factory=list)
    where_trailing_comment: Optional[str] = None
    where_raw: Optional[RawTokens] = None  # WHERE CURRENT OF cursor (not an expression)
    returning: List[SelectItem] = field(default_factory=list)
    returning_with: Optional[list] = None  # RETURNING WITH (OLD AS o, NEW AS n): raw tokens
    _has_semicolon: bool = False


@dataclass
class DeleteStatement:
    table: str
    schema: Optional[str] = None
    alias: Optional[str] = None
    only: bool = False
    descendants: bool = False
    using: Optional[FromClause] = None  # USING a, b JOIN c ON ... (like UPDATE ... FROM)
    where: Optional[Expression] = None
    where_raw: Optional[RawTokens] = None  # WHERE CURRENT OF cursor (not an expression)
    pre_where_comments: List[str] = field(default_factory=list)
    where_leading_comments: List[str] = field(default_factory=list)
    where_trailing_comment: Optional[str] = None
    returning: List[SelectItem] = field(default_factory=list)
    returning_with: Optional[list] = None  # RETURNING WITH (OLD AS o, NEW AS n): raw tokens
    _has_semicolon: bool = False


@dataclass
class WithStatement:
    recursive: bool
    ctes: List[CteClause]
    main_statement: Statement
    _has_semicolon: bool = False
    main_leading_comments: List[str] = field(default_factory=list)
    # standalone comments between a subquery's "(" and its WITH (render above WITH)
    leading_comments: List[str] = field(default_factory=list)


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
    suffix: list = field(default_factory=list)  # raw tokens: WITH [NO] DATA
    # raw tokens between the name and AS: (col, ...) USING m WITH (...) ON COMMIT ... TABLESPACE t
    options: list = field(default_factory=list)
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
class ExpressionFragment:
    """A bare select-list fragment with no statement around it (`CASE ... END AS x`,
    `coalesce(a, b)`), e.g. a DBeaver template or a selection formatted on its own."""
    items: list
    extra_comments: list = field(default_factory=list)
    _has_semicolon: bool = False


@dataclass
class ValuesStatement:
    """VALUES (..), (..) [ORDER BY ...] [LIMIT ...] as a statement of its own."""
    rows: list                                   # raw token lists, one per row
    tail: list = field(default_factory=list)     # raw tokens after the rows (ORDER BY / LIMIT / ...)
    _has_semicolon: bool = False


@dataclass
class VerbatimStatement:
    """Statement the parser/formatter could not handle (invalid SQL, template
    placeholders, ...): its source text is re-emitted exactly as written."""
    text: str


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
    # CREATE FUNCTION / PROCEDURE ... BEGIN ATOMIC <statements> END: the body statements
    atomic_body: Optional[list] = None


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
    insert_overriding: Optional[str] = None  # INSERT ... OVERRIDING SYSTEM|USER VALUE
    leading_comments: list = field(default_factory=list)


@dataclass
class MergeStatement:
    target: object         # TableRef
    source: object         # TableRef
    on_condition: object
    whens: list
    source_joins: list = field(default_factory=list)  # USING a JOIN b ON ... (the source is a join)
    returning: list = field(default_factory=list)
    returning_with: Optional[list] = None  # RETURNING WITH (OLD AS o, NEW AS n): raw tokens
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
