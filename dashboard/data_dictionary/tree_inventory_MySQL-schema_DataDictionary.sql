CREATE TABLE tree_inventory (
    -- Administrative fields
    tree_id VARCHAR(10) PRIMARY KEY,
    tag_number INT UNIQUE,
    
    -- Taxonomy
    scientific_name VARCHAR(255) NOT NULL,
    common_name VARCHAR(255) NOT NULL,
    
    -- Physical measurements (with numeric validations)
    dbh_inches DECIMAL(5,2) NOT NULL CHECK (dbh_inches > 0),
    total_height_ft DECIMAL(5,2) CHECK (total_height_ft > 0),
    canopy_radius_ft DECIMAL(5,2) CHECK (canopy_radius_ft > 0),
    height_to_crown_base_ft DECIMAL(5,2),
    number_of_trunks INT DEFAULT 1 CHECK (number_of_trunks >= 1),
    
    -- Health metrics
    condition_class ENUM('Excellent', 'Good', 'Fair', 'Poor', 'Dead'),
    dieback_percentage ENUM('0-10%', '11-25%', '26-50%', '50%+'),
    pest_disease_present ENUM('None', 'Spotted Lanternfly', 'Emerald Ash Borer', 'Oak Wilt', 'Other'),
    structural_defects TEXT,
    
    -- Location 
    gps_coordinates VARCHAR(50) NOT NULL, 

    -- Environmental context
    land_use_type ENUM('Riparian Buffer', 'Urban Park', 'Street Tree', 'Forested Wetland'),
    soil_moisture_regime ENUM('Poorly Drained (Wet)', 'Moderately Drained', 'Well Drained (Dry)'),
    surrounding_surface ENUM('Soil/Mulch', 'Turf Grass', 'Permeable Pavers', 'Concrete/Asphalt'),
    
    -- Metadata
    insert_date DATE NOT NULL,
    last_update DATE NOT NULL,
    team_members VARCHAR(255) NOT NULL,
    notes TEXT,

    -- Holds your CloudFront distribution URL string for uploaded photos
    photo_url VARCHAR(2048) DEFAULT NULL, 

    -- Logical business rule validations
    CONSTRAINT chk_height_logic CHECK (height_to_crown_base_ft <= total_height_ft),
    CONSTRAINT chk_date_logic CHECK (last_update >= insert_date),
    CONSTRAINT chk_tree_id_format CHECK (tree_id REGEXP '^TREE-[0-9]{5}$')
);

