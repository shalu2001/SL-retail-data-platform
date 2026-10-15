"""
scrapers/glomark.py
Extracts daily supermarket product prices and metadata from Glomark via internal AJAX department endpoints.
"""

from datetime import datetime
import gzip
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://glomark.lk"
SL_TIMEZONE = ZoneInfo("Asia/Colombo")


def _get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://glomark.lk/",
    })
    return session


def fetch_department_products(session: requests.Session, dep_id: int) -> Optional[Dict[str, Any]]:
    """Fetches full product payload for a specific department ID."""
    url = f"{BASE_URL}/ajax_products_by_department?depId={dep_id}"
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") is True and "data" in payload:
            return payload["data"]
    except Exception as e:
        logger.warning("Failed to fetch department %d: %s", dep_id, e)
    return None


def scrape_glomark(max_departments: int = 35, request_delay: float = 0.3) -> List[Dict[str, Any]]:
    """
    Iterates through all Glomark department IDs and flattens product lists
    into the standardized Bronze layer schema.
    """
    logger.info("=" * 50)
    logger.info("STARTING GLOMARK INGESTION (AJAX API)")
    logger.info("=" * 50)

    session = _get_session()
    all_records: Dict[str, Dict[str, Any]] = {}
    observed_at = datetime.now(SL_TIMEZONE).isoformat()

    for dep_id in range(1, max_departments + 1):
        data = fetch_department_products(session, dep_id)
        if not data:
            continue

        products = data.get("products_list", [])
        if not products:
            continue

        # Lookups provided by the response payload
        brands_map = {int(b["id"]): b["name"] for b in data.get("brands", {}).values() if "id" in b}
        categories_map = {int(c["id"]): c["name"] for c in data.get("categories", {}).values() if "id" in c}

        valid_count = 0
        for item in products:
            product_id = str(item.get("id"))
            sku = str(item.get("erpCode")) if item.get("erpCode") else product_id

            base_price = float(item.get("basePrice") or 0.0)
            promo_price = float(item.get("promoPrice") or base_price)
            discount_val = max(0.0, base_price - promo_price)

            brand_id = item.get("brand")
            cat_id = item.get("category")

            is_out_of_stock = bool(item.get("isOutOfStock"))
            stock_qty = float(item.get("stock") or 0.0)

            # Build standardized record matching Keells and Cargills
            record = {
                "store": "glomark",
                "product_id": product_id,
                "sku": sku,
                "product_name": item.get("name"),
                "brand": brands_map.get(brand_id),
                "category": categories_map.get(cat_id),
                "unit_size": None,  # Normalizable downstream
                "uom": item.get("unit"),
                "pack_size": None,
                "price": promo_price,
                "mrp": base_price,
                "discount": discount_val,
                "inventory": stock_qty,
                "availability": "Out of Stock" if is_out_of_stock else "In Stock",
                "is_saleable": not is_out_of_stock,
                "image_url": f"https://glomark.lk/images/products/{item.get('image')}" if item.get("image") else None,
                "source_url": f"https://glomark.lk/product/p/{product_id}",
                "observed_at": observed_at,
            }

            # Deduplicate by product ID or SKU
            all_records[product_id] = record
            valid_count += 1

        logger.info("DepID %02d: Harvested %d items (Total unique so far: %d)", dep_id, valid_count, len(all_records))
        time.sleep(request_delay)

    final_results = list(all_records.values())
    logger.info("Glomark ingestion finished. Total unique products: %d", len(final_results))
    return final_results


if __name__ == "__main__":
    data = scrape_glomark()

    date_str = datetime.now(SL_TIMEZONE).strftime("%Y-%m-%d")
    output_dir = Path("data/raw/glomark")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{date_str}.json.gz"

    with gzip.open(out_file, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    logger.info("Complete! Saved %d items to %s", len(data), out_file)