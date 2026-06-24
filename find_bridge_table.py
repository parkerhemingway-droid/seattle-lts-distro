"""
Standalone script to find bridge tables linking listings to agents in Databricks.
Bypasses Streamlit decorators from src/db.py and uses the SDK directly.
"""
import sys
import os

# Add src to path so we can inspect db.py constants
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config
from databricks import sql as dbsql

DATABRICKS_HOST = os.getenv(
    "DATABRICKS_HOST",
    "compass-product-data-engineering.cloud.databricks.com",
)
SQL_WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "")


def get_connection():
    print("Authenticating with Databricks (browser login may open)...")
    cfg = Config(
        host=f"https://{DATABRICKS_HOST}",
        auth_type="external-browser",
    )
    client = WorkspaceClient(config=cfg)

    token = client.config.authenticate()["Authorization"].removeprefix("Bearer ")

    warehouse_id = SQL_WAREHOUSE_ID
    if not warehouse_id:
        print("Discovering SQL warehouse...")
        for wh in client.warehouses.list():
            if wh.state and wh.state.value in ("RUNNING", "IDLE"):
                warehouse_id = wh.id
                print(f"Using warehouse: {wh.name} ({warehouse_id})")
                break
        if not warehouse_id:
            raise RuntimeError("No running SQL warehouse found.")

    conn = dbsql.connect(
        server_hostname=DATABRICKS_HOST,
        http_path=f"/sql/1.0/warehouses/{warehouse_id}",
        access_token=token,
    )
    return conn


def run_query(conn, label, sql):
    print(f"\n{'='*60}")
    print(f"QUERY {label}")
    print('='*60)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        print(f"Columns: {cols}")
        print(f"Row count: {len(rows)}")
        for row in rows:
            print(row)
    except Exception as e:
        print(f"ERROR: {e}")


QUERY_A = """
SELECT table_name
FROM main.information_schema.tables
WHERE table_schema = 'bronze_mls_data'
ORDER BY table_name
"""

QUERY_B = """
SELECT table_name
FROM main.information_schema.tables
WHERE table_schema = 'bronze_agentintelligence'
ORDER BY table_name
"""

QUERY_C = """
SELECT c1.table_schema, c1.table_name, c1.column_name AS listing_col, c2.column_name AS agent_col
FROM main.information_schema.columns c1
JOIN main.information_schema.columns c2
  ON c1.table_schema = c2.table_schema AND c1.table_name = c2.table_name
WHERE (LOWER(c1.column_name) LIKE '%listing%id%' OR LOWER(c1.column_name) LIKE '%listing_external%')
  AND (LOWER(c2.column_name) LIKE '%agent%' )
ORDER BY c1.table_schema, c1.table_name
LIMIT 50
"""

QUERY_D = """
SELECT column_name, data_type
FROM main.information_schema.columns
WHERE table_schema = 'bronze_agentintelligence' AND table_name = 'listing_contacts'
ORDER BY ordinal_position
"""

QUERY_E = """
SELECT column_name, data_type
FROM main.information_schema.columns
WHERE table_schema = 'bronze_mls_data' AND table_name = 'agent'
ORDER BY ordinal_position
LIMIT 40
"""

QUERY_F = """
SELECT table_name, column_name
FROM main.information_schema.columns
WHERE table_schema = 'bronze_mls_data'
  AND (LOWER(column_name) LIKE '%listing%' OR LOWER(column_name) LIKE '%agent%')
ORDER BY table_name, column_name
LIMIT 100
"""

if __name__ == "__main__":
    conn = get_connection()
    try:
        run_query(conn, "A - Tables in bronze_mls_data", QUERY_A)
        run_query(conn, "B - Tables in bronze_agentintelligence", QUERY_B)
        run_query(conn, "C - Tables with BOTH listing ID and agent column", QUERY_C)
        run_query(conn, "D - Columns in bronze_agentintelligence.listing_contacts", QUERY_D)
        run_query(conn, "E - Columns in bronze_mls_data.agent", QUERY_E)
        run_query(conn, "F - All listing/agent columns in bronze_mls_data", QUERY_F)
    finally:
        conn.close()
    print("\n\nDone.")
