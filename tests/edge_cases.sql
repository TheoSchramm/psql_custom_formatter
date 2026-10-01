-- TEST 1: EXTRACT(YEAR FROM ...) where FROM is not a clause keyword
SELECT
    EXTRACT(YEAR FROM created_at) AS yr,
    EXTRACT(EPOCH FROM now() - updated_at) AS age_secs,
    EXTRACT(DOW FROM TIMESTAMP '2024-01-15 10:30:00') AS weekday
FROM events
WHERE EXTRACT(MONTH FROM created_at) = 12;


-- TEST 2: Deeply nested subqueries (3+ levels) with mixed AND/OR
SELECT *
FROM users u
WHERE u.id IN (
    SELECT user_id FROM orders WHERE total > 100 AND status IN (
        SELECT code FROM statuses WHERE active = TRUE AND category IN (
            SELECT cat FROM categories WHERE parent_id IS NOT NULL OR legacy = TRUE
        )
    )
) AND u.deleted_at IS NULL OR u.role = 'admin';


-- TEST 3: LATERAL JOIN with subquery
SELECT c.name, recent.total, recent.last_order
FROM customers c
LEFT JOIN LATERAL (
    SELECT SUM(o.amount) AS total, MAX(o.created_at) AS last_order
    FROM orders o
    WHERE o.customer_id = c.id AND o.created_at > '2024-01-01'
    ORDER BY o.created_at DESC
    LIMIT 5
) recent ON TRUE
WHERE c.active = TRUE;


-- TEST 4: Window functions with complex frame specs
SELECT
    employee_id,
    department,
    salary,
    AVG(salary) OVER (PARTITION BY department ORDER BY hire_date ROWS BETWEEN 2 PRECEDING AND 1 FOLLOWING) AS moving_avg,
    SUM(salary) OVER (PARTITION BY department ORDER BY hire_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total,
    FIRST_VALUE(salary) OVER (PARTITION BY department ORDER BY salary DESC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS max_sal,
    LAG(salary, 1, 0) OVER (PARTITION BY department ORDER BY hire_date) AS prev_salary,
    RANK() OVER (ORDER BY salary DESC) AS salary_rank
FROM employees;


-- TEST 5: Array syntax with ARRAY constructor, array_agg, unnest
SELECT
    ARRAY[1, 2, 3] AS literal_arr,
    ARRAY[ARRAY[1, 2], ARRAY[3, 4]] AS nested_arr,
    array_agg(DISTINCT t.tag ORDER BY t.tag) AS tags,
    unnest(ARRAY['a', 'b', 'c']) AS letter
FROM tags t
WHERE t.id = ANY(ARRAY[10, 20, 30])
  AND t.category_id != ALL(ARRAY(SELECT id FROM banned_categories));


-- TEST 6: String concatenation with || mixed with CASE and casts
SELECT
    'Hello ' || first_name || ' ' || CASE WHEN title IS NOT NULL THEN title || '. ' ELSE '' END || last_name AS greeting,
    (CASE WHEN age >= 18 THEN 'adult' ELSE 'minor' END) || ' (' || age::TEXT || ')' AS category,
    repeat('-', 40) || E'\n' || description AS decorated
FROM people
WHERE first_name || ' ' || last_name LIKE '%Smith%';


-- TEST 7: Multiple BETWEEN...AND in same WHERE clause (ambiguous AND)
SELECT *
FROM transactions t
WHERE t.amount BETWEEN 100 AND 500
  AND t.created_at BETWEEN '2024-01-01' AND '2024-12-31'
  AND t.fee BETWEEN 0.5 AND 2.5
  AND t.status = 'completed'
  AND t.quantity BETWEEN 1 AND 100;


-- TEST 8: CTE that references another CTE (chained WITH)
WITH active_users AS (
    SELECT id, name, email FROM users WHERE active = TRUE
),
user_orders AS (
    SELECT au.id, au.name, COUNT(o.id) AS order_count, SUM(o.total) AS total_spent
    FROM active_users au
    LEFT JOIN orders o ON o.user_id = au.id
    GROUP BY au.id, au.name
),
ranked AS (
    SELECT uo.*, RANK() OVER (ORDER BY uo.total_spent DESC) AS spending_rank
    FROM user_orders uo
    WHERE uo.order_count > 0
)
SELECT r.name, r.order_count, r.total_spent, r.spending_rank
FROM ranked r
WHERE r.spending_rank <= 10
ORDER BY r.spending_rank;


-- TEST 9: INSERT ... SELECT ... UNION ALL ... ON CONFLICT
INSERT INTO summary_table (category, total_amount, record_count, period)
SELECT category, SUM(amount), COUNT(*), 'Q1' FROM sales WHERE quarter = 1 GROUP BY category
UNION ALL
SELECT category, SUM(amount), COUNT(*), 'Q2' FROM sales WHERE quarter = 2 GROUP BY category
UNION ALL
SELECT category, SUM(amount), COUNT(*), 'Q3' FROM sales WHERE quarter = 3 GROUP BY category
ON CONFLICT (category, period) DO UPDATE SET total_amount = EXCLUDED.total_amount, record_count = EXCLUDED.record_count;


-- TEST 10: UPDATE with multiple JOINs in FROM and subquery in SET
UPDATE inventory i
SET
    quantity = sub.new_qty,
    price = (SELECT AVG(p.price) FROM pricing p WHERE p.sku = i.sku AND p.valid_until > NOW()),
    last_synced = NOW()
FROM warehouses w
JOIN suppliers s ON s.id = w.supplier_id AND s.active = TRUE
LEFT JOIN overrides o ON o.sku = i.sku
WHERE i.warehouse_id = w.id
  AND w.region = 'US'
  AND o.id IS NULL;


-- TEST 11: Aliased subquery in FROM joined to another aliased subquery
SELECT a.user_name, b.total_orders, a.avg_rating
FROM (
    SELECT u.id, u.name AS user_name, AVG(r.score) AS avg_rating
    FROM users u
    LEFT JOIN reviews r ON r.user_id = u.id
    GROUP BY u.id, u.name
) a
JOIN (
    SELECT o.user_id, COUNT(*) AS total_orders, MAX(o.created_at) AS last_order
    FROM orders o
    WHERE o.status != 'cancelled'
    GROUP BY o.user_id
) b ON b.user_id = a.id
WHERE a.avg_rating > 3.5
  AND b.total_orders > 5
ORDER BY b.total_orders DESC;


-- TEST 12: Searched CASE inside COALESCE inside nested function calls
SELECT
    COALESCE(
        CASE
            WHEN u.preferred_name IS NOT NULL THEN u.preferred_name
            WHEN u.first_name IS NOT NULL THEN u.first_name || ' ' || u.last_name
            ELSE 'Unknown'
        END,
        NULLIF(u.username, ''),
        'anonymous'
    ) AS display_name,
    COALESCE(CASE WHEN score >= 90 THEN 'A' WHEN score >= 80 THEN 'B' WHEN score >= 70 THEN 'C' ELSE 'F' END, 'N/A') AS grade
FROM users u;


-- TEST 13: Comments between every clause (inline and standalone)
-- This is a standalone comment before SELECT
SELECT
    -- column group: identifiers
    id,    -- the primary key
    name,  -- user display name
    /* block comment in select list */ email
-- standalone comment before FROM
FROM
    users u  -- aliased table
-- standalone comment before JOIN
LEFT JOIN profiles p  -- the profile join
    ON p.user_id = u.id  -- join condition
-- another standalone before WHERE
WHERE
    -- first condition group
    u.active = TRUE  -- only active users
    -- commented-out condition
    -- AND u.verified = TRUE
    AND p.bio IS NOT NULL
-- final comment
ORDER BY u.name;


-- TEST 14: Dollar-quoted strings and DO blocks
DO $$ BEGIN
    RAISE NOTICE 'Hello from anonymous block';
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'temp_data') THEN
        DROP TABLE temp_data;
    END IF;
END $$;


-- TEST 15: CAST(x AS VARCHAR(255)) vs x::VARCHAR(255) and exotic casts
SELECT
    CAST(price AS NUMERIC(10,2)) AS formatted_price,
    amount::NUMERIC(12,4) AS precise_amount,
    CAST(created_at AS VARCHAR(255)) AS date_str,
    name::VARCHAR(100) AS short_name,
    CAST(data AS JSON)::TEXT AS json_text,
    (metadata ->> 'key')::INTEGER AS key_val,
    CAST(ARRAY[1,2,3] AS INTEGER[]) AS int_arr
FROM products;


-- TEST 16: Empty and near-empty IN lists
SELECT * FROM items WHERE status IN () AND category IN ('A') AND tag IN ('x', 'y') AND priority IN ('low', 'med', 'high', 'critical', 'blocker');


-- TEST 17: Massive chained UNION ALL (5 selects)
SELECT id, name, 'active' AS status FROM users WHERE active = TRUE
UNION ALL
SELECT id, name, 'inactive' FROM users WHERE active = FALSE AND deleted_at IS NULL
UNION ALL
SELECT id, name, 'deleted' FROM users WHERE deleted_at IS NOT NULL
UNION ALL
SELECT id, email AS name, 'pending' FROM pending_users WHERE confirmed = FALSE
UNION ALL
SELECT id, legacy_name, 'legacy' FROM legacy_users WHERE migrated = FALSE
ORDER BY status, name;


-- TEST 18: GROUP BY with ROLLUP, CUBE, and GROUPING SETS
SELECT
    COALESCE(region, '(all regions)') AS region,
    COALESCE(category, '(all categories)') AS category,
    COALESCE(brand, '(all brands)') AS brand,
    SUM(revenue) AS total_revenue,
    COUNT(*) AS cnt,
    GROUPING(region, category, brand) AS grp_level
FROM sales
WHERE year = 2024
GROUP BY GROUPING SETS (
    (region, category, brand),
    (region, category),
    (region),
    ()
)
HAVING SUM(revenue) > 1000
ORDER BY region NULLS FIRST, category NULLS FIRST, brand NULLS FIRST;


-- TEST 19: SELECT with no FROM clause and complex expressions
SELECT
    1 AS one,
    'hello world' AS greeting,
    NOW() AS current_time,
    NOW() + INTERVAL '30 days' AS future_date,
    CASE WHEN 1 = 1 THEN 'yes' ELSE 'no' END AS always_yes,
    GREATEST(1, 2, 3, 4, 5) AS max_val,
    ARRAY(SELECT generate_series(1, 10)) AS series,
    (SELECT COUNT(*) FROM pg_stat_activity) AS active_connections;


-- TEST 20: Nested parenthesized OR groups in WHERE
SELECT *
FROM accounts a
WHERE (a.status = 'active' OR (a.status = 'suspended' AND (a.reason = 'payment' OR a.reason = 'review')))
  AND (a.balance > 0 OR (a.credit_limit > 0 AND (a.type = 'premium' OR (a.type = 'standard' AND a.tenure > 365))))
  AND NOT (a.flagged = TRUE AND (a.flag_reason IN ('fraud', 'abuse', 'spam', 'bot') OR a.risk_score > 90))
  AND EXISTS (SELECT 1 FROM logins l WHERE l.account_id = a.id AND l.login_at > NOW() - INTERVAL '90 days');


-- TEST 21: Standalone comment on own line immediately before semicolon
CREATE TABLE maintenance.protocol_aux AS
  WITH ajuste_ceps AS (
      SELECT * FROM maintenance.cep_a
      UNION ALL
      SELECT * FROM maintenance.cep_b
  )
  SELECT DISTINCT
      ap.postal_code AS new_postal_code,
      p.*
  FROM
      erp.people p
      JOIN ajuste_ceps ap ON
          upper(trim(p.street)) = upper(trim(ap.old_street))
      AND upper(trim(p.city))   = upper(trim(ap.old_city))
      AND REPLACE(upper(p.zip), '-', '') = REPLACE(upper(ap.old_zip), '-', '')
  -- WHERE p.name = 'test value'
  ;


-- TEST 22: CREATE TABLE AS WITH (CTE before SELECT — no blank lines between AS and WITH)
CREATE TABLE maintenance.ajuste_cep_test AS
  WITH src AS (
      SELECT * FROM maintenance.cep_a
      UNION ALL
      SELECT * FROM maintenance.cep_b
  )
  SELECT DISTINCT
      s.cep AS new_postal_code,
      p.*
  FROM erp.people_addresses p
  JOIN src s ON upper(trim(p.street)) = upper(trim(s.street))
  ;


-- TEST 23: FROM (VALUES ...) AS alias(cols) — table constructor with column-list alias
UPDATE t SET a = v.a FROM (VALUES ('x', 1), ('y', 2)) AS v(a, b) WHERE t.id = v.b;


-- TEST 24: Simple CASE (CASE expr WHEN val THEN result) in UPDATE SET clause
UPDATE erp.companies_places cp
SET
    faktura_integration_code = CASE cp.code
        WHEN '04' THEN 'XXXXXXX+Lqt6dfyTICTcPSFypuEvK57O'
        WHEN '05' THEN 'XXXXXXX+nBmPqNp5byt0k+7y'
        ELSE cp.faktura_integration_code END
WHERE
    code IN ('04', '05');


-- TEST 27: ANY(ARRAY[...]) with >3 values expands one per line (= ANY and ILIKE ANY)
SELECT * FROM t
WHERE id = ANY(ARRAY[1, 2, 3, 4, 5])
  AND label ILIKE ANY(ARRAY['alpha', 'beta', 'gamma', 'delta', 'epsilon']);


-- TEST 26: Standalone comments between WHERE AND conditions are preserved
SELECT a, b
FROM t
WHERE a = 1
    -- this condition is commented out:
    --AND b = 2
    AND c = 3
    -- another block
    AND d = 4;


-- TEST 25: CREATE TABLE with column definitions (type alignment, constraints)
--DROP TABLE IF EXISTS legado.phoenix_pedidos;
CREATE TABLE legado.phoenix_pedidos (
    protocolo       BIGINT,
    ano_mes         INTEGER,
    cliente         VARCHAR(200),
    cidade          VARCHAR(100),
    assunto         VARCHAR(500),
    operador        VARCHAR(150),
    anotacao        TEXT,
    data_inclusao   TIMESTAMP,
    data_fechamento VARCHAR(20),
    obs_fechamento  TEXT,
    tecnico         TEXT
);


-- TEST 28: SELECT DISTINCT ON (...) with single and multiple columns
SELECT DISTINCT ON (p.id)
    p.name, p.tx_id, a.created
FROM person p
LEFT JOIN assignments a ON a.created_by = p.id
ORDER BY p.id, a.created DESC;

SELECT DISTINCT ON (a.id, b.category) a.id, b.category, b.total
FROM items a
JOIN categories b ON b.id = a.category_id
ORDER BY a.id, b.category, b.total DESC;


-- TEST 29: Long inlined subquery WHERE breaks AND conditions onto separate lines
SELECT
    *
    , (
        SELECT COUNT(*) FROM erp.people_addresses tmp WHERE tmp.city = aux.cidade AND tmp.neighborhood = aux.bairro_cliente AND tmp.street IN (aux.rua_cliente, aux.somente_rua) AND REGEXP_REPLACE(aux.cep_novo, '[^0-9-]', '', 'g') != REGEXP_REPLACE(tmp.postal_code, '[^0-9-]', '', 'g')
    )
FROM
    maintenance.aux_protocol_1439457_enderecos aux;


-- TEST 30: Structurally invalid SQL is returned unchanged, not mangled
SELECT WHERE FROM 1 WHEN 2;


-- TEST 31: Standalone comment between a CTE's closing paren and the main SELECT
WITH cte AS (
    SELECT 1 AS x
)
-- note about the main query
SELECT x FROM cte;


-- TEST 32: SUBSTRING(str FROM start FOR len) SQL-standard syntax (FROM/FOR are not clause keywords here)
SELECT
    SUBSTRING(vs.name FROM LENGTH(vs.ddd::VARCHAR) + 1) AS telefone
    , SUBSTRING(vs.name FROM 1 FOR 3) AS ddd
    , SUBSTRING(vs.name, 1, 3) AS ddd_commas
FROM legado.voip_sippeers vs;


-- TEST 33: Multiple standalone comments at clause boundaries (select list, ON, WHERE, ORDER BY)
SELECT c.id, c.description
    --, fat.title
    --, tit.title
    --, ccb.financial_operation_id
FROM
    erp.people p
    JOIN erp.contracts c ON
        c.client_id = p.id  -- join condition
-- another standalone before WHERE
WHERE
    -- first condition group
    c.amount > 0  -- only positive amounts
    AND c.status = 1
-- final comment
ORDER BY c.id;


-- TEST 34: Standalone comment between UPDATE SET items is preserved, not dropped
UPDATE erp.users xx
SET
    yy = 1
    -- fill in the real value above
    , modified = now()
    , modified_by = (SELECT id FROM erp.users WHERE login = 'syntesis')
FROM
    maintenance.tmp man
WHERE
    xx.id = man.id;


-- TEST 35: Standalone comment between JOIN...ON and its condition is preserved, not dropped
INSERT INTO erp.companies_modules (
    id,
    company_id
)
SELECT
    id,
    company_id
FROM
    erp.companies c
    JOIN erp.modules m ON
        -- pick the module id to insert
        m.id = 1
WHERE
    c.id = 1;


-- TEST 36: UPDATE's WHERE gets the same leading/trailing comment handling as SELECT's WHERE
UPDATE erp.patrimonies p
SET
    active = TRUE
WHERE
    -- only rows still checked out
    p.deleted = FALSE  -- redundant safety check
    AND p.contract_id IS NULL;


-- TEST 37: Set-returning function call in FROM (previously caused a parser hang inside a CTE)
WITH cte AS (
    SELECT now() AS data FROM generate_series(1, 10)
)
SELECT * FROM cte;

SELECT * FROM generate_series(1, 10) gs;

SELECT * FROM pg_catalog.generate_series(1, 10) gs;

SELECT * FROM foo JOIN generate_series(1, 10) gs ON gs.val = foo.id;

SELECT * FROM unnest(ARRAY[1, 2, 3]) x;


-- TEST 38: = ANY(ARRAY[...]::TYPE[]) cast — previously the cast landed outside ANY(...)
-- and the real closing paren was left unconsumed, corrupting everything after it
SELECT c.id
FROM erp.contracts c
WHERE
    c.id = ANY(ARRAY[1, 2, 3]::BIGINT[])
    AND c.deleted = FALSE
GROUP BY c.id
HAVING count(c.id) > 1;


-- TEST 39: Schema-qualified quoted identifier as CREATE TABLE / INSERT INTO target
-- (previously the schema was duplicated and the quoted identifier left unconsumed)
CREATE TABLE
    maintenance."bkp_protocol_GV-35731_item_integrations" AS
    SELECT 1 AS new_status;

INSERT INTO maintenance."bkp_protocol_GV-35731_item_integrations" (
    a
)
VALUES (1);


-- TEST 40: '*' as multiplication and unary +/- (previously `a*b` was split into two columns
-- with `* AS b`, and a unary `+` was silently dropped)
SELECT a*b, a * -b, -a, +a, - -a, 2*(3+4), COUNT(*)*2, t.*, a%3, a/b
FROM t;


-- TEST 41: Positional parameters ($1) — previously the `$` was silently dropped
SELECT $1, $12::INT, a
FROM t
WHERE b = $2 AND c = ANY($3);


-- TEST 42: Array subscripts and slices — previously each bracket became its own select column
SELECT arr[1], arr[1:3], arr[:3], arr[2:], m[1][2], (f(x))[1], arr[i + 1], x::INT[]
FROM t
WHERE tags[1] = 'a';


-- TEST 43: Row-level locking clauses — previously `for` was swallowed as a table alias
SELECT a FROM t WHERE b = 1 FOR UPDATE;

SELECT a FROM t ORDER BY a LIMIT 1 FOR NO KEY UPDATE OF t SKIP LOCKED;

SELECT a FROM t FOR SHARE OF t NOWAIT;

SELECT * FROM (SELECT a FROM t FOR UPDATE) x WHERE a IN (SELECT b FROM u FOR SHARE);


-- TEST 44: Row constructors and multi-column UPDATE SET (previously `(a, b) = (1, 2)`
-- became `(a, b) = (1)` / `, 2 = )`)
UPDATE t SET (a, b) = (1, 2) WHERE c = 1;

UPDATE t SET (a, b) = (SELECT x, y FROM u WHERE u.id = t.id), c = 3 WHERE c = 1;

SELECT a FROM t WHERE (a, b) = (1, 2) AND (a, b) IN ((1, 2), (3, 4));


-- TEST 45: MATERIALIZED / NOT MATERIALIZED CTEs
WITH x AS MATERIALIZED (SELECT 1 AS a), y AS NOT MATERIALIZED (SELECT 2 AS b), z AS (SELECT 3 AS c)
SELECT * FROM x, y, z;


-- TEST 46: SIMILAR TO / NOT SIMILAR TO
SELECT a FROM t WHERE p SIMILAR TO 'x%' AND q NOT SIMILAR TO 'y%' AND r NOT LIKE 'z%';


-- TEST 47: = ALL / <> ANY with a subquery — previously the whole statement came back unformatted
SELECT a FROM t WHERE y = ALL (SELECT 1) AND z <> ANY (SELECT b FROM u WHERE c = 1);


-- TEST 48: UPDATE ... SET ... RETURNING (previously RETURNING was parsed as another SET target)
UPDATE t SET a = 1, b = 2 WHERE c = 3 RETURNING a, b;

UPDATE t SET a = 1, b = 2 RETURNING a, b;


-- TEST 49: ON CONFLICT DO UPDATE / DO NOTHING in all shapes
INSERT INTO t (a) VALUES (1)
ON CONFLICT (a) DO UPDATE SET a = EXCLUDED.a, b = t.b + 1 WHERE t.a = 1 AND t.b = 2
RETURNING a;

INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO NOTHING;

INSERT INTO t (a) VALUES (1) ON CONFLICT ON CONSTRAINT t_pk DO NOTHING RETURNING a;

INSERT INTO t (a) SELECT 1 ON CONFLICT (a) WHERE b > 0 DO UPDATE SET a = 1;

INSERT INTO t (a) SELECT a FROM u ON CONFLICT (a) DO UPDATE SET a = EXCLUDED.a;


-- TEST 50: Comma-separated FROM tables, DEFAULT keyword, SUBSTRING ... FOR
SELECT SUBSTRING(s FROM 1 FOR 3) FROM t1, t2 x WHERE t1.id = x.id;

UPDATE t SET a = DEFAULT WHERE b = 1;


-- TEST 51: psql meta-commands, transaction control and DDL one-liners
-- (previously `\echo` was glued to a trailing comment, so ROLLBACK ended up inside the comment)
\echo '=== QUERY PLAN ==='
-- note
ROLLBACK;

\set ON_ERROR_STOP on
\echo 'x'

BEGIN;
SELECT 1;
COMMIT;

SELECT a FROM t \gset

ALTER TABLE t ADD COLUMN c INT NOT NULL DEFAULT 0, DROP COLUMN d;

ALTER TABLE t ALTER COLUMN c TYPE BIGINT USING c::BIGINT, ALTER COLUMN d SET DEFAULT 0;

DROP TABLE IF EXISTS a.b, c CASCADE;

TRUNCATE TABLE t RESTART IDENTITY;

GRANT SELECT, INSERT ON TABLE s.t TO PUBLIC, role_a;

COMMENT ON TABLE t IS 'x';

COPY t (a, b) FROM STDIN WITH (format csv);

SET LOCAL work_mem = '64MB';

CREATE UNIQUE INDEX idx ON s.t (a, b) INCLUDE (c) WHERE d IS NOT NULL;

CREATE FUNCTION f(a INT) RETURNS INT AS $$ select a $$ LANGUAGE sql IMMUTABLE;

CREATE TRIGGER tg AFTER INSERT OR UPDATE ON t FOR EACH ROW EXECUTE FUNCTION f();


-- TEST 52: EXPLAIN, CREATE VIEW, MERGE, SELECT INTO, CTAS variants
-- (previously CREATE VIEW became `CREATE TABLE viewv`, MERGE and COPY were corrupted,
-- and EXPLAIN split into two statements)
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM t WHERE a = 1;

EXPLAIN ANALYZE UPDATE t SET a = 1 WHERE b = 2;

CREATE OR REPLACE VIEW v (x, y) AS SELECT a, b FROM t WHERE c = 1;

CREATE MATERIALIZED VIEW mv AS SELECT 1 WITH NO DATA;

CREATE TEMP TABLE x AS SELECT 1;

CREATE TABLE a AS TABLE b;

MERGE INTO t USING s ON t.id = s.id
WHEN MATCHED AND s.del THEN DELETE
WHEN MATCHED THEN UPDATE SET a = s.a, b = s.b
WHEN NOT MATCHED THEN INSERT (id, a) VALUES (s.id, s.a);

SELECT * INTO new_t FROM old_t WHERE a = 1;


-- TEST 53: Word operators and special syntax (previously turned into aliases / extra columns)
SELECT ts AT TIME ZONE 'UTC', ts AT TIME ZONE 'a' AT TIME ZONE 'b', a COLLATE "C"
FROM t
WHERE b ISNULL AND c NOTNULL AND (a, b) OVERLAPS (c, d) AND d BETWEEN SYMMETRIC 1 AND 2
ORDER BY a USING <, b DESC NULLS LAST;

SELECT a IS JSON, b IS NOT JSON ARRAY, (a).b, (a).*, a.b[1].c,
    a::CHARACTER VARYING(10), b::NUMERIC(10, 2), c::TIMESTAMP WITH TIME ZONE
FROM t;

SELECT TRIM(BOTH 'x' FROM s), POSITION('a' IN s), OVERLAY(s PLACING 'x' FROM 1 FOR 2),
    EXTRACT(epoch FROM NOW() - ts), SUBSTRING(s FROM '[0-9]+')
FROM t
WHERE b = ANY (VALUES (1), (2));

SELECT ARRAY_AGG(a ORDER BY b DESC NULLS LAST), SUM(x) OVER (ORDER BY y DESC NULLS FIRST)
FROM t;


-- TEST 54: WINDOW clause, data-modifying CTEs, structured DELETE
SELECT a, SUM(b) OVER w FROM t WINDOW w AS (PARTITION BY a ORDER BY c), w2 AS (ORDER BY d) ORDER BY a;

WITH i AS (INSERT INTO t VALUES (1) RETURNING id) SELECT * FROM i;

WITH moved AS (DELETE FROM a WHERE x = 1 RETURNING *) INSERT INTO b SELECT * FROM moved;

DELETE FROM t USING u, v WHERE t.id = u.id AND u.k = v.k RETURNING t.id;

DELETE FROM t WHERE CURRENT OF c;

SELECT a FROM t GROUP BY ROLLUP (a, b), CUBE (c, d), GROUPING SETS ((e), (f), ());


-- TEST 55: Comments at clause boundaries that used to be dropped
SELECT a
FROM t
-- between the table and the next JOIN
JOIN u p
-- between the joined table and its ON
ON p.id = t.id
WHERE a = 1;

SELECT a
FROM
-- before the first table
t
-- before the comma table
, u;

SELECT
-- before the first select item
a
, b
FROM t;

SELECT a FROM t WHERE a IN (
1, -- one
2 -- two
);

DELETE FROM t
-- why
WHERE a = 1  -- trailing
    AND b = 2;

INSERT INTO t (a, b) VALUES (1, -- one
2);


-- TEST 56: CREATE TABLE comments, LIKE and table options
CREATE TABLE t (
-- the id
id INT,
-- the name
name TEXT, -- trailing
-- uniq
UNIQUE (id) -- u
);

CREATE TABLE t (id INT, name TEXT) PARTITION BY RANGE (id);

CREATE TABLE a (LIKE b INCLUDING ALL);


-- TEST 57: DO block envelope variants
DO LANGUAGE plpgsql $$ begin perform 1; end $$;

DO $$ begin null; end $$ LANGUAGE plpgsql;


-- TEST 58: Semicolon never lands on a comment line; subquery function arguments keep parentheses
UPDATE t SET a = 1 WHERE id IN ()  -- note
;

DELETE FROM t WHERE a = 1 -- c
;

SELECT COALESCE(a, (SELECT 1), 2), COALESCE((SELECT MAX(x) FROM t), 0), ARRAY(SELECT 1) FROM u;


-- TEST 59: IN (VALUES), window refinement, WITH ORDINALITY (previously raw fallback or corrupted)
SELECT a FROM t WHERE b IN (VALUES (1), (2));

SELECT SUM(a) OVER (w ORDER BY b) FROM t WINDOW w AS (PARTITION BY c);

SELECT SUM(a) OVER (PARTITION BY b RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW EXCLUDE TIES) FROM t;

SELECT a FROM t CROSS JOIN LATERAL UNNEST(arr) WITH ORDINALITY u (x, n);


-- TEST 60: Comments between statements and UPDATE without a terminating semicolon
SELECT a
FROM t
WHERE b = 1



-- note one
-- note two
SELECT c
FROM u;

UPDATE t SET a = 1



-- next
SELECT 1;

UPDATE t SET a = 1,
-- b
b = 2
-- before where
WHERE c = 1;


-- TEST 61: A line comment before a closing paren (previously mis-nested the parens and, inside
-- a CTE, made the parser loop forever)
WITH f AS (
    SELECT a
    FROM t
    WHERE d IS FALSE
        AND ((x IS NOT NULL)	-- combo
        OR (y IS NOT NULL)	-- composto
        AND (z = 1) -- nao pai
    )
    GROUP BY a
)
SELECT * FROM f;

SELECT a FROM t WHERE b = (c + 1 -- note
);


-- TEST 62: Number literals, digit-led names, comment adjacency, WITH without a main query
SELECT 1e10, 1.5e-3, 0x1F, 1_000, 2.E+2, .5 FROM t;

SELECT * FROM maintenance.1433617_serra WHERE a = 1;

SELECT a FROM t WHERE b = 1 --x
/* block */ AND c = 2;

WITH cte AS (SELECT 1);

SELECT
'a
b'

-- c1
-- c2
/* x */


-- TEST 63: SELECT without a terminating semicolon followed by another statement; ROWS FROM
SELECT 'x'

-- c

DROP TABLE IF EXISTS m.x;

SELECT TRIM((SELECT 1 LIMIT 1), '/');

SELECT m.ord FROM erp.reports r,
LATERAL ROWS FROM (regexp_matches(r.d, 'x', 'gi'), unnest(a)) WITH ORDINALITY m (tag, ord) WHERE r.id = 1;


-- TEST 64: ${placeholders}, VALUES CTE bodies, comments inside CASE
SELECT a.${col}, ${sch}.t.x FROM erp.${table} t JOIN ${s}.u ON 1 = 1;

WITH r (a) AS (VALUES (0.01), (-0.01)) SELECT * FROM r;

SELECT (CASE
    WHEN a <> '' THEN
        1 -- fixed
    ELSE
        b -- pool
END) AS t FROM x;


-- TEST 65: Statements without a terminating semicolon followed by another statement; WITH in subqueries
SELECT a FROM t ORDER BY a DESC
DROP TABLE m.x;

SELECT b FROM u GROUP BY b
TRUNCATE t;

SELECT 1 WHERE EXISTS (WITH c (x) AS (SELECT 1) SELECT x FROM c) AND a IN (WITH d AS (SELECT 2) SELECT * FROM d);


-- TEST 66: Casts followed by operators (previously `::text LIKE '0%'` swallowed LIKE into the type name)
SELECT a::TEXT LIKE '0%', b::INT IN (1, 2), c::NUMERIC(10, 2) IS NULL, d::TIMESTAMP(3) WITH TIME ZONE,
    i::INT BETWEEN 1 AND 2, j::TEXT || 'x'
FROM t
WHERE a::TEXT ILIKE 'x%' AND b::INT NOT IN (1);
