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
            table3.name = 'Foo Bar' 
            AND table3.type = 'unknown_type'
    )
GROUP BY
    table1.id
    , table2.number
ORDER BY
    table1.id;