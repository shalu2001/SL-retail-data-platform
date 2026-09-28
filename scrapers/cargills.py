import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


BASE_URL = "https://cargillsonline.com"
SL_TIMEZONE = ZoneInfo("Asia/Colombo")


def _get_session():
    """
    Create a requests session with basic browser-like headers.
    """
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    })

    return session


def establish_session(session, pin_code="Colombo"):
    """
    Establish the ASP.NET session used by Cargills Online.
    """

    url = f"{BASE_URL}/Web/CheckDeliveryOptionV1/"

    response = session.post(
        url,
        json={"PinCode": pin_code},
        headers={
            "Content-Type": "application/json"
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    # requests.Session automatically stores Set-Cookie.
    # We verify that the Cargills session cookie exists.
    session_cookie = session.cookies.get("ASP.NET_SessionId")

    if not session_cookie:
        raise RuntimeError(
            "Cargills session was not established. "
            "ASP.NET_SessionId cookie not found."
        )

    print("Cargills session established.")

    return data


def get_categories(session):
    """
    Retrieve all Cargills categories.
    """

    url = f"{BASE_URL}/Web/GetCategoriesV1/"

    response = session.post(
        url,
        json={},
        headers={
            "Content-Type": "application/json"
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError(
            f"Unexpected category response type: {type(data)}"
        )

    return data


def get_products_by_category(session, category_en_id, page_size=10000):
    """
    Retrieve products belonging to one Cargills category.
    """

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
        headers={
            "Content-Type": "application/json"
        },
        timeout=60,
    )

    response.raise_for_status()

    text = response.text

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some responses can contain control characters.
        cleaned = "".join(
            char if ord(char) >= 32 or char in "\n\r\t" else " "
            for char in text
        )

        data = json.loads(cleaned)

    if not isinstance(data, list):
        return []

    return data


def scrape_cargills(
    pin_code="Colombo",
    page_size=10000,
    category_delay=0.7
):
    """
    Scrape current Cargills product data.

    Returns:
        list[dict]
    """

    session = _get_session()

    # -----------------------------------------
    # 1. Establish session
    # -----------------------------------------

    print("=" * 60)
    print("CARGILLS SCRAPER")
    print("=" * 60)

    establish_session(
        session,
        pin_code=pin_code
    )

    # -----------------------------------------
    # 2. Get categories
    # -----------------------------------------

    print("Fetching categories...")

    categories = get_categories(session)

    print(
        f"Categories found: {len(categories)}"
    )

    records = {}

    # -----------------------------------------
    # 3. Scrape every category
    # -----------------------------------------

    for index, category in enumerate(
        categories,
        start=1
    ):

        category_name = (
            category.get("MenuCategoryName")
            or category.get("EnMenuCategoryName")
            or "Unknown"
        )

        category_en_id = category.get("EnId")

        if not category_en_id:
            print(
                f"[{index}/{len(categories)}] "
                f"Skipping {category_name}: no EnId"
            )
            continue

        print(
            f"[{index}/{len(categories)}] "
            f"Scraping: {category_name}"
        )

        try:

            products = get_products_by_category(
                session,
                category_en_id,
                page_size=page_size
            )

            if not products:
                print("  No products found.")
                continue

            # Cargills sometimes returns a "No Products Found" record
            if (
                isinstance(products[0], dict)
                and products[0].get("ItemName")
                == "No Products Found"
            ):
                print("  No products found.")
                continue

            valid_count = 0

            for product in products:

                sku = product.get("SKUCODE")
                product_id = product.get("Id")
                product_name = product.get("ItemName")

                if not sku or not product_name:
                    continue

                observed_at = (
                    datetime.now(SL_TIMEZONE)
                    .isoformat()
                )

                record = {
                    "store": "cargills",

                    "product_id": str(
                        product_id
                    ) if product_id is not None else None,

                    "sku": str(sku),

                    "product_name": product_name,

                    "brand": None,

                    "category": category_name,

                    "unit_size": product.get(
                        "UnitSize"
                    ),

                    "uom": product.get(
                        "UOM"
                    ),

                    "pack_size": product.get(
                        "PackSize"
                    ),

                    "price": _to_float(
                        product.get("Price")
                    ),

                    "mrp": _to_float(
                        product.get("Mrp")
                    ),

                    "discount": _to_float(
                        product.get(
                            "DiscountAmount"
                        )
                    ),

                    "inventory": product.get(
                        "Inventory"
                    ),

                    "availability": (
                        "In Stock"
                        if str(
                            product.get(
                                "IsSaleable",
                                ""
                            )
                        ).lower()
                        == "true"
                        else "Out of Stock"
                    ),

                    "is_saleable": product.get(
                        "IsSaleable"
                    ),

                    "max_order_quantity": product.get(
                        "MaxOrderQuantity"
                    ),

                    "min_order_quantity": _to_float(
                        product.get(
                            "MinOrderQuantity"
                        )
                    ),

                    "image_url": product.get(
                        "ItemImage"
                    ),

                    "web_image_url": product.get(
                        "WebImage"
                    ),

                    "category_code": product.get(
                        "CategoryCode"
                    ),

                    "observed_at": observed_at,
                }

                # Use SKU as natural product key
                records[str(sku)] = record

                valid_count += 1

            print(
                f"  Products received: {len(products)}"
            )

            print(
                f"  Valid products: {valid_count}"
            )

        except Exception as exc:

            print(
                f"  ERROR: {category_name}: {exc}"
            )

        # Respectful delay
        time.sleep(category_delay)

    result = list(records.values())

    print()
    print(
        f"Cargills total unique products: "
        f"{len(result)}"
    )

    return result


def _to_float(value):
    """
    Safely convert numeric/string values to float.
    """

    if value is None:
        return None

    try:
        return float(
            str(value).replace(",", "").strip()
        )
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":

    products = scrape_cargills()

    print(
        f"Finished. Records: {len(products)}"
    )