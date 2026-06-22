import json
import os
import urllib.parse
import psycopg2
from psycopg2.extras import RealDictCursor

# Database configurations loaded via environment variables with defaults
DB_HOST = os.environ.get("DB_HOST", "10.0.2.176")
DB_NAME = os.environ.get("DB_NAME", "canopy_dashboard")
DB_USER = os.environ.get("DB_USER", "postgres")
RAW_PASSWORD = os.environ.get("DB_PASSWORD", "uvaTr33C@n0Py!")

# Safely escape special password characters
DB_PASSWORD = urllib.parse.quote_plus(RAW_PASSWORD)

def get_db_connection():
    """Helper connection block for database operations."""
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=5
    )

def lambda_handler(event: dict, context: dict) -> dict:
    # 1. Determine Payload Format and extract the HTTP Method
    # Works for both HTTP API Payload Format 1.0 and 2.0
    method = "GET"
    if "requestContext" in event and "http" in event["requestContext"]:
        method = event["requestContext"]["http"]["method"]  # Format 2.0
    elif "httpMethod" in event:
        method = event["httpMethod"]  # Format 1.0

    # 2. Extract Tree ID from route path parameters if present
    path_parameters = event.get("pathParameters") or {}
    tree_id = path_parameters.get("treeId") or path_parameters.get("proxy")

    # If it's a catch-all proxy string (like 'api/trees/TREE-00001'), isolate the final block
    if tree_id and "/" in tree_id:
        tree_id = tree_id.split("/")[-1]

    # Shared return headers structure
    response_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
    }

    try:
        conn = get_db_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            
            # 🔍 READ Operations (GET)
            if method == "GET":
                if tree_id:
                    # Fetch single record
                    cur.execute("SELECT * FROM tree_inventory WHERE tree_id = %s;", (tree_id,))
                    row = cur.fetchone()
                    if not row:
                        return {"statusCode": 404, "headers": response_headers, "body": json.dumps({"error": f"Record {tree_id} not found."})}
                    return {"statusCode": 200, "headers": response_headers, "body": json.dumps(row, default=str)}
                else:
                    # Fetch multi-row registry index
                    cur.execute("SELECT * FROM tree_inventory ORDER BY tree_id DESC LIMIT 100;")
                    rows = cur.fetchall()
                    return {"statusCode": 200, "headers": response_headers, "body": json.dumps(rows, default=str)}

            # ➕ CREATE Operation (POST)
            elif method == "POST":
                if not event.get("body"):
                    return {"statusCode": 400, "headers": response_headers, "body": json.dumps({"error": "Missing payload body."})}
                
                body = json.loads(event["body"])
                
                query = """
                    INSERT INTO tree_inventory (
                        tree_id, tag_number, scientific_name, common_name, dbh_inches, 
                        total_height_ft, canopy_radius_ft, height_to_crown_base_ft, number_of_trunks,
                        condition_class, dieback_percentage, pest_disease_present, structural_defects,
                        gps_coordinates, land_use_type, soil_moisture_regime, surrounding_surface, 
                        team_members, notes, photo_url
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *;
                """
                values = (
                    body.get("treeId"), body.get("tagNumber"), body.get("scientificName"), body.get("commonName"), body.get("dbhInches"),
                    body.get("totalHeightFt"), body.get("canopyRadiusFt"), body.get("heightToCrownBaseFt"), body.get("numberOfTrunks", 1),
                    body.get("conditionClass"), body.get("diebackPercentage"), body.get("pestDiseasePresent"), body.get("structuralDefects"),
                    body.get("gpsCoordinates"), body.get("landUseType"), body.get("soilMoistureRegime"), body.get("surroundingSurface"),
                    body.get("teamMembers"), body.get("notes"), body.get("photoUrl")
                )
                
                cur.execute(query, values)
                inserted_row = cur.fetchone()
                conn.commit()
                return {"statusCode": 201, "headers": response_headers, "body": json.dumps(inserted_row, default=str)}

            # ⚡ UPDATE Operation (PUT)
            elif method == "PUT":
                if not tree_id:
                    return {"statusCode": 400, "headers": response_headers, "body": json.dumps({"error": "Missing tree ID parameter in route."})}
                if not event.get("body"):
                    return {"statusCode": 400, "headers": response_headers, "body": json.dumps({"error": "Missing update payload body."})}
                
                body = json.loads(event["body"])
                
                query = """
                    UPDATE tree_inventory 
                    SET tag_number = %s, scientific_name = %s, common_name = %s, dbh_inches = %s, 
                        total_height_ft = %s, canopy_radius_ft = %s, height_to_crown_base_ft = %s, number_of_trunks = %s,
                        condition_class = %s, dieback_percentage = %s, pest_disease_present = %s, structural_defects = %s,
                        gps_coordinates = %s, land_use_type = %s, soil_moisture_regime = %s, surrounding_surface = %s, 
                        team_members = %s, notes = %s, photo_url = %s, last_update = CURRENT_DATE
                    WHERE tree_id = %s
                    RETURNING *;
                """
                values = (
                    body.get("tagNumber"), body.get("scientificName"), body.get("commonName"), body.get("dbhInches"),
                    body.get("totalHeightFt"), body.get("canopyRadiusFt"), body.get("heightToCrownBaseFt"), body.get("numberOfTrunks", 1),
                    body.get("conditionClass"), body.get("diebackPercentage"), body.get("pestDiseasePresent"), body.get("structuralDefects"),
                    body.get("gpsCoordinates"), body.get("landUseType"), body.get("soilMoistureRegime"), body.get("surroundingSurface"),
                    body.get("teamMembers"), body.get("notes"), body.get("photoUrl"),
                    tree_id
                )
                
                cur.execute(query, values)
                updated_row = cur.fetchone()
                conn.commit()
                
                if not updated_row:
                    return {"statusCode": 404, "headers": response_headers, "body": json.dumps({"error": f"Record {tree_id} target not found to modify."})}
                return {"statusCode": 200, "headers": response_headers, "body": json.dumps(updated_row, default=str)}

            # ❌ DELETE Operation (DELETE)
            elif method == "DELETE":
                if not tree_id:
                    return {"statusCode": 400, "headers": response_headers, "body": json.dumps({"error": "Missing tree ID parameter in route query."})}
                
                cur.execute("DELETE FROM tree_inventory WHERE tree_id = %s RETURNING tree_id;", (tree_id,))
                deleted_row = cur.fetchone()
                conn.commit()
                
                if not deleted_row:
                    return {"statusCode": 404, "headers": response_headers, "body": json.dumps({"error": f"Record {tree_id} not found to purge."})}
                return {"statusCode": 200, "headers": response_headers, "body": json.dumps({"message": f"Tree registry record {tree_id} successfully purged."})}

            # Fallback if an unexpected HTTP request configuration breaches routing logic
            else:
                return {"statusCode": 405, "headers": response_headers, "body": json.dumps({"error": f"Method {method} not supported."})}
                
        conn.close()

    except Exception as e:
        if 'conn' in locals() and conn:
            conn.close()
        return {
            "statusCode": 500,
            "headers": response_headers,
            "body": json.dumps({"error": "Database Execution Failure Context", "details": str(e)})
        }
