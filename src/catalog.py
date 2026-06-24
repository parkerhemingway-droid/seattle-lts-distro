"""
Discover supplemental signal tables from information_schema.
Looks for tables whose names hint at: closed sales, pending listings,
home appreciation, mortgage/equity, and time-in-home.
"""
from __future__ import annotations
from typing import Optional
import streamlit as st
from src.db import run_query

# Keywords that map a signal to a candidate table name
SIGNAL_KEYWORDS = {
    "closed_sales": ["closed_sale", "sold_listing", "closed_listing", "transaction"],
    "pending": ["pending", "under_contract", "active_under"],
    "appreciation": ["appreciation", "home_value", "avm", "zestimate", "valuation"],
    "mortgage": ["mortgage", "equity", "loan", "lien"],
    "time_in_home": ["time_in_home", "length_of_ownership", "ownership_tenure", "years_owned"],
}

CATALOG = "main"
SCHEMA_PATTERN = "silver%"  # search silver layer first, fall back to gold


@st.cache_data(ttl=3600, show_spinner="Scanning catalog for signal tables…")
def discover_signal_tables(_conn) -> dict:
    """
    Returns a dict mapping each signal name to the best matching full table path,
    or None if nothing was found.
    """
    sql = f"""
        SELECT table_catalog, table_schema, table_name
        FROM {CATALOG}.information_schema.tables
        WHERE table_schema LIKE '{SCHEMA_PATTERN}'
           OR table_schema LIKE 'gold%'
        ORDER BY table_schema, table_name
    """
    try:
        df = run_query(_conn, sql)
    except Exception:
        # Fallback: query without catalog qualifier
        sql_fallback = """
            SELECT table_catalog, table_schema, table_name
            FROM information_schema.tables
            ORDER BY table_schema, table_name
        """
        df = run_query(_conn, sql_fallback)

    results: dict[str, str | None] = {}
    for signal, keywords in SIGNAL_KEYWORDS.items():
        match = _best_match(df, keywords)
        results[signal] = match
    return results


def _best_match(df, keywords: list[str]) -> str | None:
    for kw in keywords:
        hit = df[df["table_name"].str.contains(kw, case=False, na=False)]
        if not hit.empty:
            row = hit.iloc[0]
            return f"{row['table_catalog']}.{row['table_schema']}.{row['table_name']}"
    return None
