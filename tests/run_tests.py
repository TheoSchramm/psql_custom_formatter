#!/usr/bin/env python3
"""Comprehensive test runner for psql_custom_formatter.

Usage:
    python3 tests/run_tests.py

Exit code 0 if all tests pass, 1 if any fail.
"""

import os
import re
import sys
import difflib
import subprocess

# Resolve paths relative to the project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
FORMATTER = os.path.join(PROJECT_DIR, "psql_custom_formatter.py")
EXAMPLE_INPUT = os.path.join(SCRIPT_DIR, "fixtures", "input.sql")
EXAMPLE_EXPECTED = os.path.join(SCRIPT_DIR, "fixtures", "expected.sql")
EDGE_CASES_FILE = os.path.join(SCRIPT_DIR, "edge_cases.sql")

# Keywords that must be uppercased in formatted output
MUST_UPPERCASE_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
    "FULL", "CROSS", "ON", "AND", "OR", "NOT", "IN", "AS", "IS", "NULL",
    "BETWEEN", "LIKE", "EXISTS", "CASE", "WHEN", "THEN", "ELSE", "END",
    "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET", "INSERT", "INTO",
    "VALUES", "UPDATE", "SET", "DELETE", "UNION", "ALL", "DISTINCT",
    "ASC", "DESC", "CREATE", "TABLE", "WITH", "RETURNING",
]

# Fused keyword patterns to reject
FUSED_KEYWORDS = [
    "ENDELSE", "FROMWHERE", "SELECTFROM", "JOINON", "JOINTO",
    "WHEREJOIN", "WHEREAND", "WHEREOR", "ANDFROM", "ORFROM",
    "ENDAS", "ENDFROM", "ENDWHEN", "SELECTWHERE", "FROMJOIN",
    "UPDATESET", "DELETEFROM", "INSERINTO", "ONAND",
    "GROUPBY", "ORDERBY", "LEFTJOIN", "RIGHTJOIN", "INNERJOIN",
    "OUTERJOIN", "CROSSJOIN", "FULLJOIN",
    "THENELSE", "THENEND", "THENWHEN", "ENDAND", "ENDOR",
    "SELECTDISTINCT", "LIMITOFFSET",
]


class TestResult:
    def __init__(self, name):
        self.name = name
        self.passed = True
        self.messages = []

    def fail(self, msg):
        self.passed = False
        self.messages.append(msg)

    def info(self, msg):
        self.messages.append(msg)


def run_formatter(sql_input):
    """Run the formatter on the given SQL string, return (output, error, returncode)."""
    proc = subprocess.run(
        [sys.executable, FORMATTER],
        input=sql_input,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout, proc.stderr, proc.returncode


def parse_edge_case_blocks(filepath):
    """Parse edge_cases.sql into individual test blocks.

    Each block starts with a line matching '-- TEST N: <description>'.
    Returns list of (test_name, sql_block) tuples.
    """
    with open(filepath, "r") as f:
        content = f.read()

    blocks = []
    # Split on the test header pattern
    pattern = re.compile(r"^(-- TEST \d+:.*)$", re.MULTILINE)
    parts = pattern.split(content)

    # parts alternates between non-header text and header matches
    i = 1  # skip any text before the first header
    while i < len(parts):
        header = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sql = header + "\n" + body.strip()
        blocks.append((header, sql))
        i += 2

    return blocks


# ---------------------------------------------------------------------------
# Quality checks applied to formatted output
# ---------------------------------------------------------------------------

def check_no_exceptions(result, output, stderr, returncode):
    """Formatter must not crash."""
    if returncode != 0:
        result.fail(f"Formatter exited with code {returncode}")
    if stderr.strip():
        result.fail(f"Formatter wrote to stderr: {stderr.strip()[:200]}")


def check_no_empty_output(result, sql_input, output):
    """Non-empty input must produce non-empty output."""
    stripped_input = sql_input.strip()
    if stripped_input and not output.strip():
        result.fail("Formatter returned empty output for non-empty input")


def check_no_fused_keywords(result, output):
    """Check that no keywords are fused together (e.g., ENDELSE)."""
    # Build a single regex that catches all fused patterns as whole words
    # We look for these patterns case-insensitively but they should
    # not appear even in lowercase since the formatter uppercases keywords.
    for fused in FUSED_KEYWORDS:
        # Match the fused word as a standalone token (not inside a string or identifier)
        # We check lines that are not inside string literals
        for line in output.split("\n"):
            # Skip comment lines
            stripped = line.strip()
            if stripped.startswith("--") or stripped.startswith("/*"):
                continue
            # Skip string literals in the line for this check
            cleaned = re.sub(r"'[^']*'", "", line)
            cleaned = re.sub(r'"[^"]*"', "", cleaned)
            if re.search(r"\b" + fused + r"\b", cleaned, re.IGNORECASE):
                result.fail(
                    f"Fused keywords detected: '{fused}' in line: {line.strip()}"
                )


def check_no_double_spaces(result, output):
    """No double spaces in non-indentation areas."""
    in_create_table_cols = False  # True inside CREATE TABLE (...) column block
    paren_depth = 0
    lines = output.split("\n")
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        # Detect entry/exit of CREATE TABLE column definition block.
        # The block opens on a line that is exactly '(' (after CREATE TABLE name)
        # and closes when paren_depth returns to 0.
        if in_create_table_cols:
            paren_depth += stripped.count('(') - stripped.count(')')
            if paren_depth <= 0:
                in_create_table_cols = False
            continue  # type-alignment spaces are intentional here
        if stripped == '(':
            # Look back to see if the previous non-empty lines were CREATE TABLE
            prev_nonblank = [l.strip() for l in lines[:lineno - 1] if l.strip()]
            if (len(prev_nonblank) >= 2
                    and prev_nonblank[-2].upper().startswith('CREATE TABLE')
                    and not prev_nonblank[-1].upper().startswith('AS')):
                in_create_table_cols = True
                paren_depth = 1
                continue
        # Skip comment lines
        if stripped.startswith("--") or stripped.startswith("/*"):
            continue
        if not stripped:
            continue
        # Get the non-indentation part: everything after leading whitespace
        content = line.lstrip()
        # Remove string literals so we don't flag spaces inside strings
        cleaned = re.sub(r"'[^']*'", "'X'", content)
        cleaned = re.sub(r'"[^"]*"', '"X"', cleaned)
        # Remove trailing comment (after --) since those can have any spacing
        cleaned = re.sub(r"\s*--.*$", "", cleaned)
        # Now check for double spaces
        if "  " in cleaned:
            result.fail(
                f"Double space in non-indentation area at line {lineno}: "
                f"'{line.rstrip()}'"
            )
            break  # Report only first occurrence per test


def check_semicolons(result, output):
    """No leading space before semicolons (e.g., ' ;')."""
    for lineno, line in enumerate(output.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("/*"):
            continue
        # Check for ' ;' pattern (space before semicolon) outside strings
        cleaned = re.sub(r"'[^']*'", "'X'", stripped)
        if re.search(r"\s;", cleaned):
            result.fail(
                f"Leading space before semicolon at line {lineno}: "
                f"'{line.rstrip()}'"
            )
            break


def check_function_commas(result, output):
    """Commas inside function parens should not have leading spaces.

    Reject: func(a , b)
    Allow:  , column  (leading comma style for column lists)
    """
    for lineno, line in enumerate(output.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("/*"):
            continue
        # Remove strings
        cleaned = re.sub(r"'[^']*'", "'X'", stripped)
        cleaned = re.sub(r'"[^"]*"', '"X"', cleaned)
        # Look for pattern: non-comma-non-paren word/token, then space(s), then comma
        # But only when it appears to be inside function parens.
        # We detect "word ( ... stuff , stuff )" patterns.
        # Simple heuristic: find all occurrences of " ," that are NOT at the
        # start of the content (after stripping), since leading ", col" is allowed.
        # Match " ," where it's preceded by an alphanumeric or closing paren
        matches = list(re.finditer(r"(?<=[a-zA-Z0-9_)\]])\s+,", cleaned))
        for m in matches:
            # Check if this is inside parentheses by counting parens before match
            before = cleaned[: m.start() + 1]
            open_p = before.count("(")
            close_p = before.count(")")
            if open_p > close_p:
                # We are inside parens -- this is likely a function call
                result.fail(
                    f"Leading space before comma inside parens at line {lineno}: "
                    f"'{line.rstrip()}'"
                )
                return  # Report only first occurrence


def check_keywords_uppercased(result, output):
    """Major SQL keywords should be uppercased in formatted output."""
    # We only check keywords that appear as standalone tokens (not inside
    # strings, comments, or identifiers).
    for lineno, line in enumerate(output.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("/*"):
            continue
        # Remove strings, comments, quoted identifiers
        cleaned = re.sub(r"'[^']*'", "'X'", stripped)
        cleaned = re.sub(r'"[^"]*"', '"X"', cleaned)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned)
        cleaned = re.sub(r"--.*$", "", cleaned)
        # Tokenize by word boundaries
        words = re.findall(r"\b[a-zA-Z_]+\b", cleaned)
        for word in words:
            upper = word.upper()
            if upper in MUST_UPPERCASE_KEYWORDS and word != upper:
                # Skip known identifier words that the formatter intentionally lowercases
                if word.lower() in (
                    "name", "value", "type", "status", "id", "number", "amount",
                ):
                    continue
                # Skip if this word is part of a dotted identifier (e.g., table.set)
                # by checking the cleaned line around this word
                idx = cleaned.find(word)
                if idx > 0 and cleaned[idx - 1] == ".":
                    continue
                if idx + len(word) < len(cleaned) and cleaned[idx + len(word)] == ".":
                    continue
                result.fail(
                    f"Keyword '{word}' not uppercased (expected '{upper}') "
                    f"at line {lineno}: '{stripped}'"
                )
                return  # Report only first occurrence


def check_balanced_parens(result, output):
    """Output must have balanced parentheses."""
    # Strip strings and comments first
    cleaned = re.sub(r"'[^']*'", "", output)
    cleaned = re.sub(r'"[^"]*"', "", cleaned)
    cleaned = re.sub(r"--[^\n]*", "", cleaned)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)

    opens = cleaned.count("(")
    closes = cleaned.count(")")
    if opens != closes:
        result.fail(
            f"Unbalanced parentheses: {opens} opening vs {closes} closing"
        )


def run_quality_checks(result, sql_input, output, stderr, returncode):
    """Run all quality checks on a single formatted output."""
    check_no_exceptions(result, output, stderr, returncode)
    check_no_empty_output(result, sql_input, output)
    check_no_fused_keywords(result, output)
    check_no_double_spaces(result, output)
    check_semicolons(result, output)
    check_function_commas(result, output)
    check_keywords_uppercased(result, output)
    check_balanced_parens(result, output)


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------

def check_idempotency(result, output):
    """Format the output a second time; it should be identical."""
    output2, stderr2, rc2 = run_formatter(output)
    if rc2 != 0:
        result.fail(f"Second format pass crashed (exit code {rc2})")
        return
    if output != output2:
        diff = list(
            difflib.unified_diff(
                output.splitlines(keepends=True),
                output2.splitlines(keepends=True),
                fromfile="pass1",
                tofile="pass2",
                n=3,
            )
        )
        diff_text = "".join(diff[:30])  # Limit diff output
        result.fail(f"Idempotency failure -- output changed on second format:\n{diff_text}")


# ---------------------------------------------------------------------------
# Round-trip token sanity
# ---------------------------------------------------------------------------

def extract_tokens(sql):
    """Extract a sorted list of meaningful tokens from SQL for comparison.

    Strips whitespace, lowercases, and extracts word tokens and punctuation.
    We compare tokens as a multiset (sorted list) to catch lost/added tokens.
    """
    # Remove comments
    cleaned = re.sub(r"--[^\n]*", "", sql)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    # Extract words, numbers, string literals, operators
    tokens = re.findall(r"'[^']*'|\"[^\"]*\"|\$\d+|\b\w+\b|[(),;.*<>=!:+\-/%\[\]|&^~@#?$]", cleaned)
    # Lowercase everything for comparison
    return sorted(t.lower() for t in tokens)


def check_round_trip_tokens(result, sql_input, output):
    """Ensure no tokens are lost or added during formatting."""
    input_tokens = extract_tokens(sql_input)
    output_tokens = extract_tokens(output)

    if input_tokens != output_tokens:
        # Find differences
        from collections import Counter
        in_counts = Counter(input_tokens)
        out_counts = Counter(output_tokens)

        missing = in_counts - out_counts
        extra = out_counts - in_counts

        details = []
        if missing:
            top_missing = missing.most_common(5)
            details.append(
                "Missing tokens: "
                + ", ".join(f"'{t}'x{c}" for t, c in top_missing)
            )
        if extra:
            top_extra = extra.most_common(5)
            details.append(
                "Extra tokens: "
                + ", ".join(f"'{t}'x{c}" for t, c in top_extra)
            )
        result.fail("Token round-trip mismatch: " + "; ".join(details))


# ---------------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------------

def test_regression():
    """Test 1: Compare example.sql formatted output vs example_formatted.sql."""
    result = TestResult("Regression: example.sql vs example_formatted.sql")

    if not os.path.isfile(EXAMPLE_INPUT):
        result.fail(f"Missing input file: {EXAMPLE_INPUT}")
        return result
    if not os.path.isfile(EXAMPLE_EXPECTED):
        result.fail(f"Missing expected file: {EXAMPLE_EXPECTED}")
        return result

    with open(EXAMPLE_INPUT, "r") as f:
        sql_input = f.read()
    with open(EXAMPLE_EXPECTED, "r") as f:
        expected = f.read()

    output, stderr, rc = run_formatter(sql_input)

    check_no_exceptions(result, output, stderr, rc)

    if output != expected:
        diff = list(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                output.splitlines(keepends=True),
                fromfile="expected",
                tofile="actual",
                n=3,
            )
        )
        diff_text = "".join(diff[:40])
        result.fail(f"Output differs from expected:\n{diff_text}")

    return result


def test_edge_cases():
    """Test 2: Run each edge case block through the formatter with quality checks."""
    results = []

    if not os.path.isfile(EDGE_CASES_FILE):
        r = TestResult("Edge cases: file loading")
        r.info(
            f"Edge cases file not found at {EDGE_CASES_FILE} -- "
            "skipping edge case tests (create the file to enable them)"
        )
        results.append(r)
        return results

    blocks = parse_edge_case_blocks(EDGE_CASES_FILE)
    if not blocks:
        r = TestResult("Edge cases: parsing")
        r.fail(
            "No test blocks found in edge_cases.sql. "
            "Each test must start with '-- TEST N: description'"
        )
        results.append(r)
        return results

    for test_name, sql_block in blocks:
        result = TestResult(f"Edge case: {test_name}")
        output, stderr, rc = run_formatter(sql_block)
        run_quality_checks(result, sql_block, output, stderr, rc)
        results.append(result)

    return results


def test_idempotency():
    """Test 3: Format each test input twice; output must be stable."""
    results = []

    # Test with example.sql
    if os.path.isfile(EXAMPLE_INPUT):
        with open(EXAMPLE_INPUT, "r") as f:
            sql_input = f.read()
        result = TestResult("Idempotency: example.sql")
        output, stderr, rc = run_formatter(sql_input)
        if rc == 0:
            check_idempotency(result, output)
        else:
            result.fail(f"First format pass failed (exit code {rc})")
        results.append(result)

    # Test with edge case blocks
    if os.path.isfile(EDGE_CASES_FILE):
        blocks = parse_edge_case_blocks(EDGE_CASES_FILE)
        for test_name, sql_block in blocks:
            result = TestResult(f"Idempotency: {test_name}")
            output, stderr, rc = run_formatter(sql_block)
            if rc == 0:
                check_idempotency(result, output)
            else:
                result.fail(f"First format pass failed (exit code {rc})")
            results.append(result)

    return results


def test_round_trip():
    """Test 4: Ensure no tokens are lost or added during formatting."""
    results = []

    # Test with example.sql
    if os.path.isfile(EXAMPLE_INPUT):
        with open(EXAMPLE_INPUT, "r") as f:
            sql_input = f.read()
        result = TestResult("Round-trip tokens: example.sql")
        output, stderr, rc = run_formatter(sql_input)
        if rc == 0:
            check_round_trip_tokens(result, sql_input, output)
        else:
            result.fail(f"Format failed (exit code {rc})")
        results.append(result)

    # Test with edge case blocks
    if os.path.isfile(EDGE_CASES_FILE):
        blocks = parse_edge_case_blocks(EDGE_CASES_FILE)
        for test_name, sql_block in blocks:
            result = TestResult(f"Round-trip tokens: {test_name}")
            output, stderr, rc = run_formatter(sql_block)
            if rc == 0:
                check_round_trip_tokens(result, sql_block, output)
            else:
                result.fail(f"Format failed (exit code {rc})")
            results.append(result)

    return results


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
]


SYNTAX_EXACT_OUTPUT_CASES = [
    (
        'multiplication is not a wildcard',
        'SELECT a*b, 2*(3+4), COUNT(*)*2, t.* FROM t;\n',
        'SELECT\n    a * b\n    , 2 * (3 + 4)\n    , COUNT(*) * 2\n    , t.*\nFROM\n    t;\n',
    ),
    (
        'unary plus/minus are kept and bind tight',
        'SELECT -a, +a, - -a, a - -b FROM t;\n',
        'SELECT\n    -a\n    , +a\n    , - -a\n    , a - -b\nFROM\n    t;\n',
    ),
    (
        'positional parameters keep the dollar sign',
        'SELECT $1, $12::INT FROM t WHERE b = $2;\n',
        'SELECT\n    $1\n    , $12::INT\nFROM\n    t\nWHERE\n    b = $2;\n',
    ),
    (
        'array subscripts and slices',
        'SELECT arr[1], arr[1:3], arr[:3], arr[2:], m[1][2] FROM t;\n',
        'SELECT\n    arr[1]\n    , arr[1:3]\n    , arr[:3]\n    , arr[2:]\n    , m[1][2]\nFROM\n    t;\n',
    ),
    (
        'FOR UPDATE is a clause, not a table alias',
        'SELECT a FROM t WHERE b = 1 FOR UPDATE;\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    b = 1\nFOR UPDATE;\n',
    ),
    (
        'FOR lock options are uppercased',
        'SELECT a FROM t ORDER BY a LIMIT 1 FOR NO KEY UPDATE OF t SKIP LOCKED;\n',
        'SELECT\n    a\nFROM\n    t\nORDER BY\n    a\nLIMIT 1\nFOR NO KEY UPDATE OF t SKIP LOCKED;\n',
    ),
    (
        'multi-column UPDATE SET row assignment',
        'UPDATE t SET (a, b) = (1, 2) WHERE c = 1;\n',
        'UPDATE\n    t\nSET\n    (a, b) = (1, 2)\nWHERE\n    c = 1;\n',
    ),
    (
        'row constructors in WHERE ... IN',
        'SELECT a FROM t WHERE (a, b) IN ((1, 2), (3, 4));\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    (a, b) IN ((1, 2), (3, 4));\n',
    ),
    (
        'MATERIALIZED / NOT MATERIALIZED CTEs',
        'WITH x AS MATERIALIZED (SELECT 1 AS a), y AS NOT MATERIALIZED (SELECT 2 AS b) SELECT * FROM x, y;\n',
        'WITH x AS MATERIALIZED (\n    SELECT\n        1 AS a\n),\ny AS NOT MATERIALIZED (\n    SELECT\n        2 AS b\n)\nSELECT\n    *\nFROM\n    x\n    , y;\n',
    ),
    (
        'SIMILAR TO / NOT SIMILAR TO',
        "SELECT a FROM t WHERE p SIMILAR TO 'x%' AND q NOT SIMILAR TO 'y%';\n",
        "SELECT\n    a\nFROM\n    t\nWHERE\n    p SIMILAR TO 'x%'\n    AND q NOT SIMILAR TO 'y%';\n",
    ),
    (
        '= ALL (subquery) is formatted, not passed through raw',
        'SELECT a FROM t WHERE y = ALL (SELECT 1);\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    y = ALL (SELECT 1);\n',
    ),
    (
        'UPDATE ... SET ... RETURNING',
        'UPDATE t SET a = 1, b = 2 RETURNING a, b;\n',
        'UPDATE\n    t\nSET\n    a = 1\n    , b = 2\nRETURNING\n    a\n    , b;\n',
    ),
    (
        'ON CONFLICT DO UPDATE SET ... WHERE',
        'INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = EXCLUDED.a, b = t.b + 1 WHERE t.a = 1 RETURNING a;\n',
        'INSERT INTO t (\n    a\n)\nVALUES (1)\nON CONFLICT (a) DO UPDATE\nSET\n    a = excluded.a\n    , b = t.b + 1\nWHERE\n    t.a = 1\nRETURNING\n    a;\n',
    ),
    (
        'ON CONFLICT ON CONSTRAINT ... DO NOTHING',
        'INSERT INTO t (a) VALUES (1) ON CONFLICT ON CONSTRAINT t_pk DO NOTHING;\n',
        'INSERT INTO t (\n    a\n)\nVALUES (1)\nON CONFLICT ON CONSTRAINT t_pk DO NOTHING;\n',
    ),
    (
        'ON CONFLICT right after a FROM-less SELECT',
        'INSERT INTO t (a) SELECT 1 ON CONFLICT (a) DO NOTHING;\n',
        'INSERT INTO t (\n    a\n)\nSELECT\n    1\nON CONFLICT (a) DO NOTHING;\n',
    ),
    (
        'comma-separated FROM tables are indented',
        'SELECT a FROM t1, t2 x WHERE t1.id = x.id;\n',
        'SELECT\n    a\nFROM\n    t1\n    , t2 x\nWHERE\n    t1.id = x.id;\n',
    ),
    (
        'DEFAULT is uppercased',
        'UPDATE t SET a = DEFAULT WHERE b = 1;\n',
        'UPDATE\n    t\nSET\n    a = DEFAULT\nWHERE\n    b = 1;\n',
    ),
    (
        'SUBSTRING ... FROM ... FOR keeps FOR uppercase',
        'SELECT SUBSTRING(s FROM 1 FOR 3) FROM t;\n',
        'SELECT\n    SUBSTRING(s FROM 1 FOR 3)\nFROM\n    t;\n',
    ),
    (
        'inline subquery has no space before commas',
        'UPDATE t SET c = (SELECT x, y FROM u) WHERE c = 1;\n',
        'UPDATE\n    t\nSET\n    c = (SELECT x, y FROM u)\nWHERE\n    c = 1;\n',
    ),
]


def _run_exact_output_cases(prefix, cases):
    results = []
    for name, sql_input, expected in cases:
        result = TestResult(f"{prefix}: {name}")
        output, stderr, rc = run_formatter(sql_input)
        if rc != 0:
            result.fail(f"Formatter crashed (exit code {rc}): {stderr}")
        elif output != expected:
            diff = "\n".join(difflib.unified_diff(
                expected.splitlines(), output.splitlines(),
                fromfile="expected", tofile="actual", lineterm=""))
            result.fail(f"Output mismatch:\n{diff}")
        else:
            # The expected output must itself be a fixed point of the formatter
            again, _, rc2 = run_formatter(output)
            if rc2 != 0 or again != output:
                result.fail(f"Output is not idempotent:\n{again}")
        results.append(result)
    return results


def test_comment_positioning():
    """Test 6: Comments/continuation-lines that ARE preserved must land in the
    right place — not just anywhere in the output (exact-output checks, since
    substring-only checks can't catch a comment being on the wrong line)."""
    return _run_exact_output_cases("Comment/list positioning", EXACT_OUTPUT_CASES)


def test_syntax_exact_output():
    """Test 7: Exact formatted output for syntax that used to be mangled or
    silently dropped (operators, subscripts, locking clauses, ON CONFLICT...).
    Round-trip checks alone miss cases where the formatter returns the input
    untouched or reshuffles tokens, so these pin the exact result."""
    return _run_exact_output_cases("Syntax", SYNTAX_EXACT_OUTPUT_CASES)


def test_comment_preservation():
    """Test 5: Comments at clause boundaries must survive formatting, on their own line."""
    results = []
    for name, sql_input, must_contain in COMMENT_PRESERVATION_CASES:
        result = TestResult(f"Comment preservation: {name}")
        output, stderr, rc = run_formatter(sql_input)
        if rc != 0:
            result.fail(f"Formatter crashed (exit code {rc}): {stderr}")
            results.append(result)
            continue
        for snippet in must_contain:
            if snippet not in output:
                result.fail(f"Expected comment {snippet!r} missing from output:\n{output}")
        # The comment text must never be glued onto the same line as a ';'
        for line in output.splitlines():
            if "--" in line and ";" in line and line.strip().startswith("--"):
                result.fail(f"Semicolon appended to a comment line: {line!r}")
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_results = []

    print("=" * 70)
    print("psql_custom_formatter Test Runner")
    print("=" * 70)

    # 1. Regression test
    print("\n--- 1. Regression Test ---")
    r = test_regression()
    all_results.append(r)
    print_result(r)

    # 2. Edge case tests
    print("\n--- 2. Edge Case Tests ---")
    edge_results = test_edge_cases()
    all_results.extend(edge_results)
    for r in edge_results:
        print_result(r)

    # 3. Idempotency tests
    print("\n--- 3. Idempotency Tests ---")
    idem_results = test_idempotency()
    all_results.extend(idem_results)
    for r in idem_results:
        print_result(r)

    # 4. Round-trip token sanity
    print("\n--- 4. Round-Trip Token Tests ---")
    rt_results = test_round_trip()
    all_results.extend(rt_results)
    for r in rt_results:
        print_result(r)

    # 5. Comment preservation tests
    print("\n--- 5. Comment Preservation Tests ---")
    cp_results = test_comment_preservation()
    all_results.extend(cp_results)
    for r in cp_results:
        print_result(r)

    # 6. Comment/list positioning tests (exact output)
    print("\n--- 6. Comment/List Positioning Tests ---")
    pos_results = test_comment_positioning()
    all_results.extend(pos_results)
    for r in pos_results:
        print_result(r)

    # 7. Exact output for previously-mangled syntax
    print("\n--- 7. Syntax Exact-Output Tests ---")
    syn_results = test_syntax_exact_output()
    all_results.extend(syn_results)
    for r in syn_results:
        print_result(r)

    # Summary
    print("\n" + "=" * 70)
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    failed = total - passed
    skipped = sum(1 for r in all_results if r.passed and r.messages)

    print(f"Total: {total}  |  Passed: {passed}  |  Failed: {failed}")
    if skipped:
        print(f"  (of which {skipped} passed with info/skip notices)")
    print("=" * 70)

    if failed > 0:
        print("\nRESULT: FAIL")
        sys.exit(1)
    else:
        print("\nRESULT: PASS")
        sys.exit(0)


def print_result(result):
    status = "PASS" if result.passed else "FAIL"
    print(f"  [{status}] {result.name}")
    for msg in result.messages:
        # Indent detail messages
        for line in msg.split("\n"):
            print(f"         {line}")


if __name__ == "__main__":
    main()
