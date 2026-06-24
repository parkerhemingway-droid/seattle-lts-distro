"""
All SQL queries against Databricks public records tables.
Primary source: gold_public_records / realtytrac_v3 — no agent CRM required.
Join key across realtytrac tables: property_id (int).
Join key to gold mortgage/deed/ownership: data_source_primary_id = CAST(property_id AS STRING).
"""
from __future__ import annotations
from typing import Optional
import pandas as pd
from src.db import run_query

PROP_TABLE   = "main.gold_public_records.realtytrac_v3_nationwide_property"
AVM_TABLE    = "main.gold_public_records.realtytrac_v3_avm"
ASSESS_TABLE = "main.gold_public_records.realtytrac_v3_nationwide_assessment"
MORT_TABLE   = "main.gold_public_records.mortgage"
DEED_TABLE   = "main.gold_public_records.deed"
LISTINGS_TABLE  = "main.gold_mls.search_listings"
AGENT_BRIDGE    = "main.bronze_agentintelligence.listing_contacts"
LIKELY_TO_SELL  = "data_analytics.dev.likely_to_sell_property_scored"


def _prop_type_clause(property_types):
    if not property_types:
        return ""
    escaped = ", ".join(f"'{t.replace(chr(39), chr(39)*2)}'" for t in property_types)
    return f"AND p.jurisdiction_value IN ({escaped})"


def fetch_property_types(conn, zip_code: str) -> list:
    sql = f"""
        SELECT DISTINCT jurisdiction_value
        FROM {PROP_TABLE}
        WHERE property_address_zip = ?
          AND is_deleted_property = FALSE
          AND jurisdiction_value IS NOT NULL
          AND TRIM(jurisdiction_value) != ''
        ORDER BY jurisdiction_value
    """
    try:
        df = run_query(conn, sql, [zip_code])
        return sorted(df.iloc[:, 0].dropna().tolist())
    except Exception:
        return []


def inspect_likely_to_sell(conn):
    """Debug: show columns in likely_to_sell table."""
    sql = f"SELECT * FROM {LIKELY_TO_SELL} LIMIT 1"
    try:
        df = run_query(conn, sql)
        return list(df.columns)
    except Exception as e:
        return str(e)


def fetch_properties(conn, zip_code: str, limit: int = 500, avm_min: int = 0, avm_max: int = 100_000_000, property_types: list = None) -> pd.DataFrame:
    """
    Unique properties in zip joined with AVM.  Deduped on property_id (each
    unit in a multi-unit building has its own id, so this is correct).
    Null-address rows are excluded. last_sale_date is stored as integer YYYYMMDD.
    """
    sql = f"""
        WITH deduped_props AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY property_id ORDER BY last_sale_date DESC NULLS LAST) AS prop_rn
            FROM {PROP_TABLE}
            WHERE property_address_zip = ?
              AND is_deleted_property = FALSE
              AND property_address_house_number IS NOT NULL
              AND TRIM(property_address_house_number) != ''
              AND property_address_street_name IS NOT NULL
              AND TRIM(property_address_street_name) != ''
        )
        SELECT
            p.property_id,
            TRIM(CONCAT_WS(' ',
                NULLIF(p.property_address_house_number, ''),
                NULLIF(p.property_address_street_direction, ''),
                NULLIF(p.property_address_street_name, ''),
                NULLIF(p.property_address_street_suffix, '')
            ))                                                  AS street,
            TRIM(CONCAT_WS(' ',
                NULLIF(p.property_address_unit_prefix, ''),
                NULLIF(p.property_address_unit_value, '')
            ))                                                  AS unit,
            p.property_address_city                             AS city,
            p.property_address_state                            AS state,
            p.property_address_zip                              AS zip_code,
            p.jurisdiction_value                                AS property_type,
            TRIM(CONCAT_WS(' ',
                NULLIF(p.contact_owner_mail_address_house_number, ''),
                NULLIF(p.contact_owner_mail_address_street_direction, ''),
                NULLIF(p.contact_owner_mail_address_street_name, ''),
                NULLIF(p.contact_owner_mail_address_street_suffix, ''),
                NULLIF(p.contact_owner_mail_address_unit_prefix, ''),
                NULLIF(p.contact_owner_mail_address_unit, '')
            ))                                                  AS mailing_street,
            p.contact_owner_mail_address_city                   AS mailing_city,
            p.contact_owner_mail_address_state                  AS mailing_state,
            p.contact_owner_mail_address_zip                    AS mailing_zip,
            p.owner_1_name_full,
            p.owner_2_name_full,
            p.status_owner_occupied_flag,
            p.bedroom_count,
            p.bath_count_full,
            p.area_building                                     AS sqft,
            p.year_built,
            p.last_sale_date,
            p.last_sale_amount,
            a.avm_final_value,
            a.avm_low_value,
            a.avm_high_value,
            a.avm_confidence_score,
            CASE
                WHEN p.last_sale_amount > 0 AND a.avm_final_value IS NOT NULL
                THEN ROUND(
                    (a.avm_final_value - p.last_sale_amount) / p.last_sale_amount * 100, 1
                )
                ELSE NULL
            END                                                 AS appreciation_pct,
            CASE
                WHEN p.last_sale_date > 0
                THEN DATEDIFF(
                    year,
                    TO_DATE(CAST(p.last_sale_date AS STRING), 'yyyyMMdd'),
                    CURRENT_DATE()
                )
                ELSE NULL
            END                                                 AS years_in_home,
            lts.total_property_scored                          AS likely_to_sell_score
        FROM deduped_props p
        LEFT JOIN (
            SELECT property_id,
                   avm_final_value, avm_low_value, avm_high_value, avm_confidence_score,
                   ROW_NUMBER() OVER (PARTITION BY property_id ORDER BY avm_confidence_score DESC NULLS LAST) AS rn
            FROM {AVM_TABLE}
        ) a ON p.property_id = a.property_id AND a.rn = 1
        LEFT JOIN {LIKELY_TO_SELL} lts ON p.property_id = lts.geo_id
        WHERE p.prop_rn = 1
          AND (a.avm_final_value IS NULL OR (a.avm_final_value >= {avm_min} AND a.avm_final_value <= {avm_max}))
          {_prop_type_clause(property_types)}
        ORDER BY lts.total_property_scored DESC NULLS LAST, a.avm_final_value DESC NULLS LAST
        LIMIT {limit}
    """
    try:
        df = run_query(conn, sql, [zip_code])
        df.columns = [c.lower() for c in df.columns]
        # Build a clean display address: "123 MAIN ST" or "123 MAIN ST APT 4B"
        df["address"] = df.apply(
            lambda r: (r["street"] + (" " + r["unit"] if r.get("unit") else "")).strip(),
            axis=1,
        )
        def _mailing(r):
            parts = [r.get("mailing_street") or ""]
            city  = r.get("mailing_city") or ""
            state = r.get("mailing_state") or ""
            zip_  = r.get("mailing_zip") or ""
            city_line = ", ".join(filter(None, [city, state])) + (" " + zip_ if zip_ else "")
            parts.append(city_line)
            full = ", ".join(p for p in parts if p.strip())
            return full if full.strip(", ") else None
        df["mailing_address"] = df.apply(_mailing, axis=1)
        return df
    except Exception as e:
        raise e


def fetch_zip_summary(conn, zip_code: str) -> dict:
    sql = f"""
        SELECT
            COUNT(*)                                                         AS total_properties,
            SUM(CASE WHEN p.status_owner_occupied_flag = TRUE THEN 1 ELSE 0 END) AS owner_occupied,
            ROUND(AVG(a.avm_final_value), 0)                                AS avg_avm,
            ROUND(MEDIAN(a.avm_final_value), 0)                             AS median_avm,
            ROUND(AVG(
                CASE WHEN p.last_sale_amount > 0 AND a.avm_final_value IS NOT NULL
                THEN (a.avm_final_value - p.last_sale_amount) / p.last_sale_amount * 100
                ELSE NULL END
            ), 1)                                                            AS avg_appreciation_pct
        FROM {PROP_TABLE} p
        LEFT JOIN {AVM_TABLE} a ON p.property_id = a.property_id
        WHERE p.property_address_zip = ?
          AND p.is_deleted_property = FALSE
    """
    try:
        df = run_query(conn, sql, [zip_code])
        df.columns = [c.lower() for c in df.columns]
        return df.iloc[0].to_dict() if not df.empty else {}
    except Exception:
        return {}


def fetch_closed_sales(conn, zip_code: str, months: int = 60, months_start: int = 12) -> pd.DataFrame:
    sql = f"""
        SELECT
            listing_id,
            pretty_address,
            city,
            state,
            zipcode,
            bedrooms,
            bathrooms,
            square_feet,
            property_type,
            close_date,
            close_price,
            list_price,
            days_on_market_from_feed,
            price_per_square_foot,
            latitude,
            longitude
        FROM {LISTINGS_TABLE}
        WHERE zipcode = ?
          AND close_date >= DATEADD(month, -{months}, CURRENT_DATE())
          AND close_date <= DATEADD(month, -{months_start}, CURRENT_DATE())
          AND close_price IS NOT NULL
          AND is_deleted = FALSE
        ORDER BY close_date DESC
        LIMIT 300
    """
    try:
        df = run_query(conn, sql, [zip_code])
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def fetch_pending(conn, zip_code: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            listing_id,
            pretty_address,
            city,
            state,
            zipcode,
            bedrooms,
            bathrooms,
            square_feet,
            property_type,
            list_price,
            contract_date,
            contract_price,
            list_date,
            days_on_market_from_feed,
            price_per_square_foot,
            latitude,
            longitude
        FROM {LISTINGS_TABLE}
        WHERE zipcode = ?
          AND listing_status IN ('CONTRACT_OUT', 'CONTRACT_SIGNED', 'TEMPORARILY_OFF_MARKET', 'COMING_SOON', 'ACTIVE')
          AND is_deleted = FALSE
        ORDER BY contract_date DESC
        LIMIT 200
    """
    try:
        df = run_query(conn, sql, [zip_code])
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def fetch_mortgages(conn, zip_code: str) -> pd.DataFrame:
    """
    Join mortgage records to properties by data_source_primary_id = property_id.
    """
    sql = f"""
        SELECT
            p.property_id,
            CONCAT_WS(' ',
                p.property_address_house_number,
                p.property_address_street_name,
                p.property_address_street_suffix
            )                                   AS address,
            p.property_address_zip              AS zip_code,
            m.borrower_1_full_name,
            m.lender_name,
            m.amount                            AS mortgage_amount,
            m.interest_rate,
            m.interest_rate_type,
            m.mortgage_term_month,
            m.mortgage_type,
            m.transaction_date                  AS mortgage_date,
            a.avm_final_value,
            CASE
                WHEN m.amount > 0 AND a.avm_final_value IS NOT NULL
                THEN ROUND((a.avm_final_value - m.amount) / a.avm_final_value * 100, 1)
                ELSE NULL
            END                                 AS estimated_equity_pct
        FROM {PROP_TABLE} p
        JOIN {MORT_TABLE} m
          ON m.data_source_primary_id = CAST(p.property_id AS STRING)
        LEFT JOIN {AVM_TABLE} a ON p.property_id = a.property_id
        WHERE p.property_address_zip = ?
          AND p.is_deleted_property = FALSE
          AND m.is_deleted_property = FALSE
        ORDER BY m.transaction_date DESC
        LIMIT 500
    """
    try:
        df = run_query(conn, sql, [zip_code])
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def fetch_ad_target_zips(conn, zip_code: str) -> pd.DataFrame:
    """
    Score nearby zip codes for digital advertising (seller targeting).
    Price baseline comes from public-records AVM so any zip with property data works,
    even when MLS closed-sale history is sparse (e.g. WA/non-CA markets).
    Scoring: sales velocity 40%, price similarity 30%, days-on-market 30%.
    """
    sql = f"""
        WITH target AS (
            -- Use AVM median from public records — much broader coverage than MLS history
            SELECT
                p.property_address_state                AS state,
                MEDIAN(a.avm_final_value)               AS target_median_price
            FROM {PROP_TABLE} p
            LEFT JOIN {AVM_TABLE} a ON p.property_id = a.property_id
            WHERE p.property_address_zip = ?
              AND p.is_deleted_property = FALSE
              AND a.avm_final_value IS NOT NULL
            GROUP BY p.property_address_state
        ),
        zip_stats AS (
            SELECT
                l.zipcode,
                l.city,
                l.state,
                COUNT(*)                                                                    AS total_listings,
                SUM(CASE WHEN l.close_date >= DATEADD(month, -12, CURRENT_DATE())
                         AND l.close_price IS NOT NULL THEN 1 ELSE 0 END)                 AS closed_12mo,
                SUM(CASE WHEN l.close_date >= DATEADD(month, -3, CURRENT_DATE())
                         AND l.close_price IS NOT NULL THEN 1 ELSE 0 END)                 AS closed_3mo,
                ROUND(MEDIAN(l.close_price), 0)                                            AS median_close_price,
                ROUND(MEDIAN(l.list_price), 0)                                             AS median_list_price,
                ROUND(MEDIAN(l.days_on_market_from_feed), 0)                               AS median_dom,
                ROUND(MEDIAN(l.price_per_square_foot), 0)                                  AS median_price_per_sqft
            FROM {LISTINGS_TABLE} l
            JOIN target t ON l.state = t.state
            WHERE l.is_deleted = FALSE
              AND l.zipcode != ?
              AND l.zipcode IS NOT NULL
            GROUP BY l.zipcode, l.city, l.state
            HAVING closed_12mo >= 5
        )
        scored AS (
            SELECT
                z.zipcode,
                z.city,
                z.state,
                z.closed_12mo,
                z.closed_3mo,
                z.median_close_price,
                z.median_list_price,
                z.median_dom,
                z.median_price_per_sqft,
                z.total_listings,
                ROUND(
                    (LEAST(z.closed_12mo, 1000) / 10.0) * 0.40
                    + CASE
                        WHEN t.target_median_price IS NULL OR t.target_median_price = 0 THEN 0
                        ELSE GREATEST(0, 10 - ABS(z.median_close_price - t.target_median_price)
                             / t.target_median_price * 10) * 0.30
                      END
                    + CASE
                        WHEN z.median_dom IS NULL OR z.median_dom = 0 THEN 0
                        ELSE GREATEST(0, 10 - LEAST(z.median_dom, 100) / 10.0) * 0.30
                      END
                , 1) AS ad_score
            FROM zip_stats z
            JOIN target t ON z.state = t.state
        ),
        deduped AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY city, state ORDER BY ad_score DESC) AS rn
            FROM scored
        )
        SELECT
            zipcode, city, state, closed_12mo, closed_3mo,
            median_close_price, median_list_price, median_dom,
            median_price_per_sqft, total_listings, ad_score
        FROM deduped
        WHERE rn = 1
        ORDER BY ad_score DESC
        LIMIT 25
    """
    try:
        df = run_query(conn, sql, [zip_code, zip_code])
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def fetch_buyer_origin_zips(conn, zip_code: str) -> pd.DataFrame:
    """
    Zips where buyers of properties in this zip came from.
    Identified by: owner mailing address differs from property zip after a recent sale.
    These are the best zips for buyer-targeted ads (people already moving here).
    """
    sql = f"""
        SELECT
            contact_owner_mail_address_zip      AS origin_zip,
            contact_owner_mail_address_city     AS origin_city,
            contact_owner_mail_address_state    AS origin_state,
            COUNT(*)                            AS buyer_count,
            ROUND(MEDIAN(last_sale_amount), 0)  AS median_purchase_price,
            MIN(last_sale_date)                 AS earliest_sale,
            MAX(last_sale_date)                 AS latest_sale
        FROM {PROP_TABLE}
        WHERE property_address_zip = ?
          AND is_deleted_property = FALSE
          AND contact_owner_mail_address_zip IS NOT NULL
          AND TRIM(contact_owner_mail_address_zip) != ''
          AND contact_owner_mail_address_zip != property_address_zip
          AND last_sale_date > 20150101
        GROUP BY 1, 2, 3
        HAVING buyer_count >= 2
        ORDER BY buyer_count DESC
        LIMIT 25
    """
    try:
        df = run_query(conn, sql, [zip_code])
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def fetch_seller_destination_zips(conn, zip_code: str) -> pd.DataFrame:
    """
    Zips where past sellers of this zip area have moved to.
    Identified by: owners who sold in this zip and now have a mailing address elsewhere.
    Useful for targeting people who previously owned here and may want to return,
    or who are likely to refer buyers.
    """
    sql = f"""
        SELECT
            contact_owner_mail_address_zip      AS destination_zip,
            contact_owner_mail_address_city     AS destination_city,
            contact_owner_mail_address_state    AS destination_state,
            COUNT(*)                            AS seller_count,
            ROUND(MEDIAN(last_sale_amount), 0)  AS median_sale_price
        FROM {PROP_TABLE}
        WHERE property_address_zip = ?
          AND is_deleted_property = FALSE
          AND contact_owner_mail_address_zip IS NOT NULL
          AND TRIM(contact_owner_mail_address_zip) != ''
          AND contact_owner_mail_address_zip != property_address_zip
          AND contact_owner_mail_address_state IS NOT NULL
          AND last_sale_date > 20150101
          AND status_owner_occupied_flag = FALSE
        GROUP BY 1, 2, 3
        HAVING seller_count >= 2
        ORDER BY seller_count DESC
        LIMIT 25
    """
    try:
        df = run_query(conn, sql, [zip_code])
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def fetch_assessment(conn, zip_code: str) -> pd.DataFrame:
    """Tax assessment values joined to property for zip filtering."""
    sql = f"""
        SELECT
            p.property_id,
            CONCAT_WS(' ',
                p.property_address_house_number,
                p.property_address_street_name,
                p.property_address_street_suffix
            )                                       AS address,
            p.property_address_zip                  AS zip_code,
            p.owner_1_name_full,
            ass.assessment_year,
            ass.value_assessed,
            ass.market_value,
            a.avm_final_value,
            CASE
                WHEN ass.value_assessed > 0 AND a.avm_final_value IS NOT NULL
                THEN ROUND((a.avm_final_value - ass.value_assessed) / ass.value_assessed * 100, 1)
                ELSE NULL
            END                                     AS avm_vs_assessed_pct
        FROM {PROP_TABLE} p
        JOIN {ASSESS_TABLE} ass ON p.property_id = ass.property_id
        LEFT JOIN {AVM_TABLE} a ON p.property_id = a.property_id
        WHERE p.property_address_zip = ?
          AND p.is_deleted_property = FALSE
        ORDER BY ass.assessment_year DESC
        LIMIT 500
    """
    try:
        df = run_query(conn, sql, [zip_code])
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def fetch_listings_columns(conn) -> list:
    """Return column names for the MLS listings table."""
    sql = f"""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_catalog = 'main'
          AND table_schema = 'gold_mls'
          AND table_name = 'search_listings'
        ORDER BY ordinal_position
    """
    try:
        df = run_query(conn, sql)
        return df.iloc[:, 0].tolist()
    except Exception:
        return []


def fetch_agent_market_share(conn, zip_code: str) -> tuple:
    """
    Agent market share for closed sales in the zip — last 24 months.
    Joins listings → listing_contacts bridge → agent names.
    Falls back to brokerage-level if the bridge returns nothing.
    Returns (DataFrame, error_str).
    """
    sql = f"""
        WITH closed AS (
            SELECT listing_id, close_price, listing_brokerage
            FROM {LISTINGS_TABLE}
            WHERE zipcode = ?
              AND close_date >= DATEADD(month, -24, CURRENT_DATE())
              AND close_price IS NOT NULL
              AND is_deleted = FALSE
        ),
        agent_sides AS (
            SELECT
                INITCAP(REGEXP_REPLACE(lc.mris_agent_id_contact_name, '^[0-9]+:', '')) AS agent_name,
                c.listing_brokerage             AS brokerage,
                c.close_price
            FROM closed c
            JOIN {AGENT_BRIDGE} lc ON c.listing_id = lc.listing_id
            WHERE lc.mris_agent_id_contact_name IS NOT NULL
              AND TRIM(lc.mris_agent_id_contact_name) != ''
        ),
        agg AS (
            SELECT
                agent_name,
                MAX(brokerage)              AS brokerage,
                COUNT(*)                    AS closed_listings,
                ROUND(SUM(close_price), 0)  AS sold_volume
            FROM agent_sides
            GROUP BY agent_name
        ),
        totals AS (SELECT SUM(sold_volume) AS total_volume FROM agg)
        SELECT
            a.agent_name                                            AS `Agent Name`,
            a.brokerage                                             AS `Brokerage`,
            a.closed_listings                                       AS `Closed Listings`,
            a.sold_volume                                           AS `Sold Volume ($)`,
            ROUND(a.sold_volume / t.total_volume * 100, 1)         AS `Market Share (%)`
        FROM agg a CROSS JOIN totals t
        ORDER BY a.sold_volume DESC
        LIMIT 200
    """
    try:
        df = run_query(conn, sql, [zip_code])
        if not df.empty:
            return df, None
    except Exception as e:
        pass  # fall through to brokerage fallback

    # Fallback: brokerage-level only
    sql_fallback = f"""
        WITH agg AS (
            SELECT
                listing_brokerage               AS brokerage,
                COUNT(*)                        AS closed_listings,
                ROUND(SUM(close_price), 0)      AS sold_volume
            FROM {LISTINGS_TABLE}
            WHERE zipcode = ?
              AND close_date >= DATEADD(month, -24, CURRENT_DATE())
              AND close_price IS NOT NULL
              AND is_deleted = FALSE
              AND listing_brokerage IS NOT NULL
              AND TRIM(listing_brokerage) != ''
            GROUP BY 1
        ),
        totals AS (SELECT SUM(sold_volume) AS total_volume FROM agg)
        SELECT
            NULL                                                    AS `Agent Name`,
            a.brokerage                                             AS `Brokerage`,
            a.closed_listings                                       AS `Closed Listings`,
            a.sold_volume                                           AS `Sold Volume ($)`,
            ROUND(a.sold_volume / t.total_volume * 100, 1)         AS `Market Share (%)`
        FROM agg a CROSS JOIN totals t
        ORDER BY a.sold_volume DESC
        LIMIT 200
    """
    try:
        df = run_query(conn, sql_fallback, [zip_code])
        if df.empty:
            return pd.DataFrame(), "No closed sales data found for this zip."
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)


def fetch_neighborhoods(conn, zip_code: str) -> list:
    """Return distinct neighborhoods for a given zip code."""
    sql = f"""
        SELECT DISTINCT neighborhood
        FROM (
            SELECT EXPLODE(neighborhoods) AS neighborhood
            FROM {LISTINGS_TABLE}
            WHERE zipcode = ?
              AND neighborhoods IS NOT NULL
              AND is_deleted = FALSE
        )
        WHERE neighborhood IS NOT NULL
          AND TRIM(neighborhood) != ''
        ORDER BY neighborhood
    """
    try:
        df = run_query(conn, sql, [zip_code])
        return sorted(df.iloc[:, 0].dropna().tolist())
    except Exception:
        return []


def fetch_by_neighborhood(conn, neighborhood: str, months_back: int = 60) -> pd.DataFrame:
    """Closed sales in a given neighborhood over the past months_back months."""
    sql = f"""
        SELECT
            listing_id, pretty_address, city, state, zipcode,
            bedrooms, bathrooms, square_feet, property_type,
            close_date, close_price, list_price,
            days_on_market_from_feed, price_per_square_foot,
            latitude, longitude
        FROM {LISTINGS_TABLE}
        WHERE ARRAY_CONTAINS(neighborhoods, ?)
          AND close_date >= DATEADD(month, -{months_back}, CURRENT_DATE())
          AND close_price IS NOT NULL
          AND is_deleted = FALSE
        ORDER BY close_date DESC
        LIMIT 500
    """
    try:
        df = run_query(conn, sql, [neighborhood])
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()
