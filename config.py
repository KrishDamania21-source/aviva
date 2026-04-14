import os
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "sales.db")
FAISS_INDEX_DIR = os.path.join(DATA_DIR, "faiss_index")

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
}
