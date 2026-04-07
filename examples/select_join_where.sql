-- Sample script for testing
-- Date: Mar 10, 2026
-- Time: 5:54:29 PM

-- Select all active line item details
SELECT
    t1.ref_code AS ref_num
    , t2.label AS display_name
    , t3.description AS item_desc
    , t3.unit_price AS price
    , t3.*
FROM
    public.line_items t3
    JOIN public.records t1 ON
        t1.id = t3.record_id
    JOIN public.contacts t2 ON
        t2.id = t1.contact_id
WHERE
    --- t3.PARENT_ITEM_ID = t3.id
    AND t1.v_status NOT IN ('Cancelled' , 'Suspended') -- active records
    AND t1.deleted IS FALSE
    AND t3.deleted IS FALSE
    AND t1.ref_code = '55001'
ORDER BY
    ref_num
---- end of query
-- Create a secondary address from the primary address for contacts that lack one.
INSERT INTO public.addresses_backup (
    id
    , contact_id
    , "type"
    , street_type
    , street
    , "number"
    , complement
    , district
    , city
    , city_code
    , "state"
    , country
    , country_code
    , reference
    , latitude
    , longitude
    , category
    , postal_code
    , created
    , modified
    , created_by
    , modified_by
    , deleted
    , ext_code
    , class_id
    , sync_flag
)
SELECT
    COALESCE(MAX(a.id), 0) + 1 AS id,--not required
    a.contact_id,
    2 AS "type",
    a.street_type,
    a.street,
    a."number",
    a.complement,
    a.district,
    a.city,
    a.city_code,
    a."state",
    a.country,
    a.country_code,
    a.reference,
    a.latitude,
    a.longitude,
    a.category,
    a.postal_code,
    now() AS created,
    now() AS modified,--not required
    1 AS created_by,
    1 AS modified_by,--not required
    false AS deleted,--not required
    a.ext_code,
    a.class_id,
    a.sync_flag
FROM public.addresses_backup a
JOIN public.contacts_backup c ON c.id = a.contact_id
WHERE
    a."type" = 1
    AND c.deleted IS FALSE
    AND NOT EXISTS (
        SELECT 1
        FROM public.addresses_backup a2
        WHERE
            a2.contact_id = a.contact_id
            AND a2."type" = 2
    )
GROUP BY
    a.contact_id,
    a.street_type,
    a.street,
    a."number",
    a.complement,
    a.district,
    a.city,
    a.city_code,
    a."state",
    a.country,
    a.country_code,
    a.reference,
    a.latitude,
    a.longitude,
    a.category,
    a.postal_code,
    a.ext_code,
    a.class_id,
    a.sync_flag;
