CREATE FOREIGN DATA WRAPPER dummy;
CREATE FOREIGN DATA WRAPPER file HANDLER file_fdw_handler VALIDATOR file_fdw_validator;
CREATE FOREIGN DATA WRAPPER mywrapper NO HANDLER NO VALIDATOR OPTIONS (debug 'true');
CREATE FOREIGN TABLE films (code char(5) NOT NULL, title varchar(40) NOT NULL, did integer NOT NULL, date_prod date, kind varchar(10), len interval hour to minute) SERVER film_server;
CREATE FOREIGN TABLE IF NOT EXISTS ft (a int OPTIONS (column_name 'aa') COLLATE "C" CONSTRAINT c1 NOT NULL CHECK (a > 0) NO INHERIT DEFAULT 1, b text GENERATED ALWAYS AS (a::text) STORED, CONSTRAINT tc CHECK (a < 10) NOT ENFORCED, LIKE src INCLUDING ALL EXCLUDING COMMENTS) INHERITS (p1, p2) SERVER s OPTIONS (table_name 'x');
CREATE FOREIGN TABLE measurement_y2016m07 PARTITION OF measurement FOR VALUES FROM ('2016-07-01') TO ('2016-08-01') SERVER server_07;
CREATE FOREIGN TABLE p2 PARTITION OF p (a WITH OPTIONS NOT NULL, CONSTRAINT k CHECK (a > 0)) DEFAULT SERVER s;
CREATE FUNCTION add(integer, integer) RETURNS integer AS 'select $1 + $2;' LANGUAGE SQL IMMUTABLE RETURNS NULL ON NULL INPUT;
CREATE FUNCTION add(a integer, b integer) RETURNS integer LANGUAGE SQL IMMUTABLE RETURNS NULL ON NULL INPUT RETURN a + b;
CREATE FUNCTION increment(i integer) RETURNS integer AS $$
        BEGIN
                RETURN i + 1;
        END;
$$ LANGUAGE plpgsql;
CREATE FUNCTION dup(in int, out f1 int, out f2 text) AS $$ SELECT $1, CAST($1 AS text) || ' is text' $$ LANGUAGE SQL;
CREATE FUNCTION dup(int) RETURNS TABLE(f1 int, f2 text) AS $$ SELECT $1, CAST($1 AS text) || ' is text' $$ LANGUAGE SQL;
CREATE OR REPLACE FUNCTION check_password(uname TEXT, pass TEXT) RETURNS BOOLEAN AS $$
DECLARE passed BOOLEAN;
BEGIN
        SELECT  (pwd = $2) INTO passed
        FROM    pwds
        WHERE   username = $1;
        RETURN passed;
END;
$$  LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = admin, pg_temp;
CREATE FUNCTION f(a int DEFAULT 1, b text = 'x', VARIADIC c int[] DEFAULT '{}') RETURNS SETOF int WINDOW STABLE NOT LEAKPROOF CALLED ON NULL INPUT EXTERNAL SECURITY INVOKER PARALLEL SAFE COST 10 ROWS 5 SUPPORT s SET work_mem TO '64MB' SET x FROM CURRENT LANGUAGE c AS 'obj_file', 'link_symbol';
CREATE FUNCTION tr(x hstore) RETURNS int TRANSFORM FOR TYPE hstore, FOR TYPE int LANGUAGE plpython3u AS $$ return 1 $$;
CREATE FUNCTION g() RETURNS int LANGUAGE SQL BEGIN ATOMIC SELECT 1; SELECT 2; END;
CREATE FUNCTION h(a int) RETURNS TABLE (x int) LANGUAGE SQL BEGIN ATOMIC INSERT INTO t VALUES (a); SELECT x FROM t WHERE x = a; END;
CREATE GROUP staff;
CREATE GROUP g WITH SUPERUSER CREATEDB NOCREATEROLE NOINHERIT LOGIN REPLICATION BYPASSRLS CONNECTION LIMIT 5 ENCRYPTED PASSWORD 'p' VALID UNTIL '2030-01-01' IN ROLE a, b IN GROUP c ROLE d ADMIN e USER f SYSID 100;
CREATE UNIQUE INDEX title_idx ON films (title);
CREATE UNIQUE INDEX title_idx ON films (title) INCLUDE (director, rating);
CREATE INDEX title_idx ON films (title) WITH (deduplicate_items = off);
CREATE INDEX ON films ((lower(title)));
CREATE INDEX title_idx_german ON films (title COLLATE "de_DE");
CREATE INDEX title_idx_nulls_low ON films (title NULLS FIRST);
CREATE UNIQUE INDEX title_idx ON films (title) WITH (fillfactor = 70);
CREATE INDEX gin_idx ON documents_table USING GIN (locations) WITH (fastupdate = off);
CREATE INDEX code_idx ON films (code) TABLESPACE indexspace;
CREATE INDEX pointloc ON points USING gist (box(location, location));
CREATE INDEX CONCURRENTLY sales_quantity_index ON sales_table (quantity);
CREATE INDEX IF NOT EXISTS i ON ONLY t USING btree (a DESC NULLS LAST, (b + 1) text_pattern_ops, c int4_ops (siglen = 32) ASC) INCLUDE (d) NULLS NOT DISTINCT WITH (fillfactor = 70) TABLESPACE ts WHERE a > 0 AND b IS NOT NULL;
CREATE UNIQUE INDEX CONCURRENTLY ON t (a) NULLS DISTINCT;
CREATE LANGUAGE plsample HANDLER plsample_call_handler;
CREATE OR REPLACE TRUSTED PROCEDURAL LANGUAGE plx HANDLER h INLINE i VALIDATOR v;
CREATE LANGUAGE plpgsql;
CREATE MATERIALIZED VIEW mymatview AS SELECT * FROM mytab;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv (a, b) USING heap WITH (fillfactor = 70) TABLESPACE ts AS SELECT x, y FROM t WITH NO DATA;
CREATE MATERIALIZED VIEW mv2 AS WITH c AS (SELECT 1 AS a) SELECT a FROM c WITH DATA;
CREATE OPERATOR === (LEFTARG = box, RIGHTARG = box, FUNCTION = area_equal_function, COMMUTATOR = ===, NEGATOR = !==, RESTRICT = area_restriction_function, JOIN = area_join_function, HASHES, MERGES);
CREATE OPERATOR - (RIGHTARG = int, PROCEDURE = int4um);
CREATE OPERATOR CLASS gist__int_ops DEFAULT FOR TYPE _int4 USING gist AS
        OPERATOR        3       &&,
        OPERATOR        6       = (anyarray, anyarray),
        OPERATOR        7       @>,
        OPERATOR        8       <@,
        OPERATOR        20      @@ (_int4, query_int),
        FUNCTION        1       g_int_consistent (internal, _int4, smallint, oid, internal),
        FUNCTION        2       g_int_union (internal, internal),
        FUNCTION        3       g_int_compress (internal),
        FUNCTION        4       g_int_decompress (internal),
        FUNCTION        5       g_int_penalty (internal, internal, internal),
        FUNCTION        6       g_int_picksplit (internal, internal),
        FUNCTION        7       g_int_same (_int4, _int4, internal);
CREATE OPERATOR CLASS c FOR TYPE point USING gist FAMILY f AS OPERATOR 15 <-> (point, point) FOR ORDER BY float_ops, OPERATOR 1 << FOR SEARCH, FUNCTION 1 (point, point) f(internal), STORAGE box;
CREATE OPERATOR FAMILY integer_ops USING btree;
CREATE POLICY account_managers ON accounts TO managers USING (manager = current_user);
CREATE POLICY user_mod ON passwd FOR UPDATE USING (current_user = user_name) WITH CHECK (current_user = user_name AND shell IN ('/bin/bash', '/bin/sh'));
CREATE POLICY p ON t AS RESTRICTIVE FOR ALL TO PUBLIC, CURRENT_USER, SESSION_USER USING (true);
CREATE POLICY p2 ON t AS PERMISSIVE FOR SELECT USING (a > 0);
CREATE POLICY p3 ON t FOR INSERT WITH CHECK (b < 10);
CREATE POLICY p4 ON t FOR DELETE TO CURRENT_ROLE USING (owner = current_user);
CREATE PROCEDURE insert_data(a integer, b integer) LANGUAGE SQL AS $$
INSERT INTO tbl VALUES (a);
INSERT INTO tbl VALUES (b);
$$;
CREATE PROCEDURE insert_data2(a integer, b integer) LANGUAGE SQL BEGIN ATOMIC INSERT INTO tbl VALUES (a); INSERT INTO tbl VALUES (b); END;
CREATE OR REPLACE PROCEDURE p(INOUT x int DEFAULT 0, OUT y text) TRANSFORM FOR TYPE hstore EXTERNAL SECURITY DEFINER SET search_path FROM CURRENT LANGUAGE plpgsql AS $$ BEGIN y := 'a'; END $$;
CREATE PUBLICATION mypublication FOR TABLE users, departments;
CREATE PUBLICATION active_departments FOR TABLE departments WHERE (active IS TRUE);
CREATE PUBLICATION alltables FOR ALL TABLES;
CREATE PUBLICATION insert_only FOR TABLE mydata WITH (publish = 'insert');
CREATE PUBLICATION production_publication FOR TABLE users, departments, TABLES IN SCHEMA production;
CREATE PUBLICATION sales_publication FOR TABLES IN SCHEMA marketing, sales;
CREATE PUBLICATION users_filtered FOR TABLE users (user_id, firstname);
CREATE PUBLICATION p FOR TABLE ONLY t (a, b) WHERE (a > 0), TABLES IN SCHEMA CURRENT_SCHEMA WITH (publish_via_partition_root = true, publish_generated_columns = stored);
CREATE PUBLICATION empty;
CREATE ROLE jonathan LOGIN;
CREATE USER davide WITH PASSWORD 'jw8s0F4';
CREATE ROLE miriam WITH LOGIN PASSWORD 'jw8s0F4' VALID UNTIL '2005-01-01';
CREATE ROLE admin WITH CREATEDB CREATEROLE;
CREATE ROLE r WITH NOSUPERUSER NOCREATEDB NOLOGIN NOREPLICATION NOBYPASSRLS PASSWORD NULL IN ROLE a ROLE b ADMIN c SYSID 5;
CREATE RULE "_RETURN" AS ON SELECT TO t1 DO INSTEAD SELECT * FROM t2;
CREATE RULE notify_me AS ON UPDATE TO mytable DO ALSO NOTIFY mytable;
CREATE OR REPLACE RULE r AS ON INSERT TO t WHERE NEW.a > 0 DO INSTEAD NOTHING;
CREATE RULE r2 AS ON DELETE TO t DO (DELETE FROM log WHERE id = OLD.id; INSERT INTO audit VALUES (OLD.id));
CREATE RULE r3 AS ON UPDATE TO t DO INSTEAD UPDATE t2 SET a = NEW.a WHERE id = OLD.id;
CREATE SCHEMA myschema;
CREATE SCHEMA AUTHORIZATION joe;
CREATE SCHEMA IF NOT EXISTS test AUTHORIZATION joe;
CREATE SCHEMA IF NOT EXISTS AUTHORIZATION CURRENT_USER;
CREATE SCHEMA hollywood
    CREATE TABLE films (title text, release date, awards text[])
    CREATE VIEW winners AS
        SELECT title, release FROM films WHERE awards IS NOT NULL;
CREATE SCHEMA s CREATE SEQUENCE sq CREATE INDEX i ON t (a) CREATE TRIGGER tr AFTER INSERT ON t FOR EACH ROW EXECUTE FUNCTION f() GRANT SELECT ON t TO PUBLIC;
CREATE SEQUENCE serial START 101;
CREATE TEMPORARY SEQUENCE IF NOT EXISTS s AS smallint INCREMENT BY 1 MINVALUE 1 MAXVALUE 100 CYCLE START WITH 1 CACHE 1 OWNED BY t.c;
CREATE UNLOGGED SEQUENCE s2 INCREMENT -1 NO MINVALUE NO MAXVALUE NO CYCLE OWNED BY NONE;
CREATE TEMP SEQUENCE s3;
CREATE SERVER myserver FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host 'foo', dbname 'foodb', port '5432');
CREATE SERVER IF NOT EXISTS s TYPE 'oracle' VERSION '19' FOREIGN DATA WRAPPER w;
CREATE STATISTICS s1 (dependencies) ON a, b FROM t1;
CREATE STATISTICS m1 (mcv) ON a, b FROM t2;
CREATE STATISTICS s3 (ndistinct, dependencies, mcv) ON date_trunc('month', a), date_trunc('day', a) FROM t3;
CREATE STATISTICS IF NOT EXISTS s4 ON (a + b) FROM t;
CREATE STATISTICS ON a, (b * 2) FROM t;
CREATE SUBSCRIPTION mysub CONNECTION 'host=192.168.1.50 port=5432 user=foo dbname=foodb' PUBLICATION mypublication, insert_only;
CREATE SUBSCRIPTION mysub2 CONNECTION 'x' PUBLICATION p WITH (enabled = false, create_slot, slot_name = 'mysub', copy_data = true, streaming = parallel, two_phase = on, failover = true, origin = none);
CREATE TABLE films (
    code        char(5) CONSTRAINT firstkey PRIMARY KEY,
    title       varchar(40) NOT NULL,
    did         integer NOT NULL,
    date_prod   date,
    kind        varchar(10),
    len         interval hour to minute
);
CREATE TABLE distributors (
     did    integer PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
     name   varchar(40) NOT NULL CHECK (name <> '')
);
CREATE TABLE array_int (vector  int[][]);
CREATE TABLE films2 (
    code        char(5),
    title       varchar(40),
    did         integer,
    date_prod   date,
    kind        varchar(10),
    len         interval hour to minute,
    CONSTRAINT code_title UNIQUE(code,title)
);
CREATE TABLE distributors2 (
    did     integer CHECK (did > 100),
    name    varchar(40),
    CONSTRAINT con1 CHECK (did > 100 AND name <> '')
);
CREATE TABLE films3 (
    code        char(5),
    title       varchar(40),
    PRIMARY KEY(code,title)
);
CREATE TABLE distributors3 (
    name      varchar(40) DEFAULT 'Luso Films',
    did       integer DEFAULT nextval('distributors_serial'),
    modtime   timestamp DEFAULT current_timestamp
);
CREATE TABLE distributors4 (
    did     integer,
    name    varchar(40)
)
WITH (fillfactor=70);
CREATE TABLE circles (
    c circle,
    EXCLUDE USING gist (c WITH &&)
);
CREATE TABLE cinemas (
        id serial,
        name text,
        location text
) TABLESPACE diskvol1;
CREATE TYPE employee_type AS (name text, salary numeric);
CREATE TABLE employees OF employee_type (
    PRIMARY KEY (name),
    salary WITH OPTIONS DEFAULT 1000
);
CREATE TABLE measurement (
    logdate         date not null,
    peaktemp        int,
    unitsales       int
) PARTITION BY RANGE (logdate);
CREATE TABLE measurement_year_month (
    logdate         date not null,
    peaktemp        int,
    unitsales       int
) PARTITION BY RANGE (EXTRACT(YEAR FROM logdate), EXTRACT(MONTH FROM logdate));
CREATE TABLE cities (
    city_id      bigserial not null,
    name         text not null,
    population   bigint
) PARTITION BY LIST (left(lower(name), 1));
CREATE TABLE orders (
    order_id     bigint not null,
    cust_id      bigint not null,
    status       text
) PARTITION BY HASH (order_id);
CREATE TABLE measurement_y2016m07
    PARTITION OF measurement (
    unitsales DEFAULT 0
) FOR VALUES FROM ('2016-07-01') TO ('2016-08-01');
CREATE TABLE measurement_ym_older
    PARTITION OF measurement_year_month
    FOR VALUES FROM (MINVALUE, MINVALUE) TO (2016, 11);
CREATE TABLE cities_ab
    PARTITION OF cities (
    CONSTRAINT city_id_nonzero CHECK (city_id != 0)
) FOR VALUES IN ('a', 'b') PARTITION BY RANGE (population);
CREATE GLOBAL TEMPORARY TABLE IF NOT EXISTS t (
    a int STORAGE EXTERNAL COMPRESSION lz4 COLLATE "C" CONSTRAINT nn NOT NULL NO INHERIT,
    b int NULL,
    c int GENERATED ALWAYS AS (a * 2) VIRTUAL,
    d int GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1),
    e text UNIQUE NULLS NOT DISTINCT WITH (fillfactor = 70) USING INDEX TABLESPACE ts,
    f int REFERENCES other (id) MATCH FULL ON DELETE SET NULL ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED NOT ENFORCED,
    g int CHECK (g > 0) NO INHERIT ENFORCED,
    valid tstzrange,
    CONSTRAINT pk PRIMARY KEY (a, valid WITHOUT OVERLAPS),
    CONSTRAINT fk FOREIGN KEY (a, PERIOD valid) REFERENCES p (a, PERIOD valid) ON DELETE NO ACTION,
    CONSTRAINT ex EXCLUDE USING gist (b WITH =, (c + 1) WITH <>) WHERE (b > 0),
    NOT NULL b NO INHERIT,
    LIKE src INCLUDING DEFAULTS INCLUDING CONSTRAINTS EXCLUDING INDEXES INCLUDING STORAGE INCLUDING COMPRESSION INCLUDING IDENTITY INCLUDING GENERATED INCLUDING STATISTICS
) INHERITS (base) PARTITION BY RANGE (a COLLATE "C" int4_ops) USING heap WITH (fillfactor = 80) ON COMMIT PRESERVE ROWS TABLESPACE ts;
CREATE LOCAL TEMP TABLE t2 (a int) ON COMMIT DELETE ROWS;
CREATE TEMP TABLE t3 (a int) ON COMMIT DROP;
CREATE UNLOGGED TABLE t4 (a int) WITHOUT OIDS;
CREATE TABLE t5 ();
CREATE TABLE t6 (LIKE t5);
CREATE TABLE films_recent AS SELECT * FROM films WHERE date_prod >= '2002-01-01';
CREATE TABLE films2 AS TABLE films;
CREATE TEMP TABLE films_recent2 ON COMMIT DROP AS EXECUTE recentfilms('2002-01-01');
CREATE UNLOGGED TABLE IF NOT EXISTS ctas (a, b) USING heap WITH (fillfactor = 70) TABLESPACE ts AS SELECT 1, 2 WITH NO DATA;
CREATE TABLE ctas2 AS VALUES (1, 'a'), (2, 'b');
CREATE TABLE ctas3 WITHOUT OIDS AS SELECT 1 AS x;
CREATE TABLESPACE dbspace LOCATION '/data/dbs';
CREATE TABLESPACE indexspace OWNER genevieve LOCATION '/data/indexes' WITH (random_page_cost = 1.1);
CREATE TEXT SEARCH CONFIGURATION my_search_config (copy = english);
CREATE TEXT SEARCH CONFIGURATION pg (PARSER = default);
CREATE TEXT SEARCH DICTIONARY my_russian (template = snowball, language = russian, stopwords = myrussian);
CREATE TEXT SEARCH PARSER myparser (START = prsd_start, GETTOKEN = prsd_nexttoken, END = prsd_end, LEXTYPES = prsd_lextype, HEADLINE = prsd_headline);
CREATE TEXT SEARCH TEMPLATE mytemplate (INIT = dsimple_init, LEXIZE = dsimple_lexize);
CREATE TRANSFORM FOR hstore LANGUAGE plpython3u (FROM SQL WITH FUNCTION hstore_to_plpython(internal), TO SQL WITH FUNCTION plpython_to_hstore(internal));
CREATE OR REPLACE TRANSFORM FOR int LANGUAGE plperl (FROM SQL WITH FUNCTION f1, TO SQL WITH FUNCTION f2);
CREATE TRIGGER check_update BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION check_account_update();
CREATE OR REPLACE TRIGGER check_update BEFORE UPDATE OF balance ON accounts FOR EACH ROW EXECUTE FUNCTION check_account_update();
CREATE TRIGGER check_update2 BEFORE UPDATE ON accounts FOR EACH ROW WHEN (OLD.balance IS DISTINCT FROM NEW.balance) EXECUTE FUNCTION check_account_update();
CREATE TRIGGER log_update AFTER UPDATE ON accounts FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION log_account_update();
CREATE TRIGGER view_insert INSTEAD OF INSERT ON my_view FOR EACH ROW EXECUTE FUNCTION view_insert_row();
CREATE TRIGGER transfer_insert AFTER INSERT ON transfer REFERENCING NEW TABLE AS inserted FOR EACH STATEMENT EXECUTE FUNCTION check_transfer_balances_to_zero();
CREATE TRIGGER paired_items_update AFTER UPDATE ON paired_items REFERENCING NEW TABLE AS newtab OLD TABLE AS oldtab FOR EACH ROW EXECUTE FUNCTION check_matching_pairs();
CREATE CONSTRAINT TRIGGER ct AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON t FROM other DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE PROCEDURE f('a', 1);
CREATE TRIGGER t2 AFTER TRUNCATE ON t FOR STATEMENT EXECUTE FUNCTION f();
CREATE TYPE compfoo AS (f1 int, f2 text COLLATE "C");
CREATE TYPE bug_status AS ENUM ('new', 'open', 'closed');
CREATE TYPE empty_enum AS ENUM ();
CREATE TYPE floatrange AS RANGE (subtype = float8, subtype_diff = float8mi);
CREATE TYPE r2 AS RANGE (SUBTYPE = int4, SUBTYPE_OPCLASS = int4_ops, COLLATION = "C", CANONICAL = c, SUBTYPE_DIFF = d, MULTIRANGE_TYPE_NAME = r2_multi);
CREATE TYPE box (INTERNALLENGTH = 16, INPUT = my_box_in_function, OUTPUT = my_box_out_function);
CREATE TYPE bigobj (INPUT = lo_filein, OUTPUT = lo_fileout, INTERNALLENGTH = VARIABLE, RECEIVE = r, SEND = s, TYPMOD_IN = ti, TYPMOD_OUT = tout, ANALYZE = a, SUBSCRIPT = sub, PASSEDBYVALUE, ALIGNMENT = double, STORAGE = plain, LIKE = int4, CATEGORY = 'U', PREFERRED = false, DEFAULT = '0', ELEMENT = int4, DELIMITER = ',', COLLATABLE = true);
CREATE TYPE shell_type;
CREATE USER MAPPING FOR bob SERVER foo OPTIONS (user 'bob', password 'secret');
CREATE USER MAPPING IF NOT EXISTS FOR PUBLIC SERVER foo;
CREATE USER MAPPING FOR USER SERVER foo OPTIONS (user 'x');
CREATE USER MAPPING FOR CURRENT_ROLE SERVER foo;
CREATE VIEW vista AS SELECT 'Hello World';
CREATE VIEW vista2 AS SELECT text 'Hello World' AS hello;
CREATE VIEW comedies AS SELECT * FROM films WHERE kind = 'Comedy';
CREATE VIEW universal_comedies AS SELECT * FROM comedies WHERE classification = 'U' WITH LOCAL CHECK OPTION;
CREATE VIEW pg_comedies AS SELECT * FROM comedies WHERE classification = 'PG' WITH CASCADED CHECK OPTION;
CREATE VIEW comedies2 AS SELECT f.*, country_code_to_name(f.country_code) AS country, (SELECT avg(r.rating) FROM user_ratings r WHERE r.film_id = f.id) AS avg_rating FROM films f WHERE f.kind = 'Comedy';
CREATE RECURSIVE VIEW public.nums_1_100 (n) AS VALUES (1) UNION ALL SELECT n+1 FROM nums_1_100 WHERE n < 100;
CREATE OR REPLACE TEMP VIEW v (a, b) WITH (security_barrier = true, check_option = cascaded, security_invoker) AS SELECT 1, 2 WITH CHECK OPTION;
