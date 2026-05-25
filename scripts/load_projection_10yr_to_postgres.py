from pathlib import Path
import os
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
PARQUET_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_sst_projection_10yr.parquet"
)

SCHEMA_NAME = "analytics"
TABLE_NAME = "region_monthly_sst_projection_10yr"


def get_database_url() -> str:
    """
    Reads database connection details from .env.

    Supports either:
    DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/dbname

    or separate variables:
    DB_HOST / POSTGRES_HOST
    DB_PORT / POSTGRES_PORT
    DB_NAME / POSTGRES_DB
    DB_USER / POSTGRES_USER
    DB_PASSWORD / POSTGRES_PASSWORD
    """

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        return database_url

    host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or "localhost"
    port = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or "5432"
    db_name = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")
    user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
    password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

    missing = []
    if not db_name:
        missing.append("DB_NAME or POSTGRES_DB")
    if not user:
        missing.append("DB_USER or POSTGRES_USER")
    if not password:
        missing.append("DB_PASSWORD or POSTGRES_PASSWORD")

    if missing:
        raise ValueError("Missing database settings in .env: " + ", ".join(missing))

    password_safe = quote_plus(password)

    return f"postgresql+psycopg2://{user}:{password_safe}@{host}:{port}/{db_name}"


def main():
    print(f"Loading .env from: {ENV_FILE}")
    load_dotenv(ENV_FILE)

    if not PARQUET_FILE.exists():
        raise FileNotFoundError(f"Projection file not found: {PARQUET_FILE}")

    print(f"Reading projection file: {PARQUET_FILE}")
    df = pd.read_parquet(PARQUET_FILE)

    print(f"Rows to load: {len(df):,}")
    print(df["observed_or_projected"].value_counts())

    # Make sure dates load cleanly into Postgres
    df["month_date"] = pd.to_datetime(df["month_date"]).dt.date

    database_url = get_database_url()
    engine = create_engine(database_url)

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME};"))

    df.to_sql(
        TABLE_NAME,
        engine,
        schema=SCHEMA_NAME,
        if_exists="replace",
        index=False,
    )

    print("\nLoaded successfully into Postgres:")
    print(f"{SCHEMA_NAME}.{TABLE_NAME}")
    print(f"Rows loaded: {len(df):,}")


if __name__ == "__main__":
    main()
