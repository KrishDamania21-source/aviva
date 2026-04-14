import sqlite3
import pandas as pd
from config import CSV_SOURCES, DB_PATH


def load_csv_to_table(table_name: str, csv_path: str, conn: sqlite3.Connection):
    """Read a single CSV file and write it into a SQLite table."""
    df = pd.read_csv(csv_path)
    df.to_sql(table_name, conn, if_exists="replace", index=False)
    print(f"Loaded '{table_name}' — {len(df)} rows, {len(df.columns)} columns")


def load_all_sources():
    """Load every CSV defined in CSV_SOURCES into the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    for table_name, source in CSV_SOURCES.items():
        load_csv_to_table(table_name, source["path"], conn)
    conn.close()
    print(f"\nAll sources loaded into {DB_PATH}")


if __name__ == "__main__":
    load_all_sources()
