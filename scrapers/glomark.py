import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import unquote

import requests


BASE_URL = "https://glomark.lk"
SL_TIMEZONE = ZoneInfo("Asia/Colombo")


def _get_session():

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "application/json, text/javascript, "
            "*/*; q=0.01"
        ),
        "X-Requested-With": "XMLHttpRequest",
    })

    return session


def discover_products(session):
    """
    Discover Glomark product IDs from sitemap.xml.
    """

    sitemap_url = f"{BASE_URL}/sitemap.xml"

    response = session.get(
        sitemap_url,
        timeout=30
    )

    response.raise_for_status()

    html = response.text

    pattern = re.compile(
        r"<loc>\s*(https?://glomark\.lk/[^<]*/p/(\d+))\s*</loc>",
        flags=re.IGNORECASE
    )

    products = {}

    for url, product_id in pattern.findall(html):

        products[product_id] = {
            "product_id": product_id,
            "url": url,
            "name": _name_from_url(url),
        }

    return list(products.values())


def get_product_variation(
    session,
    product_id
):
    """
    Retrieve current variation/price data
    for a Glomark product.
    """

    url = (
        f"{BASE_URL}"
        f"/product-page/variation-detail/"
        f"{product_id}"
    )

    response = session.post(
        url,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


def _extract_price(data):
    """
    Recursively search JSON for likely price fields.
    """

    if isinstance(data, dict):

        preferred_keys = [
            "promoPrice",
            "price",
            "salePrice",
            "sellingPrice",
            "unitPrice",
        ]

        for key in preferred_keys:

            if key in data:

                value = _to_float(
                    data[key]
                )

                if value is not None:
                    return value

        # Search nested dictionaries
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
    """
    Try to find the non-promotional/original price.
    """

    if isinstance(data, dict):

        preferred_keys = [
            "originalPrice",
            "mrp",
            "regularPrice",
            "listPrice",
        ]

        for key in preferred_keys:

            if key in data:

                value = _to_float(
                    data[key]
                )

                if value is not None:
                    return value

        for value in data.values():

            result = _extract_original_price(
                value
            )

            if result is not None:
                return result

    elif isinstance(data, list):

        for item in data:

            result = _extract_original_price(
                item
            )

            if result is not None:
                return result

    return None


def _name_from_url(url):
    """
    Build a readable product name from
    the product URL slug.
    """

    match = re.search(
        r"glomark\.lk/(.+?)/p/\d+",
        url,
        flags=re.IGNORECASE
    )

    if not match:
        return None

    slug = match.group(1)

    slug = unquote(slug)

    return (
        slug
        .replace("-", " ")
        .replace("_", " ")
        .strip()
        .title()
    )


def scrape_glomark(
    request_delay=0.5,
    max_products=None
):
    """
    Scrape current Glomark product data.

    max_products:
        Use an integer during testing.
        None = scrape everything discovered.
    """

    print("=" * 60)
    print("GLOMARK SCRAPER")
    print("=" * 60)

    session = _get_session()

    # -----------------------------------------
    # 1. Discover product IDs
    # -----------------------------------------

    products = discover_products(
        session
    )

    print(
        f"Product URLs discovered: "
        f"{len(products)}"
    )

    if max_products is not None:

        products = products[
            :max_products
        ]

        print(
            f"Testing first {max_products}"
        )

    results = []

    # -----------------------------------------
    # 2. Get prices
    # -----------------------------------------

    for index, product in enumerate(
        products,
        start=1
    ):

        product_id = product[
            "product_id"
        ]

        print(
            f"[{index}/{len(products)}] "
            f"ID={product_id}"
        )

        try:

            data = get_product_variation(
                session,
                product_id
            )

            price = _extract_price(data)

            original_price = (
                _extract_original_price(
                    data
                )
            )

            if (
                original_price is not None
                and price is not None
                and original_price > price
            ):
                discount = (
                    original_price - price
                )
            else:
                discount = None

            observed_at = (
                datetime.now(SL_TIMEZONE)
                .isoformat()
            )

            record = {
                "store": "glomark",

                "product_id": str(
                    product_id
                ),

                "sku": None,

                "product_name": product.get(
                    "name"
                ),

                "brand": None,

                "category": None,

                "unit_size": None,

                "uom": None,

                "pack_size": None,

                "price": price,

                "mrp": original_price,

                "discount": discount,

                "inventory": None,

                "availability": "Unknown",

                "is_saleable": None,

                "max_order_quantity": None,

                "min_order_quantity": None,

                "image_url": None,

                "web_image_url": None,

                "category_code": None,

                "observed_at": observed_at,

                "source_url": product[
                    "url"
                ],
            }

            results.append(record)

            print(
                f"    Price: {price}"
            )

        except Exception as exc:

            print(
                f"    ERROR: {exc}"
            )

        time.sleep(request_delay)

    print()
    print(
        f"Glomark records collected: "
        f"{len(results)}"
    )

    return results


def _to_float(value):

    if value is None:
        return None

    try:

        return float(
            str(value)
            .replace(",", "")
            .replace("Rs.", "")
            .replace("Rs", "")
            .strip()
        )

    except (ValueError, TypeError):

        return None


if __name__ == "__main__":

    products = scrape_glomark(
        max_products=10
    )

    print(
        f"Finished. Records: {len(products)}"
    )