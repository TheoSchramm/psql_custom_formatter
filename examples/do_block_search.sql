DO $$
  DECLARE
      search_value TEXT := 'user@example.com';
      record_id    INTEGER := 99999;

      rec RECORD;
      col_name TEXT;
      col_value TEXT;
      found_any BOOLEAN := FALSE;
  BEGIN
      FOR rec IN
          SELECT
              'records' AS _src_table, r.*
          FROM
              PUBLIC.records r
              JOIN public.contacts c ON c.id = r.CONTACT_ID
              JOIN public.LINE_ITEMS LI ON li.RECORD_ID = r.id
              JOIN public.PAYMENTS PM ON pm.LINE_ITEM_ID = li.id
          WHERE
              r.DELETED IS FALSE
              AND c.id = record_id
      LOOP
          FOR col_name, col_value IN
              SELECT key, value FROM jsonb_each_text(to_jsonb(rec))
              WHERE key != '_src_table'
          LOOP
              IF col_value = search_value THEN
                  RAISE NOTICE 'Found "%" in table: %, column: %', search_value,
  rec._src_table, col_name;
                  found_any := TRUE;
              END IF;
          END LOOP;
      END LOOP;

      FOR rec IN
          SELECT
              'contacts' AS _src_table, c.*
          FROM
              PUBLIC.records r
              JOIN public.contacts c ON c.id = r.CONTACT_ID
              JOIN public.LINE_ITEMS LI ON li.RECORD_ID = r.id
              JOIN public.PAYMENTS PM ON pm.LINE_ITEM_ID = li.id
          WHERE
              r.DELETED IS FALSE
              AND c.id = record_id
      LOOP
          FOR col_name, col_value IN
              SELECT key, value FROM jsonb_each_text(to_jsonb(rec))
              WHERE key != '_src_table'
          LOOP
              IF col_value = search_value THEN
                  RAISE NOTICE 'Found "%" in table: %, column: %', search_value,
  rec._src_table, col_name;
                  found_any := TRUE;
              END IF;
          END LOOP;
      END LOOP;

      FOR rec IN
          SELECT
              'line_items' AS _src_table, li.*
          FROM
              PUBLIC.records r
              JOIN public.contacts c ON c.id = r.CONTACT_ID
              JOIN public.LINE_ITEMS LI ON li.RECORD_ID = r.id
              JOIN public.PAYMENTS PM ON pm.LINE_ITEM_ID = li.id
          WHERE
              r.DELETED IS FALSE
              AND c.id = record_id
      LOOP
          FOR col_name, col_value IN
              SELECT key, value FROM jsonb_each_text(to_jsonb(rec))
              WHERE key != '_src_table'
          LOOP
              IF col_value = search_value THEN
                  RAISE NOTICE 'Found "%" in table: %, column: %', search_value,
  rec._src_table, col_name;
                  found_any := TRUE;
              END IF;
          END LOOP;
      END LOOP;

      FOR rec IN
          SELECT
              'payments' AS _src_table, pm.*
          FROM
              PUBLIC.records r
              JOIN public.contacts c ON c.id = r.CONTACT_ID
              JOIN public.LINE_ITEMS LI ON li.RECORD_ID = r.id
              JOIN public.PAYMENTS PM ON pm.LINE_ITEM_ID = li.id
          WHERE
              r.DELETED IS FALSE
              AND c.id = record_id
      LOOP
          FOR col_name, col_value IN
              SELECT key, value FROM jsonb_each_text(to_jsonb(rec))
              WHERE key != '_src_table'
          LOOP
              IF col_value = search_value THEN
                  RAISE NOTICE 'Found "%" in table: %, column: %', search_value,
  rec._src_table, col_name;
                  found_any := TRUE;
              END IF;
          END LOOP;
      END LOOP;

      IF NOT found_any THEN
          RAISE NOTICE 'Value "%" was not found in any column.', search_value;
      END IF;
  END $$;
