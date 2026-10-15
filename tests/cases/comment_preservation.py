"""Comments that must survive formatting: (name, input, [substrings the output must contain])."""

# ---------------------------------------------------------------------------
# Targeted comment-preservation regressions
#
# The generic checks above strip comments before comparing (see
# extract_tokens), so they can't catch a formatter change that silently
# drops a comment. These cases pin specific comments that were previously
# lost to clause-boundary comment handling.
# ---------------------------------------------------------------------------

COMMENT_PRESERVATION_CASES = [
    (
        "Multiple standalone comments before FROM",
        "SELECT a, b\n"
        "    --, c\n"
        "    --, d\n"
        "    --, e\n"
        "FROM t;\n",
        ["--, c", "--, d", "--, e"],
    ),
    (
        "Standalone comment before WHERE and after the WHERE keyword",
        "SELECT a\n"
        "FROM t\n"
        "-- before where\n"
        "WHERE\n"
        "    -- first condition\n"
        "    a = 1;\n",
        ["-- before where", "-- first condition"],
    ),
    (
        "Inline trailing comment on the first WHERE condition",
        "SELECT a\n"
        "FROM t\n"
        "WHERE a = 1  -- only active\n"
        "    AND b = 2;\n",
        ["-- only active"],
    ),
    (
        "Trailing comment after a JOIN...ON condition",
        "SELECT a\n"
        "FROM t\n"
        "    JOIN u ON\n"
        "        t.id = u.id  -- join condition\n"
        "WHERE a = 1;\n",
        ["-- join condition"],
    ),
    (
        "Standalone comment before ORDER BY",
        "SELECT a\n"
        "FROM t\n"
        "WHERE a = 1\n"
        "-- final comment\n"
        "ORDER BY a;\n",
        ["-- final comment"],
    ),
    (
        "Semicolon stays off a trailing-comment line",
        "SELECT a\n"
        "FROM t\n"
        "WHERE a = 1  -- note\n"
        ";\n",
        ["-- note"],
    ),
    (
        "Standalone comment between UPDATE SET items",
        "UPDATE t\n"
        "SET\n"
        "    a = 1\n"
        "    -- fill in the real value above\n"
        "    , b = 2\n"
        "WHERE id = 1;\n",
        ["-- fill in the real value above"],
    ),
    (
        "Standalone comment between JOIN...ON and its condition",
        "SELECT a\n"
        "FROM t\n"
        "    JOIN u ON\n"
        "        -- match on the natural key\n"
        "        t.id = u.id\n"
        "WHERE a = 1;\n",
        ["-- match on the natural key"],
    ),
    (
        "Standalone comment right after UPDATE's WHERE keyword",
        "UPDATE t\n"
        "SET a = 1\n"
        "WHERE\n"
        "    -- only active rows\n"
        "    id = 1;\n",
        ["-- only active rows"],
    ),
]
