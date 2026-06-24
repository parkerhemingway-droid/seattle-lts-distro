# Likely Sellers Dashboard

Streamlit web app that surfaces likely-to-sell signals by zip code, powered entirely by **Compass public records** (RealtyTrac + MLS). No agent CRM data required.

## Signals

| Tab | What it shows |
|-----|---------------|
| Properties & AVM | All public-record properties in the zip with estimated values, appreciation, and mailing addresses |
| Closed Sales | Recent closed MLS transactions (configurable 1–25 year window) |
| Pending Activity | Active / under-contract listings |
| Home Appreciation | AVM vs last sale price — who has gained the most equity |
| Mortgage & Equity | Estimated equity % and loan amount distribution |
| Time in Home | Years of ownership distribution |
| Ad Target Zips | Scored nearby zips for digital ad targeting + buyer origin / seller destination zips |

## Setup

```bash
cd likely-sellers-dashboard

# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — DATABRICKS_HOST is pre-filled; set DATABRICKS_WAREHOUSE_ID if needed

# 3. Launch
streamlit run app.py
```

The first run opens a browser tab for Databricks OAuth login (SSO). After authenticating, enter any zip code in the sidebar and click **Search**.

## Data sources

| Table | Purpose |
|-------|---------|
| `main.gold_public_records.realtytrac_v3_nationwide_property` | Property details, ownership, mailing address |
| `main.gold_public_records.realtytrac_v3_avm` | Automated valuation model (AVM) |
| `main.gold_public_records.realtytrac_v3_nationwide_assessment` | Tax assessment values |
| `main.gold_public_records.mortgage` | Mortgage / lien records |
| `main.gold_mls.search_listings` | MLS closed sales and pending activity |

## Sidebar filters

- **Zip code** — any US zip
- **Closed sales window** — 1 to 25 years
- **Max properties to load** — 100 / 250 / 500 / 1000 / 2500 / 5000
- **AVM range** — slider + text inputs for min/max price
- **Property type** — populated after first search (single family, condo, etc.)
