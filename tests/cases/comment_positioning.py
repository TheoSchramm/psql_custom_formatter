"""Exact output for comment placement and list indentation: (name, input, expected_output)."""

EXACT_OUTPUT_CASES = [
    (
        "WHERE-leading comment renders after WHERE, not before it",
        "SELECT a\nFROM t\nWHERE\n    -- only active\n    a = 1;\n",
        "SELECT\n    a\nFROM\n    t\nWHERE\n    -- only active\n    a = 1;\n",
    ),
    (
        "HAVING-leading comment renders after HAVING, not before it",
        "SELECT a, COUNT(*)\nFROM t\nGROUP BY a\nHAVING\n    -- only large groups\n    COUNT(*) > 1;\n",
        "SELECT\n    a\n    , COUNT(*)\nFROM\n    t\nGROUP BY\n    a\nHAVING\n    -- only large groups\n    COUNT(*) > 1;\n",
    ),
    (
        "Comment between FROM and WHERE still renders before WHERE (unaffected by the leading-comment fix)",
        "SELECT a\nFROM t\n-- note before where\nWHERE a = 1;\n",
        "SELECT\n    a\nFROM\n    t\n-- note before where\nWHERE\n    a = 1;\n",
    ),
    (
        "UPDATE's WHERE-leading comment renders after WHERE, not before it",
        "UPDATE t\nSET a = 1\nWHERE\n    -- only active\n    id = 1;\n",
        "UPDATE\n    t\nSET\n    a = 1\nWHERE\n    -- only active\n    id = 1;\n",
    ),
    (
        "INSERT column list: continuation lines indented, not flush left",
        "INSERT INTO t (\n    a,\n    b,\n    c\n)\nVALUES (1, 2, 3);\n",
        "INSERT INTO t (\n    a\n    , b\n    , c\n)\nVALUES (1, 2, 3);\n",
    ),
    (
        "RETURNING list: continuation lines indented, not flush left",
        "INSERT INTO t (a)\nVALUES (1)\nRETURNING a, b, c;\n",
        "INSERT INTO t (\n    a\n)\nVALUES (1)\nRETURNING\n    a\n    , b\n    , c;\n",
    ),
    (
        'comment at the start of a CTE body stays inside the CTE, not above WITH',
        'WITH a AS (\n    SELECT 1 x\n),\nb AS (\n    -- note\n    SELECT x FROM a\n)\nSELECT * FROM b;\n',
        'WITH a AS (\n    SELECT\n        1 AS x\n),\nb AS (\n    -- note\n    SELECT\n        x\n    FROM\n        a\n)\nSELECT\n    *\nFROM\n    b;\n',
    ),
    (
        'comment at the start of a FROM subquery: subquery still formatted, comment above its SELECT',
        'SELECT * FROM (\n    -- sub\n    SELECT 1 x\n) s;\n',
        'SELECT\n    *\nFROM\n    (\n    -- sub\n    SELECT\n        1 AS x\n    ) s;\n',
    ),
    (
        'comment at the start of an IN (SELECT ...) subquery does not leave the statement unformatted',
        'SELECT * FROM t WHERE id IN (\n    -- sub\n    SELECT 1\n);\n',
        'SELECT\n    *\nFROM\n    t\nWHERE\n    id IN (\n        -- sub\n        SELECT\n            1\n    );\n',
    ),
    (
        'block comment at the start of an EXISTS subquery, and -- at the start of a scalar subquery',
        'SELECT (\n  -- scalar\n  SELECT max(x) FROM u) AS m FROM t WHERE EXISTS (\n    /* blk */\n    SELECT 1 FROM u WHERE u.id = t.id\n);\n',
        'SELECT\n    (\n        -- scalar\n        SELECT\n            MAX(x)\n        FROM\n            u\n    ) AS m\nFROM\n    t\nWHERE\n    EXISTS (\n        /* blk */\n        SELECT\n            1\n        FROM\n            u\n        WHERE\n            u.id = t.id\n    );\n',
    ),
    (
        'comment at the start of a data-modifying CTE body stays inside the CTE',
        'WITH d AS (\n  -- dml\n  DELETE FROM t WHERE id = 1 RETURNING id)\nSELECT * FROM d;\n',
        'WITH d AS (\n    -- dml\n    DELETE FROM\n        t\n    WHERE\n        id = 1\n    RETURNING\n        id\n)\nSELECT\n    *\nFROM\n    d;\n',
    ),
]
