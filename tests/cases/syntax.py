"""Exact output (and idempotency) for syntax that used to be mangled: (name, input, expected_output)."""

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
        "SELECT\n    (CASE\n        WHEN a <> '' THEN 1\t\t-- fixed\n        ELSE b\t\t\t\t\t-- pool\n        END) AS t\nFROM\n    x;\n",
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
    (
        'a comment right after CASE (or its operand) does not break parsing and stays on the CASE line',
        "select case -- c\n when a then 1 -- one\n -- own\n when b then 2 else 3 end as x, case k -- op\n when 1 then 'a' end from t;\n",
        "SELECT\n    CASE\t\t\t\t\t\t-- c\n        WHEN a THEN 1\t\t\t-- one\n        -- own\n        WHEN b THEN 2\n        ELSE 3\n        END AS x\n    , CASE k\t\t\t\t\t-- op\n        WHEN 1 THEN 'a'\n        END\nFROM\n    t;\n",
    ),
    (
        'a comment before the closing paren / between function arguments is kept with its argument',
        "select concat_ws(',', a, b -- last\n), f(a -- x\n, b) from t;\n",
        "SELECT\n    CONCAT_WS(',', a, b\t\t\t-- last\n    )\n    , F(a\t\t\t\t\t\t-- x\n        , b)\nFROM\n    t;\n",
    ),
    (
        'a scalar subquery containing a -- comment is not collapsed onto one line (the comment would swallow the rest)',
        'select (select a -- q\n from k) as s, b from t;\n',
        'SELECT\n    (\n        SELECT\n            a\t\t\t\t\t-- q\n        FROM\n            k\n    ) AS s\n    , b\nFROM\n    t;\n',
    ),
    (
        'a statement that cannot be parsed is kept verbatim; the rest of the file is still formatted',
        'select a from t;\ninsert into x (a) select v.a from (values\n<<PASTE_HERE>>\n) as v(a);  -- placeholder\nselect b from u;\n',
        'SELECT\n    a\nFROM\n    t;\n\n\n\ninsert into x (a) select v.a from (values\n<<PASTE_HERE>>\n) as v(a);  -- placeholder\n\n\n\nSELECT\n    b\nFROM\n    u;\n',
    ),
    (
        'a bare select-list fragment (CASE ... END AS x, func(...)) is formatted like a select list',
        "case when a = 1 then 'x'\n when a = 2 then 'y' else 'z' end as label\n",
        "CASE\n    WHEN a = 1 THEN 'x'\n    WHEN a = 2 THEN 'y'\n    ELSE 'z'\n    END AS label\n",
    ),
    (
        'CREATE OPERATOR / AGGREGATE / COLLATION definition lists: one option per line, keys uppercased',
        "CREATE OPERATOR maintenance.+ (\n    LEFTARG  = text,\n    RIGHTARG = text,\n    FUNCTION = textcat      -- the function behind ||\n);\ncreate aggregate my_sum (int) (sfunc = int4pl, stype = int, initcond = '0');\ncreate type mood as enum ('sad', 'ok');\n",
        "CREATE OPERATOR maintenance.+ (\n    LEFTARG = TEXT\n    , RIGHTARG = TEXT\n    , FUNCTION = textcat\t\t\t\t-- the function behind ||\n);\n\n\n\nCREATE AGGREGATE my_sum (int) (\n    SFUNC = int4pl\n    , STYPE = INT\n    , INITCOND = '0'\n);\n\n\n\nCREATE TYPE mood AS ENUM ('sad', 'ok');\n",
    ),
    (
        'operators are lexed like PostgreSQL: <->, <<=, ===, |/, ||/ are never split; a trailing - / + is a sign',
        'select a === b, c <-> d, m <<= n, x=-1, y<-2, z*-3, a@-1, f(a => 1) from t;\n',
        'SELECT\n    a === b\n    , c <-> d\n    , m <<= n\n    , x = -1\n    , y < -2\n    , z * -3\n    , a @- 1\n    , F(a => 1)\nFROM\n    t;\n',
    ),
    (
        'prefix operators (^, @, |/, ||/) keep their operand; a lone @@ template placeholder is left alone',
        'SELECT\n    2^8\n  , @    -\n5.0,\n    |/                             25\n, ||/ \n27\n;\nupdate t set yy = @@\n-- note\n, b = 1;\n',
        'SELECT\n    2 ^ 8\n    , @ -5.0\n    , |/ 25\n    , ||/ 27;\n\n\n\nUPDATE\n    t\nSET\n    yy = @@\n    -- note\n    , b = 1;\n',
    ),
    (
        "adjacent string literals ('a'<newline>'b') stay one continued literal, never split by a comma or joined on one line",
        "select concat('a, '\n  'b', x), (select 'p'\n'q' from k) as z from t where z = 'e'\n 'f';\ncomment on table t is 'x'\n'y';\n",
        "SELECT\n    CONCAT('a, '\n        'b', x)\n    , (\n        SELECT\n            'p'\n                'q'\n        FROM\n            k\n    ) AS z\nFROM\n    t\nWHERE\n    z = 'e'\n        'f';\n\n\n\nCOMMENT ON TABLE t IS 'x'\n'y';\n",
    ),
    (
        'GROUP BY is followed by OFFSET / FETCH / FOR UPDATE, which are not swallowed into the GROUP BY list',
        'select a from t group by a offset 5;\nselect a from t group by a fetch first 1 rows only;\nselect a from t group by a for update;\n',
        'SELECT\n    a\nFROM\n    t\nGROUP BY\n    a\nOFFSET 5;\n\n\n\nSELECT\n    a\nFROM\n    t\nGROUP BY\n    a\nFETCH FIRST 1 ROWS ONLY;\n\n\n\nSELECT\n    a\nFROM\n    t\nGROUP BY\n    a\nFOR UPDATE;\n',
    ),
    (
        'CREATE TABLE ... AS SELECT ... WITH [NO] DATA keeps the suffix (it is not a new WITH query)',
        'create table x as select a from t with no data;\ncreate table y as select 1 as a with data;\n',
        'CREATE TABLE\n    x AS\n    SELECT\n        a\n    FROM\n        t\nWITH NO DATA;\n\n\n\nCREATE TABLE\n    y AS\n    SELECT\n        1 AS a\nWITH DATA;\n',
    ),
    (
        'DELETE ... USING takes JOINs like UPDATE ... FROM',
        'delete from x using a join b on a.id = b.id where x.id = a.id returning x.a;\n',
        'DELETE FROM\n    x\nUSING\n    a\n    JOIN b ON\n        a.id = b.id\nWHERE\n    x.id = a.id\nRETURNING\n    x.a;\n',
    ),
    (
        'INSERT ... SELECT ... ORDER BY stops at ON CONFLICT',
        'insert into x select a from t order by a on conflict do nothing;\n',
        'INSERT INTO x\nSELECT\n    a\nFROM\n    t\nORDER BY\n    a\nON CONFLICT DO NOTHING;\n',
    ),
    (
        'comma-separated FROM items keep their position relative to JOINs (the binding is semantic)',
        'select 1 from a cross join lateral f(a.x) v1, b p2 join c on c.id = p2.id;\n',
        'SELECT\n    1\nFROM\n    a\n    CROSS JOIN LATERAL F(a.x) v1\n    , b p2\n    JOIN c ON\n        c.id = p2.id;\n',
    ),
    (
        "named arguments with := and =>, prefixed literals (B'', X'', N'', U&'' UESCAPE, E'' with \\\\')",
        'select f(a := \'x\', b => 1), B\'1010\', X\'1F\', N\'n\', U&\'d!0061t\' UESCAPE \'!\', E\'it\\\'s\', "a""b";\n',
        'SELECT\n    F(a := \'x\', b => 1)\n    , B\'1010\'\n    , X\'1F\'\n    , N\'n\'\n    , U&\'d!0061t\' UESCAPE \'!\'\n    , E\'it\\\'s\'\n    , "a""b";\n',
    ),
    (
        'keyword-style function arguments are never split by commas (SQL/XML, SQL/JSON, VARIADIC)',
        "select xmlelement(name foo, xmlattributes(a as b)), xmlexists('//t' passing by value x), json_object('a' value 1 absent on null returning jsonb), json_arrayagg(a order by b null on null), mleast(variadic arr => array[1]);\n",
        "SELECT\n    XMLELEMENT(NAME foo, XMLATTRIBUTES(a AS b))\n    , XMLEXISTS('//t' PASSING BY VALUE x)\n    , JSON_OBJECT('a' VALUE 1 ABSENT ON NULL RETURNING jsonb)\n    , JSON_ARRAYAGG(a ORDER BY b NULL ON NULL)\n    , MLEAST(VARIADIC arr => ARRAY[1]);\n",
    ),
    (
        'typed literals of any type, multi-word types, interval qualifiers, nested arrays, ANY((subquery))',
        "select point '(1,2)', timestamp with time zone '2001-02-16 20:38:40-05' at local, interval '1' day, interval '1.5' second(3), array[[1,2],[3,4]], b = any((select b2 from t2));\n",
        "SELECT\n    point '(1,2)'\n    , TIMESTAMP WITH TIME ZONE '2001-02-16 20:38:40-05' AT LOCAL\n    , interval '1' DAY\n    , interval '1.5' SECOND(3)\n    , ARRAY[[1, 2], [3, 4]]\n    , b = ANY((SELECT b2 FROM t2));\n",
    ),
    (
        'LIKE/SIMILAR TO ... ESCAPE, IS NORMALIZED, OPERATOR(schema.op), WITHIN GROUP, COLLATION FOR, SELECT ALL',
        "select all s not like 'a!%' escape '!', s similar to 'x' escape '#', s is nfd normalized, 3 operator(pg_catalog.+) 4, percentile_disc(0.5) within group (order by income), collation for (s) from t;\n",
        "SELECT ALL\n    s NOT LIKE 'a!%' ESCAPE '!'\n    , s SIMILAR TO 'x' ESCAPE '#'\n    , s IS NFD NORMALIZED\n    , 3 OPERATOR(pg_catalog.+) 4\n    , PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY income)\n    , COLLATION FOR (s)\nFROM\n    t;\n",
    ),
    (
        'INSERT: AS alias, OVERRIDING, DEFAULT VALUES, WITH body; UPDATE WHERE CURRENT OF; DELETE USING with JOIN; RETURNING WITH (OLD/NEW)',
        'insert into t as d (a) overriding system value values (1) on conflict (a) do update set a = excluded.a returning with (old as o, new as n) o.a, n.a;\ninsert into t default values;\nupdate foo set v = 1 where current of c1;\ndelete from only x using a join b on a.id = b.id returning *;\n',
        'INSERT INTO t AS d (\n    a\n)\nOVERRIDING SYSTEM VALUE\nVALUES (1)\nON CONFLICT (a) DO UPDATE\nSET\n    a = excluded.a\nRETURNING WITH (OLD AS o, NEW AS n)\n    o.a\n    , n.a;\n\n\n\nINSERT INTO t\nDEFAULT VALUES;\n\n\n\nUPDATE\n    foo\nSET\n    v = 1\nWHERE\n    CURRENT OF c1;\n\n\n\nDELETE FROM\n    ONLY x\nUSING\n    a\n    JOIN b ON\n        a.id = b.id\nRETURNING\n    *;\n',
    ),
    (
        'VALUES / TABLE / FETCH statements, parenthesized set-operation operands, INTERSECT DISTINCT',
        "values (1, 'one'), (2, 'two') order by 1;\ntable t;\nfetch forward 5 from c;\n(select a from t limit 1) union (select b from u) order by 1;\nselect a from t intersect distinct select b from u;\n",
        "VALUES (1, 'one')\n, (2, 'two')\nORDER BY 1;\n\n\n\nTABLE t;\n\n\n\nFETCH FORWARD 5 FROM c;\n\n\n\n(\n    SELECT\n        a\n    FROM\n        t\n    LIMIT 1\n)\nUNION\n(\n    SELECT\n        b\n    FROM\n        u\n)\nORDER BY 1;\n\n\n\nSELECT\n    a\nFROM\n    t\nINTERSECT DISTINCT\nSELECT\n    b\nFROM\n    u;\n",
    ),
    (
        'CTE SEARCH / CYCLE clauses and MERGE as a CTE body or after WITH',
        'with recursive g (id) as (select 1 union all select id from g) search depth first by id set o cycle id set c using p, m as (merge into x using y on x.id = y.id when matched then delete returning x.*) select * from g, m;\nwith s as (select 1 as id) merge into t using s on t.id = s.id when not matched then insert (id) overriding system value values (s.id);\n',
        'WITH RECURSIVE g (id) AS (\n    SELECT\n        1\n    UNION ALL\n    SELECT\n        id\n    FROM\n        g\n) SEARCH DEPTH FIRST BY id SET o CYCLE id SET c USING p,\nm AS (\n    MERGE INTO x\n    USING y\n    ON\n        x.id = y.id\n    WHEN MATCHED THEN\n        DELETE\n    RETURNING\n        x.*\n)\nSELECT\n    *\nFROM\n    g\n    , m;\n\n\n\nWITH s AS (\n    SELECT\n        1 AS id\n)\nMERGE INTO t\nUSING s\nON\n    t.id = s.id\nWHEN NOT MATCHED THEN\n    INSERT (id) OVERRIDING SYSTEM VALUE\n    VALUES (s.id);\n',
    ),
    (
        'BEGIN ATOMIC function bodies, CREATE TABLE AS with options, PARTITION OF tails',
        'create function g() returns int language sql begin atomic select 1; select 2; end;\ncreate unlogged table c (a, b) with (fillfactor = 70) as select 1, 2 with no data;\ncreate table p1 partition of p for values with (modulus 4, remainder 0);\n',
        'CREATE FUNCTION g() RETURNS INT LANGUAGE sql\nBEGIN ATOMIC\n    SELECT\n        1;\n    SELECT\n        2;\nEND;\n\n\n\nCREATE UNLOGGED TABLE\n    c (a, b) WITH (fillfactor = 70) AS\n    SELECT\n        1\n        , 2\nWITH NO DATA;\n\n\n\nCREATE TABLE\n    p1 PARTITION OF p FOR VALUES WITH (MODULUS 4, REMAINDER 0);\n',
    ),
    (
        'FROM: ONLY / *, TABLESAMPLE, JOIN USING ... AS alias, column definition lists, 3-part names, quoted function names',
        'select s.t.c, "Sch"."myFunc"(1) from only a x tablesample system (10) repeatable (1) join b * using (id) as j, crosstab(\'q\') as (r text, v numeric(10, 2));\n',
        'SELECT\n    s.t.c\n    , "Sch"."myFunc"(1)\nFROM\n    ONLY a x TABLESAMPLE SYSTEM (10) REPEATABLE (1)\n    JOIN b * USING (id) AS j\n    , CROSSTAB(\'q\') AS (r text, v numeric(10, 2));\n',
    ),
    (
        'a statement whose formatting would change its tokens is kept exactly as written',
        'select id, from t;\nselect 1;\n',
        'select id, from t;\n\n\n\nSELECT\n    1;\n',
    ),
    (
        'nested join trees without parentheses (a JOIN b JOIN c ON x ON y), NATURAL joins, MERGE with a joined source',
        'select 1 from a left join b left join c on b.id = c.id on a.id = b.id natural full join d;\nmerge into t using s1 join s2 on s1.k = s2.k on t.id = s1.id when matched then /* note */ delete;\n',
        'SELECT\n    1\nFROM\n    a\n    LEFT JOIN b\n        LEFT JOIN c ON\n            b.id = c.id\n    ON\n        a.id = b.id\n    NATURAL FULL JOIN d;\n\n\n\nMERGE INTO t\nUSING s1\n    JOIN s2 ON\n        s1.k = s2.k\nON\n    t.id = s1.id\n/* note */\nWHEN MATCHED THEN\n    DELETE;\n',
    ),
    (
        'parenthesized and VALUES query operands: ((SELECT ..)) UNION .., IN (VALUES .. ORDER BY ..), CTE body ((VALUES ..) UNION ALL (..))',
        "((select 2)) union (values (3));\nselect ((select 2) union select 2), a in (values (1), (2) order by 1) from t;\nwith recursive x (a) as ((values ('a')) union all (select a from x)) select * from x;\n",
        "(\n    (\n        SELECT\n            2\n    )\n)\nUNION\n(\n    VALUES (3)\n);\n\n\n\nSELECT\n    (( SELECT 2 ) UNION SELECT 2)\n    , a IN (\n        VALUES (1)\n        , (2)\n        ORDER BY 1\n    )\nFROM\n    t;\n\n\n\nWITH RECURSIVE x (a) AS (\n    (\n        VALUES ('a')\n    )\n    UNION ALL\n    (\n        SELECT\n            a\n        FROM\n            x\n    )\n)\nSELECT\n    *\nFROM\n    x;\n",
    ),
    (
        'JSON functions starting with a keyword, JSON_ARRAY(query RETURNING ..), set() as a function, INSERT .. SELECT RETURNING',
        "select json_object(returning jsonb), json_array(select 1 returning jsonb), json_array(with x as (select 1) values (true)), set('t');\ninsert into z select returning old.*, new.*;\n",
        "SELECT\n    JSON_OBJECT(RETURNING jsonb)\n    , JSON_ARRAY(\n        SELECT\n            1\n        RETURNING jsonb\n    )\n    , JSON_ARRAY(\n        WITH x AS (\n            SELECT\n                1\n        )\n        VALUES (TRUE)\n    )\n    , SET('t');\n\n\n\nINSERT INTO z\nSELECT\nRETURNING\n    old.*\n    , new.*;\n",
    ),
    (
        "slices [1:NULL] / ['a':'b'], nested /* /* */ */ comments, *< operators, OVER (ROWS ...) frames, interval(2) '..'",
        "select arr[1:null], j['a':'b'], r *< s, avg(x) over (rows between current row and 1 following), interval(2) '1 day' /* a /* b */ c */ from t;\n",
        "SELECT\n    arr[1:NULL]\n    , j['a':'b']\n    , r *< s\n    , AVG(x) OVER (ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING)\n    , interval(2) '1 day'\t\t/* a /* b */ c */\nFROM\n    t;\n",
    ),
    (
        'comments between VALUES rows (trailing and own-line), after VALUES, before ON CONFLICT; stacked comments between select items',
        'insert into t values -- first\n(1), -- one\n-- next group\n(2) -- last\non conflict do nothing;\nselect a,\n-- b,\n-- c,\nd from (values (1), -- x\n(2)) v (a);\n',
        'INSERT INTO t\nVALUES\t\t\t\t\t\t\t-- first\n(1)\t\t\t\t\t\t\t\t-- one\n-- next group\n, (2)\t\t\t\t\t\t\t-- last\nON CONFLICT DO NOTHING;\n\n\n\nSELECT\n    a\n    -- b,\n    -- c,\n    , d\nFROM\n    (\n    VALUES\n        (1)\t\t\t\t\t\t-- x\n        , (2)\n    ) AS v(a);\n',
    ),
    (
        'CREATE VIEW / TABLE options followed by a comment keep AS out of the comment; TABLESAMPLE without alias; LOCK .. SHARE UPDATE EXCLUSIVE',
        'create view v with (security_barrier = true) -- why\nas select 1;\nselect * from t tablesample system (50);\nlock table t in share update exclusive mode;\n',
        'CREATE VIEW\n    v WITH (security_barrier = TRUE)\t-- why\n    AS\n    SELECT\n        1;\n\n\n\nSELECT\n    *\nFROM\n    t TABLESAMPLE SYSTEM (50);\n\n\n\nLOCK TABLE t IN SHARE UPDATE EXCLUSIVE MODE;\n',
    ),
    (
        'unquoted identifiers: $ inside a name, non-ASCII names kept as written (PostgreSQL folds only ASCII: DESCRIÇÃO is not descrição)',
        'create schema has$dollar;\nselect 1 as DESCRIÇÃO, CAFÉ, função(x), naïve·name, Abc from tbl$x;\n',
        'CREATE SCHEMA has$dollar;\n\n\n\nSELECT\n    1 AS DESCRIÇÃO\n    , CAFÉ\n    , função(x)\n    , naïve·name\n    , abc\nFROM\n    tbl$x;\n',
    ),
    (
        'comment before AS alias, keyword-named bare alias, INSERT INTO t (SELECT ..) UNION .., WITH .. (SELECT ..), ORDER BY .. USING operator(s.op)',
        'select \'hello\'\n  -- why\n  as "text", sum(x) sum from t order by 1 using operator(public.<^);\ninsert into r (select a from p1) union (select a from p2);\nwith a as (select 4) (select 1, 2);\n',
        'SELECT\n    \'hello\'\n    -- why\n    AS "text"\n    , SUM(x) AS sum\nFROM\n    t\nORDER BY\n    1 USING OPERATOR(public.<^);\n\n\n\nINSERT INTO r\n(\n    SELECT\n        a\n    FROM\n        p1\n)\nUNION\n(\n    SELECT\n        a\n    FROM\n        p2\n);\n\n\n\nWITH a AS (\n    SELECT\n        4\n)\n(\n    SELECT\n        1\n        , 2\n);\n',
    ),
]
