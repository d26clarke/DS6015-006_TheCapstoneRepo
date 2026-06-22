-- Optional: Enable PostGIS if you plan to do proximity/spatial maps later
-- CREATE EXTENSION IF NOT EXISTS postgis; 

-- 1. Create custom ENUM types for dropdown constraints
CREATE TYPE condition_class_enum AS ENUM ('Excellent', 'Good', 'Fair', 'Poor', 'Dead');
CREATE TYPE dieback_pct_enum AS ENUM ('0-10%', '11-25%', '26-50%', '50%+');
CREATE TYPE pest_disease_enum AS ENUM ('None', 'Spotted Lanternfly', 'Emerald Ash Borer', 'Oak Wilt', 'Other');
CREATE TYPE land_use_enum AS ENUM ('Riparian Buffer', 'Urban Park', 'Street Tree', 'Forested Wetland');
CREATE TYPE soil_moisture_enum AS ENUM ('Poorly Drained (Wet)', 'Moderately Drained', 'Well Drained (Dry)');
CREATE TYPE surface_enum AS ENUM ('Soil/Mulch', 'Turf Grass', 'Permeable Pavers', 'Concrete/Asphalt');

-- 2. Create the main inventory table
CREATE TABLE tree_inventory (
    -- Administrative fields
    tree_id VARCHAR(10) PRIMARY KEY,
    tag_number INT UNIQUE,
    
    -- Taxonomy
    scientific_name VARCHAR(255) NOT NULL,
    common_name VARCHAR(255) NOT NULL,
    
    -- Physical measurements (with numeric validations)
    dbh_inches NUMERIC(5,2) NOT NULL CHECK (dbh_inches > 0),
    total_height_ft NUMERIC(5,2) CHECK (total_height_ft > 0),
    canopy_radius_ft NUMERIC(5,2) CHECK (canopy_radius_ft > 0),
    height_to_crown_base_ft NUMERIC(5,2),
    number_of_trunks INT DEFAULT 1 CHECK (number_of_trunks >= 1),
    
    -- Health metrics
    condition_class condition_class_enum,
    dieback_percentage dieback_pct_enum,
    pest_disease_present pest_disease_enum,
    structural_defects TEXT,
    
    -- Location (Using plain text for now to match CSV format, or PostGIS geometry)
    gps_coordinates VARCHAR(50) NOT NULL, 
    -- Alternative PostGIS field (uncomment if PostGIS extension is installed):
    -- geom GEOMETRY(Point, 4326),

    -- Environmental context
    land_use_type land_use_enum,
    soil_moisture_regime soil_moisture_enum,
    surrounding_surface surface_enum,
    
    -- Metadata
    insert_date DATE NOT NULL DEFAULT CURRENT_DATE,
    last_update DATE NOT NULL DEFAULT CURRENT_DATE,
    team_members VARCHAR(255) NOT NULL,
    notes TEXT,

    -- Holds your CloudFront distribution URL string for uploaded photos
    photo_url VARCHAR(2048) DEFAULT NULL, 

    -- Logical business rule validations
    CONSTRAINT chk_height_logic CHECK (height_to_crown_base_ft <= total_height_ft),
    CONSTRAINT chk_date_logic CHECK (last_update >= insert_date),
    CONSTRAINT chk_tree_id_format CHECK (tree_id ~ '^TREE-\d{5}$')
);

