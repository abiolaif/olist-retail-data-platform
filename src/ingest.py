import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_engine() -> Engine:
    load_dotenv()
    user = os.environ["DB_USER"]
    password = os.environ["DB_PASSWORD"]
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    dbname = os.environ["DB_NAME"]
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    return create_engine(url, future=True)


def compute_sha256(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def load_and_subset_raw_data(data_dir: Path, order_limit: int) -> Dict[str, pd.DataFrame]:
    files = {
        "orders": data_dir / "olist_orders_dataset.csv",
        "customers": data_dir / "olist_customers_dataset.csv",
        "order_items": data_dir / "olist_order_items_dataset.csv",
        "products": data_dir / "olist_products_dataset.csv",
        "sellers": data_dir / "olist_sellers_dataset.csv",
    }

    logger.info("=== Source File Checksums (SHA-256) ===")
    for name, path in files.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing required CSV: {path}")
        logger.info(f"  {path.name}: {compute_sha256(path)}")

    # 1. Read Orders and apply deterministic subsetting rule
    orders_raw = pd.read_csv(files["orders"], dtype=str)
    logger.info(f"Raw orders count: {len(orders_raw):,}")

    # Parse timestamps for deterministic sorting & validation
    ts_cols = [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]
    for col in ts_cols:
        orders_raw[col] = pd.to_datetime(orders_raw[col], errors="coerce")

    # Drop orders missing mandatory PK, FK, or purchase/estimated timestamps
    invalid_orders = orders_raw[
        orders_raw["order_id"].isna()
        | orders_raw["customer_id"].isna()
        | orders_raw["order_purchase_timestamp"].isna()
        | orders_raw["order_estimated_delivery_date"].isna()
    ]
    if len(invalid_orders) > 0:
        logger.warning(f"Rejected {len(invalid_orders)} orders due to missing mandatory keys/timestamps.")
    orders_clean = orders_raw.dropna(
        subset=["order_id", "customer_id", "order_purchase_timestamp", "order_estimated_delivery_date"]
    ).drop_duplicates(subset=["order_id"])

    # Deterministic selection: earliest N orders sorted by (order_purchase_timestamp, order_id)
    orders_subset = (
        orders_clean.sort_values(["order_purchase_timestamp", "order_id"], ascending=[True, True])
        .head(order_limit)
        .copy()
    )
    valid_order_ids = set(orders_subset["order_id"])
    valid_customer_ids = set(orders_subset["customer_id"])
    logger.info(f"Selected deterministic subset: {len(orders_subset):,} orders.")

    # 2. Filter Order Items to match selected orders
    items_raw = pd.read_csv(files["order_items"], dtype=str)
    items_sub = items_raw[items_raw["order_id"].isin(valid_order_ids)].copy()

    items_sub["order_item_id"] = pd.to_numeric(items_sub["order_item_id"], errors="coerce")
    items_sub["price"] = pd.to_numeric(items_sub["price"], errors="coerce")
    items_sub["freight_value"] = pd.to_numeric(items_sub["freight_value"], errors="coerce")
    items_sub["shipping_limit_date"] = pd.to_datetime(items_sub["shipping_limit_date"], errors="coerce")

    before_item_clean = len(items_sub)
    items_sub = items_sub.dropna(
        subset=["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"]
    )
    items_sub = items_sub[(items_sub["price"] >= 0) & (items_sub["freight_value"] >= 0) & (items_sub["order_item_id"] >= 1)]
    items_sub["order_item_id"] = items_sub["order_item_id"].astype(int)
    items_sub = items_sub.drop_duplicates(subset=["order_id", "order_item_id"])
    logger.info(
        f"Order items in subset: {len(items_sub):,} (rejected {before_item_clean - len(items_sub)} invalid/duplicate rows)"
    )

    valid_product_ids = set(items_sub["product_id"])
    valid_seller_ids = set(items_sub["seller_id"])

    # 3. Filter & clean Customers
    cust_raw = pd.read_csv(files["customers"], dtype=str)
    cust_sub = cust_raw[cust_raw["customer_id"].isin(valid_customer_ids)].drop_duplicates(subset=["customer_id"]).copy()
    cust_sub["zip_code_prefix"] = cust_sub["customer_zip_code_prefix"].str.strip().str.zfill(5)
    cust_sub["city"] = cust_sub["customer_city"].str.strip().str.lower()
    cust_sub["state"] = cust_sub["customer_state"].str.strip().str.upper()

    # 4. Filter & clean Sellers
    sell_raw = pd.read_csv(files["sellers"], dtype=str)
    sell_sub = sell_raw[sell_raw["seller_id"].isin(valid_seller_ids)].drop_duplicates(subset=["seller_id"]).copy()
    sell_sub["zip_code_prefix"] = sell_sub["seller_zip_code_prefix"].str.strip().str.zfill(5)
    sell_sub["city"] = sell_sub["seller_city"].str.strip().str.lower()
    sell_sub["state"] = sell_sub["seller_state"].str.strip().str.upper()

    # 5. Filter & clean Products
    prod_raw = pd.read_csv(files["products"], dtype=str)
    prod_sub = prod_raw[prod_raw["product_id"].isin(valid_product_ids)].drop_duplicates(subset=["product_id"]).copy()

    missing_cats = prod_sub["product_category_name"].isna().sum()
    prod_sub["product_category_name"] = prod_sub["product_category_name"].fillna("uncategorized").str.strip()
    logger.info(f"Products in subset: {len(prod_sub):,} (imputed {missing_cats} missing categories as 'uncategorized')")

    int_cols = [
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ]
    for col in int_cols:
        prod_sub[col] = pd.to_numeric(prod_sub[col], errors="coerce")
        # Negative dimensions/weights are physically impossible -> set to None
        prod_sub.loc[prod_sub[col] < 0, col] = None

    prod_sub = prod_sub.rename(
        columns={
            "product_name_lenght": "product_name_length",
            "product_description_lenght": "product_description_length",
        }
    )

    # 6. Build Canonical Locations Lookup (deduplicated by zip_code_prefix)
    loc_cust = cust_sub[["zip_code_prefix", "city", "state"]]
    loc_sell = sell_sub[["zip_code_prefix", "city", "state"]]
    locations = (
        pd.concat([loc_cust, loc_sell], ignore_index=True)
        .dropna(subset=["zip_code_prefix", "city", "state"])
        .sort_values(["zip_code_prefix", "city", "state"])
        .drop_duplicates(subset=["zip_code_prefix"], keep="first")
    )

    # 7. Build Customer Accounts Lookup
    customer_accounts = cust_sub[["customer_unique_id"]].dropna().drop_duplicates()

    # Verify referential completeness before DB load
    orders_subset = orders_subset[orders_subset["customer_id"].isin(set(cust_sub["customer_id"]))]
    items_sub = items_sub[
        items_sub["order_id"].isin(set(orders_subset["order_id"]))
        & items_sub["product_id"].isin(set(prod_sub["product_id"]))
        & items_sub["seller_id"].isin(set(sell_sub["seller_id"]))
    ]

    return {
        "locations": locations,
        "customer_accounts": customer_accounts,
        "customers": cust_sub[["customer_id", "customer_unique_id", "zip_code_prefix"]],
        "sellers": sell_sub[["seller_id", "zip_code_prefix"]],
        "products": prod_sub[
            [
                "product_id",
                "product_category_name",
                "product_name_length",
                "product_description_length",
                "product_photos_qty",
                "product_weight_g",
                "product_length_cm",
                "product_height_cm",
                "product_width_cm",
            ]
        ],
        "orders": orders_subset[
            [
                "order_id",
                "customer_id",
                "order_status",
                "order_purchase_timestamp",
                "order_approved_at",
                "order_delivered_carrier_date",
                "order_delivered_customer_date",
                "order_estimated_delivery_date",
            ]
        ],
        "order_items": items_sub[
            [
                "order_id",
                "order_item_id",
                "product_id",
                "seller_id",
                "shipping_limit_date",
                "price",
                "freight_value",
            ]
        ],
    }


def df_to_records(df: pd.DataFrame) -> list[dict]:
    # Convert Pandas NaT / NaN to Python None for SQLAlchemy/psycopg2
    cleaned = df.astype(object).where(pd.notnull(df), None)
    return cleaned.to_dict(orient="records")


def upsert_table(conn, table_name: str, records: list[dict], pk_cols: list[str], chunk_size: int = 2000) -> int:
    if not records:
        return 0
    from sqlalchemy import MetaData, Table

    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=conn)
    non_pk_cols = [c.name for c in table.columns if c.name not in pk_cols]

    total = 0
    for i in range(0, len(records), chunk_size):
        batch = records[i : i + chunk_size]
        stmt = insert(table).values(batch)
        if non_pk_cols:
            update_dict = {col: getattr(stmt.excluded, col) for col in non_pk_cols}
            stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_dict)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
        conn.execute(stmt)
        total += len(batch)
    return total


def main() -> None:
    load_dotenv()
    data_dir = Path(os.environ.get("DATA_DIR", "./data/raw"))
    order_limit = int(os.environ.get("SUBSET_ORDER_LIMIT", "10000"))

    engine = get_engine()
    frames = load_and_subset_raw_data(data_dir, order_limit)

    load_plan: list[Tuple[str, list[str]]] = [
        ("locations", ["zip_code_prefix"]),
        ("customer_accounts", ["customer_unique_id"]),
        ("customers", ["customer_id"]),
        ("sellers", ["seller_id"]),
        ("products", ["product_id"]),
        ("orders", ["order_id"]),
        ("order_items", ["order_id", "order_item_id"]),
    ]

    logger.info("=== Executing Transactional Idempotent Upsert ===")
    with engine.begin() as conn:
        for table_name, pk_cols in load_plan:
            records = df_to_records(frames[table_name])
            count = upsert_table(conn, table_name, records, pk_cols)
            logger.info(f"  Upserted {count:,} rows into '{table_name}'")

    logger.info("Ingestion completed successfully.")


if __name__ == "__main__":
    main()