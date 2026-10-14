from datetime import datetime
import gzip
import json
import logging
from pathlib import Path
import re
import time
from urllib.parse import unquote
from zoneinfo import ZoneInfo
import requests

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
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    })
    return session


def discover_products(session: requests.Session):
    sitemap_url = f"{BASE_URL}/sitemap.xml"
    response = session.get(sitemap_url, timeout=30)
    response.raise_for_status()

    pattern = re.compile(
        r"<loc>\s*(https?://glomark\.lk/[^<]*/p/(\d+))\s*</loc>",
        flags=re.IGNORECASE,
    )

    products = {}
    for url, product_id in pattern.findall(response.text):
        products[product_id] = {
            "product_id": product_id,
            "url": url,
            "name": _name_from_url(url),
        }

    return list(products.values())


def get_product_variation(session: requests.Session, product_id: str):
    url = f"{BASE_URL}/product-page/variation-detail/{product_id}"
    response = session.post(url, timeout=30)
    response.raise_for_status()
    return response.json()


def _to_float(value):
    if value is None:
        return None
    try:
        cleaned = (
            str(value)
            .replace(",", "")
            .replace("Rs.", "")
            .replace("Rs", "")
            .replace("LKR", "")
            .strip()
        )
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _extract_price_from_text(text: str):
    if not text or not isinstance(text, str):
        return None
    matches = re.findall(
        r"(?:Rs\.?|LKR)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)",
        text,
        flags=re.IGNORECASE,
    )
    for match in matches:
        val = _to_float(match)
        if val and val > 1.0:
            return val
    return None


def _extract_price(data):
    if isinstance(data, dict):
        preferred_keys = ["promoPrice", "price", "salePrice", "sellingPrice", "unitPrice", "finalPrice"]
        for key in preferred_keys:
            if key in data:
                val = _to_float(data[key])
                if val is not None and val > 0:
                    return val

        for html_key in ["html", "view", "content", "template"]:
            if html_key in data and isinstance(data[html_key], str):
                html_price = _extract_price_from_text(data[html_key])
                if html_price is not None:
                    return html_price

        for value in data.values():
            result = _extract_price(value)
            if result is not None:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _extract_price(item)
            if result is not None:
                return result
    return None


def _extract_original_price(data):
    if isinstance(data, dict):
        preferred_keys = ["originalPrice", "mrp", "regularPrice", "listPrice"]
        for key in preferred_keys:
            if key in data:
                val = _to_float(data[key])
                if val is not None and val > 0:
                    return val

        for value in data.values():
            result = _extract_original_price(value)
            if result is not None:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _extract_original_price(item)
            if result is not None:
                return result
    return None


def _name_from_url(url: str):
    match = re.search(r"glomark\.lk/(.+?)/p/(\d+)", url, flags=re.IGNORECASE)
    if not match:
        return None
    slug = unquote(unquote(match.group(1)))
    return slug.replace("-", " ").replace("_", " ").strip().title()


def scrape_glomark(request_delay: float = 0.4, max_products: int = None):
    session = _get_session()
    products = discover_products(session)
    logger.info("Product URLs discovered in sitemap: %d", len(products))

    if max_products is not None:
        products = products[:max_products]
        logger.info("Capping extraction to first %d items for testing", max_products)

    results = []
    observed_at = datetime.now(SL_TIMEZONE).isoformat()

    for index, product in enumerate(products, start=1):
        product_id = product["product_id"]

        try:
            data = get_product_variation(session, product_id)

            if isinstance(data, dict) and data.get("status") == 103:
                price = None
                original_price = None
                discount = None
                availability = "Discontinued"
                is_saleable = False
            else:
                price = _extract_price(data)
                original_price = _extract_original_price(data)
                if original_price and price and original_price > price:
                    discount = original_price - price
                else:
                    discount = None

                availability = "In Stock" if price is not None else "Out of Stock"
                is_saleable = price is not None

            record = {
                "store": "glomark",
                "product_id": str(product_id),
                "sku": None,
                "product_name": product.get("name"),
                "brand": None,
                "category": None,
                "unit_size": None,
                "uom": None,
                "pack_size": None,
                "price": price,
                "mrp": original_price,
                "discount": discount,
                "inventory": None,
                "availability": availability,
                "is_saleable": is_saleable,
                "max_order_quantity": None,
                "min_order_quantity": None,
                "image_url": None,
                "web_image_url": None,
                "category_code": None,
                "observed_at": observed_at,
                "source_url": product["url"],
            }
            results.append(record)

            if index % 50 == 0 or index == len(products):
                logger.info("Glomark progress: %d/%d scraped", index, len(products))

        except Exception as exc:
            logger.error("[%d/%d] ID=%s error: %s", index, len(products), product_id, exc)

        time.sleep(request_delay)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    # For full run, use max_products=None
    data = scrape_glomark(max_products=None)

    date_str = datetime.now(SL_TIMEZONE).strftime("%Y-%m-%d")
    output_dir = Path("data/raw/glomark")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{date_str}.json.gz"

    with gzip.open(out_file, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    logger.info("Complete! Saved %d items to %s", len(data), out_file)