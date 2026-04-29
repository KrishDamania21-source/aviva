import os
import pandas as pd
from sqlalchemy import create_engine, text
from config import CSV_SOURCES, DATABASE_URL


def load_csv_to_table(table_name: str, csv_path: str, engine):
    """Read a single CSV file and write it into a Postgres table."""
    df = pd.read_csv(csv_path)
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    print(f"Loaded '{table_name}' — {len(df)} rows, {len(df.columns)} columns")


def load_all_sources():
    """Load every CSV defined in CSV_SOURCES into the Postgres database."""
    print(f"DATABASE_URL starts with: {DATABASE_URL[:30] if DATABASE_URL else 'EMPTY'}")
    engine = create_engine(DATABASE_URL)
    for table_name, source in CSV_SOURCES.items():
        load_csv_to_table(table_name, source["path"], engine)
    print(f"\nAll sources loaded into Supabase.")


if __name__ == "__main__":
    load_all_sources()
