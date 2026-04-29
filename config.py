import os
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FAISS_INDEX_DIR = os.path.join(DATA_DIR, "faiss_index")

# Database — Supabase Postgres
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Anthropic
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL_NAME = "claude-sonnet-4-20250514"

# CSV source files — add more here as you expand
CSV_SOURCES = {
    "sales_data": {
        "path": os.path.join(DATA_DIR, "sales_data.csv"),
        "description": (
            "Sales transaction data organized by geographic region and sales representative. "
            "Includes order ID, date, customer name, product, category, quantity, unit price, total amount, region, and sales rep. "
            "Use this source for questions about regional sales, geographic revenue breakdown, "
            "sales by region, regional performance, rep performance, and product analysis."
        ),
    },
    "marketing_data": {
        "path": os.path.join(DATA_DIR, "marketing_data.csv"),
        "description": (
            "Digital marketing campaign performance data organized by marketing channel and month. "
            "Includes campaign name, channel (Google Ads, Facebook, Instagram, LinkedIn, Email), month, "
            "spend, impressions, clicks, conversions, and campaign revenue. "
            "Use this source for questions about marketing ROI, ad channel performance, "
            "campaign effectiveness, channel comparison, and conversion rates. "
            "This is campaign-level data, not organized by geographic region."
        ),
    },
    "facebook_ads": {
        "path": os.path.join(DATA_DIR, "facebook_ads.csv"),
        "description": (
            "Facebook and Instagram paid advertising data at the campaign and ad set level. "
            "Includes date, campaign name, ad set name, placement (Feed, Stories, Reels, Audience Network), "
            "objective, impressions, reach, clicks, spend, CTR, CPC, conversions, conversion rate, revenue, ROAS, and frequency. "
            "Use this source for questions about Facebook ads, Meta ads, Instagram ads, paid social performance, "
            "ROAS, cost per click, ad spend, campaign ROAS, retargeting performance, lookalike audiences, "
            "and placement-level breakdowns. Does not contain Google Ads or email data."
        ),
    },
    "vendor_central": {
        "path": os.path.join(DATA_DIR, "vendor_central.csv"),
        "description": (
            "Amazon Vendor Central sales and inventory data at the ASIN and product level. "
            "Includes date, ASIN, product title, category, ordered units, ordered revenue, shipped units, "
            "shipped revenue, glance views, conversion rate, customer returns, and replenishment status. "
            "Use this source for questions about Amazon sales, ASIN performance, product revenue on Amazon, "
            "glance views, inventory replenishment, customer returns, shipped vs ordered units, "
            "and product category performance on Amazon. Does not contain Facebook or direct sales data."
        ),
    },
}
