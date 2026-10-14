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

BASE_URL = "https://cargillsonline.com"
SL_TIMEZONE = ZoneInfo("Asia/Colombo")


def _get_session() -> requests.Session:
    """Create a requests session with standard browser headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    })
    return session


def establish_session(session: requests.Session, pin_code: str = "Colombo") -> Dict[str, Any]:
    """Establish the ASP.NET session used by Cargills Online."""
    url = f"{BASE_URL}/Web/CheckDeliveryOptionV1/"
    response = session.post(
        url,
        json={"PinCode": pin_code},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()

    session_cookie = session.cookies.get("ASP.NET_SessionId")
    if not session_cookie:
        raise RuntimeError("Cargills session was not established. ASP.NET_SessionId cookie not found.")

    logger.info("Cargills session established successfully (PinCode: %s).", pin_code)
    return response.json()


def get_categories(session: requests.Session) -> List[Dict[str, Any]]:
    """Retrieve all top-level and sub categories."""
    url = f"{BASE_URL}/Web/GetCategoriesV1/"
    response = session.post(
        url,
        json={},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected category response type: {type(data)}")

    return data


def get_products_by_category(session: requests.Session, category_en_id: str, page_size: int = 10000) -> List[Dict[str, Any]]:
    """Retrieve products belonging to one Cargills category."""
    url = f"{BASE_URL}/Web/GetMenuCategoryItemsPagingV3/"
    payload = {
        "CategoryId": category_en_id,
        "Search": "",
        "Filter": "",
        "PageIndex": 1,
        "PageSize": page_size,
        "BannerId": "",
        "SectionId": "",
        "CollectionId": "",
        "SectionType": "",
        "DataType": "",
        "SubCatId": "",
        "PromoId": "",
    }

    response = session.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    text = response.text

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Strip potential illegal ASCII control characters from legacy ASP.NET payloads
        cleaned = "".join(char if ord(char) >= 32 or char in "\n\r\t" else " " for char in text)
        data = json.loads(cleaned)

    if not isinstance(data, list):
        return []

    return data


def _to_float(value: Any) -> Optional[float]:
    """Safely convert numeric or formatted string values to float."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("Rs.", "").replace("Rs", "").strip())
    except (ValueError, TypeError):
        return None


def scrape_cargills(
    pin_code: str = "Colombo",
    page_size: int = 10000,
    category_delay: float = 0.5,
    max_categories: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Scrapes product records across all Cargills categories.
    Returns a normalized record list conforming to the Bronze ingestion layer.
    """
    session = _get_session()

    logger.info("=" * 50)
    logger.info("STARTING CARGILLS INGESTION")
    logger.info("=" * 50)

    establish_session(session, pin_code=pin_code)

    logger.info("Fetching categories...")
    categories = get_categories(session)
    logger.info("Found %d categories.", len(categories))

    if max_categories:
        categories = categories[:max_categories]
        logger.info("Capping extraction to first %d categories for testing.", max_categories)

    records: Dict[str, Dict[str, Any]] = {}
    observed_at = datetime.now(SL_TIMEZONE).isoformat()

    for index, category in enumerate(categories, start=1):
        category_name = (
            category.get("MenuCategoryName")
            or category.get("EnMenuCategoryName")
            or "Unknown"
        )
        category_en_id = category.get("EnId")

        if not category_en_id:
            logger.warning("[%d/%d] Skipping %s: missing EnId", index, len(categories), category_name)
            continue

        try:
            products = get_products_by_category(session, category_en_id, page_size=page_size)

            if not products:
                continue

            # Check for dummy "No Products Found" placeholder
            if isinstance(products[0], dict) and products[0].get("ItemName") == "No Products Found":
                continue

            for product in products:
                sku = product.get("SKUCODE")
                product_id = product.get("Id")
                product_name = product.get("ItemName")

                if not sku or not product_name:
                    continue

                raw_price = _to_float(product.get("Price"))
                raw_mrp = _to_float(product.get("Mrp"))
                discount_val = _to_float(product.get("DiscountAmount")) or 0.0

                is_saleable = str(product.get("IsSaleable", "")).lower() == "true"

                record = {
                    "store": "cargills",
                    "product_id": str(product_id) if product_id is not None else None,
                    "sku": str(sku),
                    "product_name": product_name,
                    "brand": None,  # Extracted downstream in cleaning.py
                    "category": category_name,
                    "unit_size": product.get("UnitSize"),
                    "uom": product.get("UOM"),
                    "pack_size": product.get("PackSize"),
                    "price": raw_price,
                    "mrp": raw_mrp if raw_mrp is not None else raw_price,
                    "discount": discount_val if discount_val > 0 else 0.0,
                    "inventory": product.get("Inventory"),
                    "availability": "In Stock" if is_saleable else "Out of Stock",
                    "is_saleable": is_saleable,
                    "max_order_quantity": product.get("MaxOrderQuantity"),
                    "min_order_quantity": _to_float(product.get("MinOrderQuantity")),
                    "image_url": product.get("ItemImage"),
                    "web_image_url": product.get("WebImage"),
                    "category_code": product.get("CategoryCode"),
                    "observed_at": observed_at,
                    "source_url": f"{BASE_URL}/product/{sku}",
                }

                # Deduplicate by SKU across categories
                records[str(sku)] = record

            logger.info(
                "[%d/%d] Scraped '%s' -> %d items (Total unique so far: %d)",
                index,
                len(categories),
                category_name,
                len(products),
                len(records),
            )

        except Exception as exc:
            logger.error("[%d/%d] Error scraping category '%s': %s", index, len(categories), category_name, exc)

        time.sleep(category_delay)

    all_items = list(records.values())
    logger.info("Cargills ingestion complete. Total unique products: %d", len(all_items))
    return all_items


if __name__ == "__main__":
    # Scrapes all categories and saves a daily Bronze snapshot
    data = scrape_cargills(pin_code="Colombo", page_size=10000, category_delay=0.5)

    date_str = datetime.now(SL_TIMEZONE).strftime("%Y-%m-%d")
    output_dir = Path("data/raw/cargills")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{date_str}.json.gz"

    with gzip.open(out_file, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    logger.info("Saved %d records to %s", len(data), out_file)