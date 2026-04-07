-- Sample script for testing
-- Date: Mar 11, 2026
-- Time: 10:17:37 AM


CREATE TABLE
    public.bkp_ticket_001_jobs AS
SELECT
    j.*
FROM
    public.jobs j
    JOIN public.job_events je ON
        je.job_id = j.id
WHERE
    deleted IS false
    AND je.ticket IN (90001 , 90002 , 90003 , 90004 , 90005 , 90006 , 90007 , 90008 , 90009 , 90010 , 90011)


UPDATE
    public.jobs xx
SET
	deleted = true
    -- ADD COLUMNS TO RESTORE FROM BACKUP ABOVE
    , modified = now()
    , modified_by = u.id
FROM
    public.bkp_ticket_001_jobs bkp
    JOIN public.users u ON u.login = 'admin'
WHERE
    xx.id = bkp.id;

SELECT 'Hello,

As requested, the maintenance was performed in the test environment. Please validate and let us know if you find any discrepancies so we can make the necessary corrections.

Backup table created:
public.bkp_ticket_001_jobs

Best regards,

Support Team';



