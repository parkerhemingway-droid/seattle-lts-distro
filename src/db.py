"""
Databricks connection using OAuth browser-based login.
Builds a SQL connector from the SDK's token provider so credentials
are never stored in env vars or config files.
"""
import os
import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config
from databricks import sql as dbsql


DATABRICKS_HOST = os.getenv(
    "DATABRICKS_HOST",
    "compass-product-data-engineering.cloud.databricks.com",
)
SQL_WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "")


@st.cache_resource(show_spinner="Authenticating with Databricks…")
def get_workspace_client() -> WorkspaceClient:
    cfg = Config(
        host=f"https://{DATABRICKS_HOST}",
        auth_type="external-browser",
    )
    return WorkspaceClient(config=cfg)


@st.cache_resource(show_spinner="Connecting to SQL warehouse…")
def get_sql_connection(_client: WorkspaceClient):
    """
    Returns a databricks-sql-connector connection.
    _client is prefixed with _ so Streamlit does not hash the object.
    """
    token = _client.config.authenticate()["Authorization"].removeprefix("Bearer ")
    warehouse_id = SQL_WAREHOUSE_ID or _discover_warehouse(_client)
    return dbsql.connect(
        server_hostname=DATABRICKS_HOST,
        http_path=f"/sql/1.0/warehouses/{warehouse_id}",
        access_token=token,
    )


def _discover_warehouse(client: WorkspaceClient) -> str:
    """Pick the first running SQL warehouse available to the user."""
    for wh in client.warehouses.list():
        if wh.state and wh.state.value in ("RUNNING", "IDLE"):
            return wh.id
    raise RuntimeError(
        "No running SQL warehouse found. Set DATABRICKS_WAREHOUSE_ID in .env "
        "or start a warehouse in your Databricks workspace."
    )


def run_query(conn, sql: str, params=None) -> "pd.DataFrame":
    import pandas as pd
    from databricks.sql.exc import RequestError, OperationalError

    def _execute(c):
        with c.cursor() as cur:
            cur.execute(sql, params or [])
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        return pd.DataFrame(rows, columns=cols)

    try:
        return _execute(conn)
    except (RequestError, OperationalError):
        # Connection went stale. Clear cache so next call reconnects.
        st.cache_resource.clear()
        st.error("Connection lost — please click **Search** again to reconnect.")
        st.stop()
