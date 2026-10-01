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
    try:
        proc = subprocess.run(
            [sys.executable, FORMATTER],
            input=sql_input,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        # A formatter that hangs must fail the test, not crash the runner
        return "", "formatter timed out after 30s (infinite loop?)", 124
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
        if stripped.startswith("\\"):
            continue  # psql meta-command line: kept verbatim
        # Remove dollar-quoted bodies (kept verbatim), strings, comments, quoted identifiers
        stripped = re.sub(r"\$[A-Za-z_]*\$.*?\$[A-Za-z_]*\$", "$$", stripped)
        stripped = re.sub(r"\$\{[^}]*\}", "PLACEHOLDER", stripped)  # ${template} variables
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


def check_comments_preserved(result, sql_input, output):
    """No comment may be silently dropped (comments are user content)."""
    pat = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
    from collections import Counter
    missing = Counter(pat.findall(sql_input)) - Counter(pat.findall(output))
    if missing:
        result.fail("Comment(s) lost during formatting: " + ", ".join(repr(c) for c in missing))


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
    check_comments_preserved(result, sql_input, output)


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
    tokens = re.findall(r"'[^']*'|\"[^\"]*\"|\$\d+|\b\w+\b|[(),;.*<>=!:+\-/%\[\]|&^~@#?$\\]", cleaned)
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
    (
        'meta-command stays on its own line, code after it is not commented out',
        "\\echo 'start'\n-- note\nROLLBACK;\n",
        "\\echo 'start'\n-- note\nROLLBACK;\n",
    ),
    (
        'meta-commands stay tight; blank line separates from SQL',
        "\\set ON_ERROR_STOP on\n\\echo 'x'\n\nselect 1;\n",
        "\\set ON_ERROR_STOP on\n\\echo 'x'\n\n\n\nSELECT\n    1;\n",
    ),
    (
        'inline meta-command attaches to its statement',
        'select a from t \\gset\n',
        'SELECT\n    a\nFROM\n    t \\gset\n',
    ),
    (
        'transaction control is uppercased and keeps its semicolon tight',
        'begin;\nselect 1;\ncommit;\n',
        'BEGIN;\n\n\n\nSELECT\n    1;\n\n\n\nCOMMIT;\n',
    ),
    (
        'ALTER TABLE: one action per line with leading commas',
        'alter table t add column c int not null default 0, drop column d;\n',
        'ALTER TABLE t\n    ADD COLUMN c INT NOT NULL DEFAULT 0\n    , DROP COLUMN d;\n',
    ),
    (
        'ALTER TABLE: comments stay with their action',
        'alter table t\n    add column comment text, -- the comment\n    -- standalone\n    drop column key;\n',
        'ALTER TABLE t\n    ADD COLUMN comment TEXT\t\t\t-- the comment\n    -- standalone\n    , DROP COLUMN key;\n',
    ),
    (
        'ALTER COLUMN TYPE',
        'alter table t alter column c type bigint using c::bigint;\n',
        'ALTER TABLE t ALTER COLUMN c TYPE BIGINT USING c::BIGINT;\n',
    ),
    (
        'DROP / TRUNCATE / GRANT one-liners',
        'drop table if exists a.b, c cascade;\ntruncate table t restart identity;\ngrant select, insert on table s.t to public, role_a;\n',
        'DROP TABLE IF EXISTS a.b, c CASCADE;\n\n\n\nTRUNCATE TABLE t RESTART IDENTITY;\n\n\n\nGRANT SELECT, INSERT ON TABLE s.t TO PUBLIC, role_a;\n',
    ),
    (
        'CREATE INDEX uses the shared renderer',
        'create unique index idx on s.t (a, b) include (c) where d is not null;\n',
        'CREATE UNIQUE INDEX idx ON s.t (a, b) INCLUDE (c) WHERE d IS NOT NULL;\n',
    ),
    (
        'CREATE FUNCTION envelope',
        'create function f(a int) returns int as $$ select a $$ language sql immutable;\n',
        'CREATE FUNCTION f(a INT) RETURNS INT AS $$ select a $$ LANGUAGE sql IMMUTABLE;\n',
    ),
    (
        'COPY and SET',
        "copy t (a, b) from stdin with (format csv);\nset local work_mem = '64MB';\n",
        "COPY t (a, b) FROM STDIN WITH (format csv);\n\n\n\nSET LOCAL work_mem = '64MB';\n",
    ),
    (
        'EXPLAIN formats the statement under it',
        'explain (analyze, buffers, format json) select * from t where a = 1;\n',
        'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\nSELECT\n    *\nFROM\n    t\nWHERE\n    a = 1;\n',
    ),
    (
        'EXPLAIN ANALYZE UPDATE',
        'explain analyze update t set a = 1 where b = 2;\n',
        'EXPLAIN ANALYZE\nUPDATE\n    t\nSET\n    a = 1\nWHERE\n    b = 2;\n',
    ),
    (
        'CREATE VIEW',
        'create or replace view v (x, y) as select a, b from t where c = 1;\n',
        'CREATE OR REPLACE VIEW\n    v (x, y) AS\n    SELECT\n        a\n        , b\n    FROM\n        t\n    WHERE\n        c = 1;\n',
    ),
    (
        'CREATE MATERIALIZED VIEW ... WITH NO DATA',
        'create materialized view mv as select 1 with no data;\n',
        'CREATE MATERIALIZED VIEW\n    mv AS\n    SELECT\n        1\nWITH NO DATA;\n',
    ),
    (
        'CREATE TEMP TABLE AS',
        'create temp table x as select 1;\n',
        'CREATE TEMP TABLE\n    x AS\n    SELECT\n        1;\n',
    ),
    (
        'CREATE TABLE AS TABLE',
        'create table a as table b;\n',
        'CREATE TABLE\n    a AS\n    TABLE b;\n',
    ),
    (
        'MERGE',
        'merge into t using s on t.id = s.id when matched and s.del then delete when matched then update set a = s.a, b = s.b when not matched then insert (id, a) values (s.id, s.a);\n',
        'MERGE INTO t\nUSING s\nON\n    t.id = s.id\nWHEN MATCHED AND s.del THEN\n    DELETE\nWHEN MATCHED THEN\n    UPDATE SET\n        a = s.a\n        , b = s.b\nWHEN NOT MATCHED THEN\n    INSERT (id, a)\n    VALUES (s.id, s.a);\n',
    ),
    (
        'SELECT INTO',
        'select * into new_t from old_t where a = 1;\n',
        'SELECT\n    *\nINTO\n    new_t\nFROM\n    old_t\nWHERE\n    a = 1;\n',
    ),
    (
        'AT TIME ZONE chains',
        "select ts at time zone 'UTC', ts at time zone 'a' at time zone 'b' from t;\n",
        "SELECT\n    ts AT TIME ZONE 'UTC'\n    , ts AT TIME ZONE 'a' AT TIME ZONE 'b'\nFROM\n    t;\n",
    ),
    (
        'COLLATE',
        'select a collate "C" from t order by a collate "C";\n',
        'SELECT\n    a COLLATE "C"\nFROM\n    t\nORDER BY\n    a COLLATE "C";\n',
    ),
    (
        'ISNULL / NOTNULL / OVERLAPS',
        'select a from t where b isnull and c notnull and (a, b) overlaps (c, d);\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    b ISNULL\n    AND c NOTNULL\n    AND (a, b) OVERLAPS (c, d);\n',
    ),
    (
        'BETWEEN SYMMETRIC',
        'select a from t where d between symmetric 1 and 2;\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    d BETWEEN SYMMETRIC 1 AND 2;\n',
    ),
    (
        'IS JSON',
        'select a is json, b is not json array from t;\n',
        'SELECT\n    a IS JSON\n    , b IS NOT JSON ARRAY\nFROM\n    t;\n',
    ),
    (
        'ORDER BY ... USING and NULLS',
        'select a from t order by a using <, b desc nulls last;\n',
        'SELECT\n    a\nFROM\n    t\nORDER BY\n    a USING <\n    , b DESC NULLS LAST;\n',
    ),
    (
        'NULLS FIRST/LAST kept inside aggregates and windows',
        'select array_agg(a order by b desc nulls last), sum(x) over (order by y desc nulls first) from t;\n',
        'SELECT\n    ARRAY_AGG(a ORDER BY b DESC NULLS LAST)\n    , SUM(x) OVER (ORDER BY y DESC NULLS FIRST)\nFROM\n    t;\n',
    ),
    (
        'field selection from composite values',
        'select (a).b, (a).*, a.b[1].c from t;\n',
        'SELECT\n    (a).b\n    , (a).*\n    , a.b[1].c\nFROM\n    t;\n',
    ),
    (
        'type modifiers on multi-word types',
        'select a::character varying(10), b::numeric(10,2), c::timestamp with time zone from t;\n',
        'SELECT\n    a::CHARACTER VARYING(10)\n    , b::NUMERIC(10, 2)\n    , c::TIMESTAMP WITH TIME ZONE\nFROM\n    t;\n',
    ),
    (
        'TRIM / POSITION / OVERLAY / EXTRACT / SUBSTRING argument syntax',
        "select trim(both 'x' from s), position('a' in s), overlay(s placing 'x' from 1 for 2), extract(epoch from now() - ts), substring(s from '[0-9]+') from t;\n",
        "SELECT\n    TRIM(BOTH 'x' FROM s)\n    , POSITION('a' IN s)\n    , OVERLAY(s PLACING 'x' FROM 1 FOR 2)\n    , EXTRACT(epoch FROM NOW() - ts)\n    , SUBSTRING(s FROM '[0-9]+')\nFROM\n    t;\n",
    ),
    (
        '= ANY (VALUES ...)',
        'select a from t where b = any (values (1), (2));\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    b = ANY (VALUES (1), (2));\n',
    ),
    (
        'WINDOW clause',
        'select a, sum(b) over w from t window w as (partition by a order by c), w2 as (order by d) order by a;\n',
        'SELECT\n    a\n    , SUM(b) OVER w\nFROM\n    t\nWINDOW\n    w AS (PARTITION BY a ORDER BY c)\n    , w2 AS (ORDER BY d)\nORDER BY\n    a;\n',
    ),
    (
        'data-modifying CTE',
        'with i as (insert into t values (1) returning id) select * from i;\n',
        'WITH i AS (\n    INSERT INTO t\n    VALUES (1)\n    RETURNING\n        id\n)\nSELECT\n    *\nFROM\n    i;\n',
    ),
    (
        'data-modifying CTE feeding INSERT',
        'with moved as (delete from a where x = 1 returning *) insert into b select * from moved;\n',
        'WITH moved AS (\n    DELETE FROM\n        a\n    WHERE\n        x = 1\n    RETURNING\n        *\n)\nINSERT INTO b\nSELECT\n    *\nFROM\n    moved;\n',
    ),
    (
        'DELETE has a structured WHERE and RETURNING',
        'delete from t using u, v where t.id = u.id and u.k = v.k returning t.id;\n',
        'DELETE FROM\n    t\nUSING\n    u\n    , v\nWHERE\n    t.id = u.id\n    AND u.k = v.k\nRETURNING\n    t.id;\n',
    ),
    (
        'DELETE ... WHERE CURRENT OF',
        'delete from t where current of c;\n',
        'DELETE FROM\n    t\nWHERE\n    CURRENT OF c;\n',
    ),
    (
        'ROLLUP / CUBE / GROUPING SETS spacing',
        'select a from t group by rollup (a, b), cube (c, d), grouping sets ((e), (f), ());\n',
        'SELECT\n    a\nFROM\n    t\nGROUP BY\n    ROLLUP (a, b)\n    , CUBE (c, d)\n    , GROUPING SETS ((e), (f), ());\n',
    ),
    (
        'DO with LANGUAGE before the body',
        'do language plpgsql $$ begin perform 1; end $$;\n',
        'DO LANGUAGE plpgsql $$ begin perform 1; end $$;\n',
    ),
    (
        'DO with LANGUAGE after the body',
        'do $$ begin null; end $$ language plpgsql;\n',
        'DO $$ begin null; end $$ LANGUAGE plpgsql;\n',
    ),
    (
        'comment between FROM table and next JOIN',
        'select a\nfrom t\n-- note\njoin u on u.id = t.id;\n',
        'SELECT\n    a\nFROM\n    t\n    -- note\n    JOIN u ON\n        u.id = t.id;\n',
    ),
    (
        'comment between joined table and ON',
        'select a\nfrom t\njoin u p\n-- note\non p.id = t.id;\n',
        'SELECT\n    a\nFROM\n    t\n    JOIN u p\n        -- note\n    ON\n        p.id = t.id;\n',
    ),
    (
        'comment before first FROM table and comma table',
        'select a\nfrom\n-- first\nt\n-- second\n, u;\n',
        'SELECT\n    a\nFROM\n    -- first\n    t\n    -- second\n    , u;\n',
    ),
    (
        'leading comment on first SELECT item',
        'select\n-- note\na\n, b\nfrom t;\n',
        'SELECT\n    -- note\n    a\n    , b\nFROM\n    t;\n',
    ),
    (
        'CREATE TABLE column comments',
        'create table t (\n-- the id\nid int,\n-- the name\nname text -- trailing\n);\n',
        'CREATE TABLE\n    t\n(\n    -- the id\n    id   INT,\n    -- the name\n    name TEXT\t\t\t\t\t-- trailing\n);\n',
    ),
    (
        'CREATE TABLE trailing comma comment and constraint comment',
        'create table t (\nid int, -- first\n-- uniq\nunique (id) -- u\n);\n',
        'CREATE TABLE\n    t\n(\n    id INT,\t\t\t\t\t\t-- first\n    -- uniq\n    UNIQUE (id)\t\t\t\t\t-- u\n);\n',
    ),
    (
        'CREATE TABLE table options',
        'create table t (id int, name text) partition by range (id);\n',
        'CREATE TABLE\n    t\n(\n    id   INT,\n    name TEXT\n) PARTITION BY RANGE (id);\n',
    ),
    (
        'CREATE TABLE LIKE',
        'create table a (like b including all);\n',
        'CREATE TABLE\n    a\n(\n    LIKE b INCLUDING ALL\n);\n',
    ),
    (
        'IN list comments',
        'select a from t where a in (\n1, -- one\n2 -- two\n);\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    a IN (\n        1\t\t\t\t\t\t-- one\n        , 2\t\t\t\t\t\t-- two\n    );\n',
    ),
    (
        'comments never swallow code in VALUES rows',
        'insert into t (a, b) values (1, -- one\n2);\n',
        'INSERT INTO t (\n    a\n    , b\n)\nVALUES (1,\t-- one\n2);\n',
    ),
    (
        'semicolon after a trailing comment goes on its own line',
        'UPDATE t SET a = 1 WHERE id IN ()  -- note\n;\n',
        'UPDATE\n    t\nSET\n    a = 1\nWHERE\n    id IN ()\t\t\t\t\t-- note\n;\n',
    ),
    (
        'semicolon after a DELETE trailing comment',
        'delete from t where a = 1 -- c\n;\n',
        'DELETE FROM\n    t\nWHERE\n    a = 1\t\t\t\t\t\t-- c\n;\n',
    ),
    (
        'bare dollar-quoted statement keeps its semicolon',
        '$$body$$;\n',
        '$$body$$;\n',
    ),
    (
        'subquery function arguments keep their parentheses',
        'select coalesce(a, (select 1), 2), coalesce((select max(x) from t), 0), array(select 1) from u;\n',
        'SELECT\n    COALESCE(a, (SELECT 1), 2)\n    , COALESCE((SELECT MAX(x) FROM t), 0)\n    , ARRAY(\n        SELECT\n            1\n    )\nFROM\n    u;\n',
    ),
    (
        'IN (VALUES ...)',
        'select a from t where b in (values (1), (2));\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    b IN (VALUES (1), (2));\n',
    ),
    (
        'window refinement: OVER (w ORDER BY ...)',
        'select sum(a) over (w order by b) from t window w as (partition by c);\n',
        'SELECT\n    SUM(a) OVER (w ORDER BY b)\nFROM\n    t\nWINDOW\n    w AS (PARTITION BY c);\n',
    ),
    (
        'window frame EXCLUDE is uppercased',
        'select sum(a) over (partition by b range between unbounded preceding and current row exclude ties) from t;\n',
        'SELECT\n    SUM(a) OVER (PARTITION BY b RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW EXCLUDE TIES)\nFROM\n    t;\n',
    ),
    (
        'function in FROM with WITH ORDINALITY and column aliases',
        'select a from t cross join lateral unnest(arr) with ordinality as u(x, n);\n',
        'SELECT\n    a\nFROM\n    t\n    CROSS JOIN LATERAL UNNEST(arr) WITH ORDINALITY u (x, n);\n',
    ),
    (
        'comments after a blank line lead the next statement, not the previous one',
        'SELECT a\nFROM t\nWHERE b = 1\n\n\n\n-- note one\n-- note two\nSELECT c\nFROM u;\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    b = 1\n\n\n\n-- note one\n-- note two\nSELECT\n    c\nFROM\n    u;\n',
    ),
    (
        'comment directly after a statement stays with it',
        'SELECT a FROM t\n-- tight\n\n\n-- loose\nSELECT b;\n',
        'SELECT\n    a\nFROM\n    t\n    -- tight\n\n\n\n-- loose\nSELECT\n    b;\n',
    ),
    (
        'UPDATE without semicolon does not swallow the next statement as a SET item',
        'UPDATE t SET a = 1\n\n\n-- next\nSELECT 1;\n',
        'UPDATE\n    t\nSET\n    a = 1\n\n\n\n-- next\nSELECT\n    1;\n',
    ),
    (
        'comments between SET items and WHERE',
        'UPDATE t SET a = 1,\n-- b\nb = 2\n-- before where\nWHERE c = 1;\n',
        'UPDATE\n    t\nSET\n    a = 1\n    -- b\n    , b = 2\n-- before where\nWHERE\n    c = 1;\n',
    ),
    (
        'a comment before a closing paren does not mis-nest the expression',
        'SELECT a FROM t WHERE b = (c + 1 -- note\n) AND d = 1;\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    b = (c + 1\t\t\t\t\t-- note\n    )\n    AND d = 1;\n',
    ),
    (
        'numeric literals keep exponents, hex and underscores',
        'select 1e10, 1.5e-3, 0x1F, 1_000, 2.E+2, .5 from t;\n',
        'SELECT\n    1e10\n    , 1.5e-3\n    , 0x1F\n    , 1_000\n    , 2.E+2\n    , .5\nFROM\n    t;\n',
    ),
    (
        'digit-led unquoted names stay whole and keep their qualifier',
        'select * from maintenance.1433617_serra where a = 1;\n',
        'SELECT\n    *\nFROM\n    maintenance.1433617_serra\nWHERE\n    a = 1;\n',
    ),
    (
        'a block comment after a line comment never joins the line comment',
        'select a from t where b = 1 --x\n/* block */ and c = 2;\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    b = 1\t\t\t\t\t\t--x\n    /* block */\n    AND c = 2;\n',
    ),
    (
        'WITH without a main query keeps its semicolon',
        'with cte as (select 1);\nselect 2;\n',
        'WITH cte AS (\n    SELECT\n        1\n);\n\n\n\nSELECT\n    2;\n',
    ),
    (
        'comments after a multi-line select item and a blank line lead the next statement',
        "select\n'a\nb'\n\n-- c1\n-- c2\n/* x */\n",
        "SELECT\n    'a\nb'\n\n\n\n-- c1\n-- c2\n/* x */\n",
    ),
    (
        'comment before a closing paren after a blank-line separated statement',
        'SELECT a FROM t WHERE b = 1\n\n\n-- n\nSELECT 2;\n',
        'SELECT\n    a\nFROM\n    t\nWHERE\n    b = 1\n\n\n\n-- n\nSELECT\n    2;\n',
    ),
    (
        'raw statement keeps its own comment exactly once',
        "SELECT 1;\n\n\n'2026-06-01'\n-- note\n\n\nSELECT 2;\n",
        "SELECT\n    1;\n\n\n\n'2026-06-01'\n-- note\n\n\n\nSELECT\n    2;\n",
    ),
    (
        'a SELECT without a semicolon does not swallow the next statement into its select list',
        "select 'x'\n\n-- c\n\ndrop table if exists m.x;\n",
        "SELECT\n    'x'\n\n\n\n-- c\n\n\n\nDROP TABLE IF EXISTS m.x;\n",
    ),
    (
        'keyword-style function arguments keep the space after a comma',
        "select trim((select 1 limit 1), '/');\n",
        "SELECT\n    TRIM((SELECT 1 LIMIT 1), '/');\n",
    ),
    (
        'ROWS FROM with ORDINALITY',
        "select m.ord from erp.reports r,\nlateral rows from (regexp_matches(r.d, 'x', 'gi'), unnest(a)) with ordinality as m(tag, ord) where r.id = 1;\n",
        "SELECT\n    m.ord\nFROM\n    erp.reports r\n    , LATERAL ROWS FROM (regexp_matches(r.d, 'x', 'gi'), unnest(a)) WITH ORDINALITY m (tag, ord)\nWHERE\n    r.id = 1;\n",
    ),
    (
        'DBeaver ${placeholders} stay whole, including in dotted names',
        'select a.${col}, ${sch}.t.x from erp.${table} t join ${s}.u on 1=1;\n',
        'SELECT\n    a.${col}\n    , ${sch}.t.x\nFROM\n    erp.${table} t\n    JOIN ${s}.u ON\n        1 = 1;\n',
    ),
    (
        'VALUES CTE body is not turned into SELECT',
        'with r(a) as (values (0.01), (-0.01)) select * from r;\n',
        'WITH r (a) AS (\n    VALUES (0.01), (-0.01)\n)\nSELECT\n    *\nFROM\n    r;\n',
    ),
    (
        'comments inside CASE do not cut the CASE short',
        "select (case\n when a <> '' then\n 1 -- fixed\n else\n b -- pool\n end) as t from x;\n",
        "-- fixed\n-- pool\nSELECT\n    (CASE\n        WHEN a <> '' THEN 1\n        ELSE b\n        END) AS t\nFROM\n    x;\n",
    ),
    (
        'ORDER BY / GROUP BY lists do not swallow the next statement when there is no semicolon',
        'select a from t order by a desc\ndrop table m.x;\nselect b from u group by b\ntruncate t;\n',
        'SELECT\n    a\nFROM\n    t\nORDER BY\n    a DESC\n\n\n\nDROP TABLE m.x;\n\n\n\nSELECT\n    b\nFROM\n    u\nGROUP BY\n    b\n\n\n\nTRUNCATE t;\n',
    ),
    (
        'WITH inside EXISTS / IN subqueries',
        'select 1 where exists (with c(x) as (select 1) select x from c) and a in (with d as (select 2) select * from d);\n',
        'SELECT\n    1\nWHERE\n    EXISTS (\n        WITH c (x) AS (\n            SELECT\n                1\n        )\n        SELECT\n            x\n        FROM\n            c\n    )\n    AND a IN (\n        WITH d AS (\n            SELECT\n                2\n        )\n        SELECT\n            *\n        FROM\n            d\n    );\n',
    ),
    (
        'a cast does not swallow the operator that follows it (::text LIKE, ::int IN, ::t IS NULL, ...)',
        "select a::text like '0%', b::int in (1,2), c::numeric(10,2) is null, d::timestamp(3) with time zone, i::int between 1 and 2, j::text || 'x' from t where a::text ilike 'x%' and b::int not in (1);\n",
        "SELECT\n    a::TEXT LIKE '0%'\n    , b::INT IN (1, 2)\n    , c::NUMERIC(10, 2) IS NULL\n    , d::TIMESTAMP(3) WITH TIME ZONE\n    , i::INT BETWEEN 1 AND 2\n    , j::TEXT || 'x'\nFROM\n    t\nWHERE\n    a::TEXT ILIKE 'x%'\n    AND b::INT NOT IN (1);\n",
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
