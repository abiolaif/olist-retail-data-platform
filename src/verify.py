import json
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def get_engine():
    load_dotenv()
    url = (
        f"postgresql+psycopg2://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
        f"@{os.environ.get('DB_HOST', 'localhost')}:{os.environ.get('DB_PORT', '5432')}/{os.environ['DB_NAME']}"
    )
    return create_engine(url, future=True)


def run_checks(engine) -> dict:
    results = {}
    with engine.connect() as conn:
        # Row counts
        tables = [
            "locations",
            "customer_accounts",
            "customers",
            "sellers",
            "products",
            "orders",
            "order_items",
        ]
        results["row_counts"] = {
            t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in tables
        }

        # Duplicate checks
        results["duplicate_violations"] = {
            "orders": conn.execute(
                text("SELECT COUNT(*) FROM (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*) > 1) x")
            ).scalar_one(),
            "order_items": conn.execute(
                text(
                    "SELECT COUNT(*) FROM (SELECT order_id, order_item_id FROM order_items "
                    "GROUP BY order_id, order_item_id HAVING COUNT(*) > 1) x"
                )
            ).scalar_one(),
        }

        # Referential checks
        results["orphan_violations"] = {
            "orders_to_customers": conn.execute(
                text("SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON o.customer_id = c.customer_id WHERE c.customer_id IS NULL")
            ).scalar_one(),
            "items_to_orders": conn.execute(
                text("SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o ON oi.order_id = o.order_id WHERE o.order_id IS NULL")
            ).scalar_one(),
            "items_to_products": conn.execute(
                text("SELECT COUNT(*) FROM order_items oi LEFT JOIN products p ON oi.product_id = p.product_id WHERE p.product_id IS NULL")
            ).scalar_one(),
            "items_to_sellers": conn.execute(
                text("SELECT COUNT(*) FROM order_items oi LEFT JOIN sellers s ON oi.seller_id = s.seller_id WHERE s.seller_id IS NULL")
            ).scalar_one(),
        }

        # Aggregate financial & domain-quality fingerprint
        agg = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS item_rows,
                    ROUND(SUM(price), 2)::TEXT AS sum_price,
                    ROUND(SUM(freight_value), 2)::TEXT AS sum_freight,
                    COUNT(*) FILTER (WHERE price < 0 OR freight_value < 0) AS negative_amounts
                FROM order_items
                """
            )
        ).mappings().one()
        results["measure_fingerprint"] = dict(agg)

        # Temporal sanity check: delivered timestamp should not precede purchase timestamp
        results["temporal_anomalies"] = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM orders
                WHERE order_delivered_customer_date IS NOT NULL
                  AND order_delivered_customer_date < order_purchase_timestamp
                """
            )
        ).scalar_one()

    return results


if __name__ == "__main__":
    engine = get_engine()
    report = run_checks(engine)
    print(json.dumps(report, indent=2))