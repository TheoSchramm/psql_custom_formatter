-- Sample script for testing
-- Date: Mar 10, 2026
-- Time: 5:54:29 PM



-- Select items with computed column
SELECT
    CASE a
        WHEN 1 THEN 'one'
        WHEN 2 THEN 'two'
        ELSE 'three'
        END AS a_num
    -- A value
    , b AS b_num				-- B value
FROM
    table1 t
WHERE
    a::NUMBER > 100
    AND b BETWEEN 12 AND 45;



SELECT
    t.*
    , j1.x
    , j2.y
FROM
    table1 t
    JOIN jt1 j1 ON 
        j1.a = t.a
    LEFT OUTER JOIN jt2 j2 ON
        j2.a = t.a
        AND j2.b = j1.b
WHERE
    t.xxx IS NOT NULL;



DELETE FROM
    table1
WHERE
    a = 1;



UPDATE
    table1
SET
    a = 2
WHERE
    a = 1
    SELECT
        table1.id
        , table2.number
        , SUM(table1.amount)
    FROM
        table1
        INNER JOIN table2 ON 
            table1.id = table2.table1_id
    WHERE
        table1.id IN (
            SELECT
                table1_id
            FROM
                table3
            WHERE
                table3.name = 'Foo Bar' AND table3.type = 'unknown_type'
        )
    GROUP BY
        table1.id
        , table2.number
    ORDER BY
        table1.id;