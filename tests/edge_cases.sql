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
