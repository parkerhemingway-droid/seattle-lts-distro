"""
Likely Sellers Dashboard — Public Records Edition
Powered by gold_public_records (RealtyTrac) + gold_mls.search_listings.
No agent CRM data required.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv

load_dotenv()

from src.db import get_workspace_client, get_sql_connection
from src.google_docs import create_envelope_doc
from src.queries import (
    fetch_properties,
    fetch_property_types,
    fetch_zip_summary,
    fetch_closed_sales,
    fetch_pending,
    fetch_mortgages,
    fetch_assessment,
    fetch_ad_target_zips,
    fetch_buyer_origin_zips,
    fetch_seller_destination_zips,
    fetch_agent_market_share,
    fetch_neighborhoods,
    fetch_by_neighborhood,
)

st.set_page_config(
    page_title="Likely Sellers Dashboard",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏡 Likely Sellers Dashboard")
st.caption("Powered by Compass · Public Records (RealtyTrac + MLS)")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Connection")
    if st.button("Connect / Re-authenticate", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()

try:
    client = get_workspace_client()
    conn = get_sql_connection(client)
except Exception as e:
    st.error(f"Authentication failed: {e}")
    st.info("Click **Connect / Re-authenticate** in the sidebar to try again.")
    st.stop()


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.header("Search")
    zip_code = st.text_input("Zip Code", placeholder="e.g. 90210", max_chars=10)
    _nbhd_options = st.session_state.get("neighborhood_options", [])
    _nbhd_zip     = st.session_state.get("neighborhood_options_zip", "")
    neighborhoods = st.multiselect(
        "Neighborhoods (optional)",
        options=_nbhd_options,
        default=[],
        help="Run a search first to populate neighborhoods for the entered zip code.",
        placeholder="Select one or more neighborhoods" if _nbhd_options else "Enter a zip and search first",
        disabled=not _nbhd_options,
    )
    years_range = st.slider("Closed sales window (years)", 1, 25, (1, 5))
    months_back = years_range[1] * 12
    months_start = years_range[0] * 12
    result_limit = st.number_input(
        "Max properties to load",
        min_value=1,
        max_value=10_000,
        value=500,
        step=100,
        help="Type any number or use the arrows (1 – 10,000)",
    )
    st.markdown("**Property valuation (AVM)**")
    _avm_col1, _avm_col2 = st.columns(2)
    _avm_min_input = _avm_col1.number_input("Min ($)", min_value=0, max_value=10_000_000, value=0, step=50_000, label_visibility="collapsed", placeholder="Min $")
    _avm_max_input = _avm_col2.number_input("Max ($)", min_value=0, max_value=10_000_000, value=10_000_000, step=50_000, label_visibility="collapsed", placeholder="Max $")
    _avm_col1.caption("Min $")
    _avm_col2.caption("Max $")
    avm_range = st.slider(
        "AVM slider",
        min_value=0,
        max_value=10_000_000,
        value=(int(_avm_min_input), int(_avm_max_input)),
        step=50_000,
        format="$%d",
        label_visibility="collapsed",
    )
    # Text inputs override the slider if they differ from slider position
    avm_range = (
        min(int(_avm_min_input), avm_range[1]),
        max(int(_avm_max_input), avm_range[0]),
    )
    _cached_types = st.session_state.get("prop_types_for_zip", [])
    selected_types = st.multiselect(
        "Property type",
        options=_cached_types,
        default=[],
        placeholder="All types" if _cached_types else "Run a search first",
    )
    run_search = st.button("Search", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------
if run_search and (zip_code or neighborhoods):
    st.session_state["last_searched_zip"] = zip_code.strip() if zip_code else ""
    st.session_state["last_searched_nbhds"] = neighborhoods

active_zip   = st.session_state.get("last_searched_zip", "")
active_nbhds = st.session_state.get("last_searched_nbhds", [])

if not active_zip and not active_nbhds:
    st.info("Enter a zip code or select neighborhoods in the sidebar and click **Search** to begin.")
    st.stop()

zip_code      = active_zip
neighborhoods = active_nbhds

# Populate property type dropdown after the first search for a zip.
# Store in session_state so it persists across reruns without re-querying.
if st.session_state.get("prop_types_zip") != zip_code:
    types = fetch_property_types(conn, zip_code)
    st.session_state["prop_types_for_zip"] = types
    st.session_state["prop_types_zip"] = zip_code
    nbhd_list = fetch_neighborhoods(conn, zip_code)
    st.session_state["neighborhood_options"] = nbhd_list
    st.session_state["neighborhood_options_zip"] = zip_code
    st.rerun()


@st.cache_data(ttl=300, show_spinner="Loading public records…")
def load_all(zip_code, neighborhoods_tuple, months_back, months_start, result_limit, avm_min, avm_max, prop_types_key):
    prop_types = list(prop_types_key)
    props    = fetch_properties(conn, zip_code, limit=result_limit, avm_min=avm_min, avm_max=avm_max, property_types=prop_types or None) if zip_code else pd.DataFrame()
    summary  = fetch_zip_summary(conn, zip_code) if zip_code else {}
    closed   = fetch_closed_sales(conn, zip_code, months_back, months_start) if zip_code else pd.DataFrame()
    pending  = fetch_pending(conn, zip_code) if zip_code else pd.DataFrame()
    mort     = fetch_mortgages(conn, zip_code) if zip_code else pd.DataFrame()
    assess   = fetch_assessment(conn, zip_code) if zip_code else pd.DataFrame()
    ad_zips        = fetch_ad_target_zips(conn, zip_code) if zip_code else pd.DataFrame()
    buyer_origins  = fetch_buyer_origin_zips(conn, zip_code) if zip_code else pd.DataFrame()
    seller_dests   = fetch_seller_destination_zips(conn, zip_code) if zip_code else pd.DataFrame()
    agent_share, agent_share_err = fetch_agent_market_share(conn, zip_code) if zip_code else (pd.DataFrame(), None)
    nbhd_closed = pd.concat([fetch_by_neighborhood(conn, nbhd, months_back) for nbhd in neighborhoods_tuple], ignore_index=True) if neighborhoods_tuple else pd.DataFrame()
    return props, summary, closed, pending, mort, assess, ad_zips, buyer_origins, seller_dests, agent_share, agent_share_err, nbhd_closed


_nbhd_label = ", ".join(neighborhoods) if neighborhoods else ""
_search_label = " / ".join(filter(None, [zip_code, _nbhd_label]))
with st.spinner(f"Loading data for {_search_label}…"):
    props, summary, closed, pending, mort, assess, ad_zips, buyer_origins, seller_dests, agent_share, agent_share_err, nbhd_closed = load_all(
        zip_code, tuple(neighborhoods), months_back, months_start, result_limit,
        avm_range[0], avm_range[1], tuple(sorted(selected_types)),
    )

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Properties", f"{int(summary.get('total_properties', 0) or 0):,}",
          help="All non-deleted properties in the zip per public records (RealtyTrac).")
k2.metric("Owner Occupied",   f"{int(summary.get('owner_occupied', 0) or 0):,}",
          help="Properties where the mailing address matches the property address, indicating the owner lives there.")
k3.metric("Median AVM",       f"${float(summary.get('median_avm', 0) or 0):,.0f}",
          help="Median Automated Valuation Model estimate across all properties with an AVM value in this zip.")
k4.metric("Avg Appreciation", f"{float(summary.get('avg_appreciation_pct', 0) or 0):.1f}%",
          help="Average appreciation from last recorded sale price to current AVM. Only includes properties with both values.")
k5.metric("Pending Listings", len(pending) if not pending.empty else "—",
          help="Active, under-contract, or coming-soon listings currently on the MLS in this zip.")

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "🏠 Properties & AVM",
    "🏘️ Closed Sales",
    "⏳ Pending Activity",
    "📈 Home Appreciation",
    "💰 Mortgage & Equity",
    "🕰️ Time in Home",
    "🎯 Ad Target Zips",
    "🏆 Agent Market Share",
    "🗺️ Neighborhood",
])

# ── Tab 1: Properties & AVM ───────────────────────────────────────────────
with tab1:
    if props.empty:
        st.warning(f"No public record properties found for zip {zip_code}.")
    else:
        valid_avm = props[props["avm_final_value"].notna()]
        if not valid_avm.empty:
            fig = px.histogram(
                valid_avm,
                x="avm_final_value",
                nbins=30,
                title="AVM Value Distribution",
                labels={"avm_final_value": "Estimated Value ($)"},
                color_discrete_sequence=["#0066CC"],
            )
            st.plotly_chart(fig, use_container_width=True)

        display_cols = [c for c in [
            "likely_to_sell_score", "address", "mailing_address", "city", "zip_code",
            "owner_1_name_full", "owner_2_name_full",
            "status_owner_occupied_flag",
            "bedroom_count", "bath_count_full", "sqft", "year_built",
            "last_sale_date", "last_sale_amount",
            "avm_final_value", "avm_low_value", "avm_high_value",
            "avm_confidence_score", "appreciation_pct", "years_in_home",
        ] if c in props.columns]
        st.subheader(f"{len(props):,} properties (limit: {result_limit:,})")
        st.dataframe(props[display_cols], use_container_width=True, hide_index=True)

        st.divider()
        if st.button("📬 Create A10 Envelope Doc in Google Docs", key="envelope_btn"):
            envelope_rows = []
            for _, r in props.iterrows():
                name = " / ".join(filter(None, [
                    str(r.get("owner_1_name_full") or "").strip(),
                    str(r.get("owner_2_name_full") or "").strip(),
                ]))
                envelope_rows.append({
                    "owner_name": name,
                    "address":    str(r.get("address") or "").strip(),
                    "city":       str(r.get("city") or "").strip(),
                    "state":      str(r.get("state") or "").strip(),
                    "zip_code":   str(r.get("zip_code") or "").strip(),
                })
            envelope_rows = [e for e in envelope_rows if e["address"]]
            with st.spinner(f"Creating Google Doc for {len(envelope_rows):,} envelopes…"):
                try:
                    url = create_envelope_doc(envelope_rows, zip_code)
                    st.success(f"Doc created! [Open in Google Docs]({url})")
                except Exception as e:
                    st.error(f"Failed to create doc: {e}")

# ── Tab 2: Closed Sales ───────────────────────────────────────────────────
with tab2:
    if closed.empty:
        st.warning(f"No closed sales found in zip {zip_code} in the last {months_back} months.")
    else:
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Total Closed", len(closed))
        col_b.metric("Median Sale Price", f"${closed['close_price'].median():,.0f}")
        dom = closed["days_on_market_from_feed"]
        col_c.metric("Avg Days on Market", f"{dom.mean():.0f}" if dom.notna().any() else "—")

        has_sqft = "square_feet" in closed.columns and closed["square_feet"].notna().any()
        scatter_df = closed.dropna(subset=["square_feet"]) if has_sqft else closed
        fig = px.scatter(
            scatter_df,
            x="close_date",
            y="close_price",
            size="square_feet" if has_sqft and not scatter_df.empty else None,
            color="property_type" if "property_type" in scatter_df.columns else None,
            hover_data=["pretty_address", "bedrooms", "bathrooms"],
            title=f"Closed Sales — Last {months_back} Months",
            labels={"close_date": "Close Date", "close_price": "Sale Price ($)"},
        )
        st.plotly_chart(fig, use_container_width=True)

        fig2 = px.histogram(
            closed, x="close_price", nbins=25,
            title="Sale Price Distribution",
            color_discrete_sequence=["#00AA44"],
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.dataframe(closed, use_container_width=True, hide_index=True)

# ── Tab 3: Pending Activity ───────────────────────────────────────────────
with tab3:
    if pending.empty:
        st.warning(f"No pending/under-contract listings found in zip {zip_code}.")
    else:
        col_a, col_b = st.columns(2)
        col_a.metric("Active Pending", len(pending))
        lp = pending["list_price"]
        col_b.metric("Median List Price", f"${lp.median():,.0f}" if lp.notna().any() else "—")

        fig = px.histogram(
            pending, x="list_price", nbins=20,
            title="Pending — List Price Distribution",
            color_discrete_sequence=["#FF6600"],
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(pending, use_container_width=True, hide_index=True)

# ── Tab 4: Home Appreciation ──────────────────────────────────────────────
with tab4:
    if props.empty:
        st.warning(f"No appreciation data available for zip {zip_code}.")
    else:
        valid = props[props["appreciation_pct"].notna()].copy()
        if valid.empty:
            st.info("Appreciation % requires both a prior sale price and an AVM value.")
        else:
            col_a, col_b = st.columns(2)
            col_a.metric("Median Appreciation %", f"{valid['appreciation_pct'].median():.1f}%")
            col_b.metric("Properties with Data", len(valid))

            fig = px.histogram(
                valid, x="appreciation_pct", nbins=30,
                title="Appreciation % (Last Sale Price → Current AVM)",
                labels={"appreciation_pct": "Appreciation %"},
                color_discrete_sequence=["#9933CC"],
            )
            st.plotly_chart(fig, use_container_width=True)

            if "years_in_home" in valid.columns:
                valid_yrs = valid[valid["years_in_home"].notna() & (valid["years_in_home"] >= 0)]
                if not valid_yrs.empty:
                    fig2 = px.scatter(
                        valid_yrs,
                        x="years_in_home",
                        y="appreciation_pct",
                        hover_data=["address", "last_sale_amount", "avm_final_value"],
                        title="Appreciation % vs Years Owned",
                        labels={"years_in_home": "Years Owned", "appreciation_pct": "Appreciation %"},

                        color_discrete_sequence=["#9933CC"],
                    )
                    st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(
            valid[["address", "owner_1_name_full", "last_sale_date", "last_sale_amount",
                   "avm_final_value", "appreciation_pct", "years_in_home"]].head(500)
            if not valid.empty else props,
            use_container_width=True, hide_index=True,
        )

# ── Tab 5: Mortgage & Equity ──────────────────────────────────────────────
with tab5:
    if mort.empty:
        st.warning(f"No mortgage records found for zip {zip_code}.")
    else:
        valid = mort[mort["estimated_equity_pct"].notna()]
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Mortgage Records", len(mort))
        if not valid.empty:
            col_b.metric("Median Est. Equity %", f"{valid['estimated_equity_pct'].median():.1f}%")
        if mort["mortgage_amount"].notna().any():
            col_c.metric("Median Loan Amount", f"${mort['mortgage_amount'].median():,.0f}")

        if not valid.empty:
            fig = px.histogram(
                valid, x="estimated_equity_pct", nbins=25,
                title="Estimated Equity % (AVM − Mortgage / AVM)",
                labels={"estimated_equity_pct": "Equity %"},
                color_discrete_sequence=["#CC3300"],
            )
            st.plotly_chart(fig, use_container_width=True)

        if mort["mortgage_amount"].notna().any():
            fig2 = px.histogram(
                mort.dropna(subset=["mortgage_amount"]),
                x="mortgage_amount", nbins=25,
                title="Mortgage Amount Distribution",
                color_discrete_sequence=["#884400"],
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(mort, use_container_width=True, hide_index=True)

# ── Tab 6: Time in Home ───────────────────────────────────────────────────
with tab6:
    if props.empty:
        st.warning(f"No time-in-home data available for zip {zip_code}.")
    else:
        valid = props[
            props["years_in_home"].notna() & (props["years_in_home"] >= 0)
        ].copy()
        if valid.empty:
            st.info("Years-in-home requires a valid last sale date in public records.")
        else:
            col_a, col_b = st.columns(2)
            col_a.metric("Median Years in Home", f"{valid['years_in_home'].median():.1f}")
            col_b.metric("% Owned 5+ Years", f"{(valid['years_in_home'] >= 5).mean() * 100:.1f}%")

            fig = px.histogram(
                valid, x="years_in_home", nbins=25,
                title="Years in Home Distribution",
                labels={"years_in_home": "Years in Home"},
                color_discrete_sequence=["#006699"],
            )
            st.plotly_chart(fig, use_container_width=True)

            fig2 = px.scatter(
                valid,
                x="years_in_home",
                y="appreciation_pct",
                hover_data=["address", "owner_1_name_full"],
                title="Years in Home vs Appreciation %",
                labels={"years_in_home": "Years in Home", "appreciation_pct": "Appreciation %"},
                color_discrete_sequence=["#006699"],
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(
            valid[["address", "owner_1_name_full", "last_sale_date",
                   "years_in_home", "avm_final_value", "appreciation_pct"]].head(500)
            if not valid.empty else props,
            use_container_width=True, hide_index=True,
        )

# ── Tab 7: Ad Target Zips ─────────────────────────────────────────────────
with tab7:
    st.subheader(f"Digital advertising targets near {zip_code}")

    ad_sec, buyer_sec, seller_sec = st.tabs([
        "📊 Seller Target Zips",
        "🏃 Buyer Origin Zips",
        "📦 Seller Destination Zips",
    ])

    # ── Seller target zips ──────────────────────────────────────────────
    with ad_sec:
        st.caption(
            "Nearby zips scored for seller-targeted ads: sales velocity (40%), "
            "price similarity (30%), days-on-market / demand (30%)."
        )
        if ad_zips.empty:
            st.warning("No nearby zip data found. This may be a low-volume market — try a broader metro zip.")
        else:
            top = ad_zips.iloc[0]
            k1, k2, k3 = st.columns(3)
            k1.metric("Top Zip", f"{top['zipcode']} ({top['city']})")
            k2.metric("Ad Score", f"{top['ad_score']:.1f} / 10")
            k3.metric("Closed (12mo)", f"{int(top['closed_12mo']):,}")

            fig = px.bar(
                ad_zips, x="zipcode", y="ad_score",
                color="ad_score", color_continuous_scale="Blues",
                hover_data=["city", "closed_12mo", "median_close_price", "median_dom"],
                title="Seller Ad Score by Zip",
                labels={"zipcode": "Zip", "ad_score": "Ad Score"},
            )
            fig.update_layout(coloraxis_showscale=False, xaxis_type="category")
            st.plotly_chart(fig, use_container_width=True)

            fig2 = px.scatter(
                ad_zips, x="closed_12mo", y="median_close_price",
                size="total_listings", color="ad_score",
                color_continuous_scale="Blues", text="zipcode",
                hover_data=["city", "median_dom", "ad_score"],
                title="Velocity vs Median Price (bubble = audience size)",
                labels={"closed_12mo": "Closed (12mo)", "median_close_price": "Median Sale $"},
            )
            fig2.update_traces(textposition="top center")
            st.plotly_chart(fig2, use_container_width=True)

            st.dataframe(ad_zips.rename(columns={
                "zipcode": "Zip", "city": "City", "state": "State",
                "ad_score": "Ad Score", "closed_12mo": "Closed (12mo)",
                "closed_3mo": "Closed (3mo)", "median_close_price": "Median Sale $",
                "median_list_price": "Median List $", "median_dom": "Median DOM",
                "median_price_per_sqft": "$/sqft", "total_listings": "Total Listings",
            }), use_container_width=True, hide_index=True)

    # ── Buyer origin zips ───────────────────────────────────────────────
    with buyer_sec:
        st.caption(
            "Zip codes where people who **bought** in this zip previously lived. "
            "Target these zips to reach buyers already moving to this area."
        )
        if buyer_origins.empty:
            st.warning("No buyer origin data found.")
        else:
            k1, k2, k3 = st.columns(3)
            k1.metric("Distinct Origin Zips", len(buyer_origins))
            k2.metric("Top Origin", f"{buyer_origins.iloc[0]['origin_zip']} ({buyer_origins.iloc[0]['origin_city']})")
            k3.metric("Buyers from Top Zip", int(buyer_origins.iloc[0]["buyer_count"]))

            fig = px.bar(
                buyer_origins, x="origin_zip", y="buyer_count",
                color="median_purchase_price", color_continuous_scale="Greens",
                hover_data=["origin_city", "origin_state", "median_purchase_price"],
                title="Buyer Count by Origin Zip",
                labels={"origin_zip": "Origin Zip", "buyer_count": "Buyers"},
            )
            fig.update_layout(xaxis_type="category")
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(buyer_origins.rename(columns={
                "origin_zip": "Origin Zip", "origin_city": "City",
                "origin_state": "State", "buyer_count": "Buyers",
                "median_purchase_price": "Median Purchase $",
                "earliest_sale": "Earliest Sale", "latest_sale": "Latest Sale",
            }), use_container_width=True, hide_index=True)

    # ── Seller destination zips ─────────────────────────────────────────
    with seller_sec:
        st.caption(
            "Zip codes where owners who **sold** in this zip have moved to. "
            "Target these zips to reach past sellers who may refer buyers or return."
        )
        if seller_dests.empty:
            st.warning("No seller destination data found.")
        else:
            k1, k2, k3 = st.columns(3)
            k1.metric("Distinct Destination Zips", len(seller_dests))
            k2.metric("Top Destination", f"{seller_dests.iloc[0]['destination_zip']} ({seller_dests.iloc[0]['destination_city']})")
            k3.metric("Sellers to Top Zip", int(seller_dests.iloc[0]["seller_count"]))

            fig = px.bar(
                seller_dests, x="destination_zip", y="seller_count",
                color="median_sale_price", color_continuous_scale="Oranges",
                hover_data=["destination_city", "destination_state", "median_sale_price"],
                title="Seller Count by Destination Zip",
                labels={"destination_zip": "Destination Zip", "seller_count": "Sellers"},
            )
            fig.update_layout(xaxis_type="category")
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(seller_dests.rename(columns={
                "destination_zip": "Destination Zip", "destination_city": "City",
                "destination_state": "State", "seller_count": "Sellers",
                "median_sale_price": "Median Sale $",
            }), use_container_width=True, hide_index=True)

# ── Tab 8: Agent Market Share ─────────────────────────────────────────────
with tab8:
    st.subheader(f"Agent market share — closed sales in {zip_code} (last 24 months)")
    if agent_share_err:
        st.error(f"Query error: {agent_share_err}")
    elif agent_share.empty:
        st.warning(f"No agent data found for zip {zip_code}.")
    else:
        has_agents = agent_share["Agent Name"].notna().any()
        k1, k2, k3 = st.columns(3)
        k1.metric("Agents" if has_agents else "Brokerages", len(agent_share))
        k2.metric("Closed Listings", f"{int(agent_share['Closed Listings'].sum()):,}")
        k3.metric("Total Volume", f"${agent_share['Sold Volume ($)'].sum():,.0f}")

        y_col = "Agent Name" if has_agents else "Brokerage"
        fig = px.bar(
            agent_share.head(20),
            x="Market Share (%)", y=y_col,
            orientation="h",
            color="Market Share (%)",
            color_continuous_scale="Blues",
            hover_data=["Brokerage", "Closed Listings", "Sold Volume ($)"],
            title="Top 20 by Market Share",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(agent_share, use_container_width=True, hide_index=True)

# ── Tab 9: Neighborhood ───────────────────────────────────────────────────
with tab9:
    if not neighborhoods:
        st.info("Select one or more neighborhoods from the sidebar to see data here.")
    elif nbhd_closed.empty:
        st.warning(f"No closed sales found for neighborhoods: {', '.join(neighborhoods)}")
    else:
        st.subheader(f"{', '.join(neighborhoods)} — closed sales (last {months_back} months)")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Closed Sales", len(nbhd_closed))
        k2.metric("Median Sale Price", f"${nbhd_closed['close_price'].median():,.0f}")
        k3.metric("Avg Price/sqft", f"${nbhd_closed['price_per_square_foot'].mean():,.0f}" if nbhd_closed["price_per_square_foot"].notna().any() else "—")
        dom = nbhd_closed["days_on_market_from_feed"]
        k4.metric("Avg Days on Market", f"{dom.mean():.0f}" if dom.notna().any() else "—")

        fig = px.scatter(
            nbhd_closed.dropna(subset=["close_date", "close_price"]),
            x="close_date", y="close_price",
            color="property_type" if "property_type" in nbhd_closed.columns else None,
            hover_data=["pretty_address", "bedrooms", "bathrooms", "zipcode"],
            title=f"Closed Sales — {neighborhood}",
            labels={"close_date": "Close Date", "close_price": "Sale Price ($)"},
        )
        st.plotly_chart(fig, use_container_width=True)

        fig2 = px.histogram(
            nbhd_closed, x="close_price", nbins=25,
            title="Sale Price Distribution",
            color_discrete_sequence=["#0066CC"],
        )
        st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(nbhd_closed, use_container_width=True, hide_index=True)
