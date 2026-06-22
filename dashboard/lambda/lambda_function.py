import json
import os
import urllib.parse
import psycopg2
from psycopg2.extras import RealDictCursor

# It is best practice to load these via Environment Variables or AWS Systems Manager
DB_HOST = os.environ.get("DB_HOST", "10.0.2.176") # Your EC2 Private IP
DB_NAME = "canopy_dashboard"
DB_USER = "postgres"
#DB_PASSWORD = os.environ.get("DB_PASSWORD", "uvaTr33C@n0Py!")
RAW_PASSWORD = "uvaTr33C@n0Py!"

# Safely escape special characters like @, !, or /
DB_PASSWORD = urllib.parse.quote_plus(RAW_PASSWORD)

def lambda_handler(event: dict, context: dict) -> dict:
    try:
        # Establish connection to the EC2 Postgres DB
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=5
        )
        
        # RealDictCursor returns rows as clean key-value dictionaries (JSON-ready)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM tree_inventory ORDER BY tree_id DESC LIMIT 50;")
            rows = cur.fetchall()
            
        conn.close()
        
        # Return standard API Gateway proxy response layout
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*" # Crucial: Permits your CloudFront frontend to fetch this data
            },
            "body": json.dumps(rows, default=str)
        }
        
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)})
        }

