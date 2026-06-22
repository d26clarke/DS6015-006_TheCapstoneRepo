CREATE USER tree_canopy_db_user WITH PASSWORD 'treeCanopyStudy123!';

GRANT CONNECT ON DATABASE canopy_dashboard TO tree_canopy_db_user;
GRANT USAGE ON SCHEMA public TO tree_canopy_db_user;

-- Grant access to all tables currently existing in the public schema
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tree_canopy_db_user;

-- Grant access to ID generators (sequences) so the user can insert new auto-incrementing items
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tree_canopy_db_user;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tree_canopy_db_user;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE, SELECT ON SEQUENCES TO tree_canopy_db_user;



--GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO tree_canopy_db_user;
--GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO tree_canopy_db_user;

--ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO tree_canopy_db_user;
--ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO tree_canopy_db_user;
