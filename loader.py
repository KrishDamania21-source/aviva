import os
import pandas as pd
from sqlalchemy import create_engine
from config import CSV_SOURCES


def load_csv_to_table(table_name: str, csv_path: str, engine):
    """Read a single CSV file and write it into a Postgres table."""
    df = pd.read_csv(csv_path)
    # Lowercase all column names — avoids case-sensitivity issues in PostgreSQL
    df.columns = [c.lower() for c in df.columns]
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    print(f"Loaded '{table_name}' — {len(df)} rows, {len(df.columns)} columns")


def load_all_sources():
    """Load every CSV defined in CSV_SOURCES into the Postgres database."""
    # Read directly from environment to avoid import-time config issues
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is not set.")
    engine = create_engine(db_url)
    for table_name, source in CSV_SOURCES.items():
        load_csv_to_table(table_name, source["path"], engine)
    print(f"\nAll sources loaded into Supabase.")


if __name__ == "__main__":
    load_all_sources()
