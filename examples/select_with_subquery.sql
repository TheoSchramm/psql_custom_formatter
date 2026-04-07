-- Sample script for testing
-- Date: Mar 10, 2026
-- Time: 5:54:29 PM



-- Select all contact tokens
SELECT
    c.token
    , *
FROM
    public.contacts c
WHERE
    deleted IS FALSE
    AND c.ref_code = '99887766555'

-- Select count
SELECT
    COUNT(*)
    FROM
        public.contacts c
    WHERE
        c.deleted IS FALSE AND c.token::TEXT ilike '%00000000%'
