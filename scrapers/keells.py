import asyncio
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import async_playwright


BASE_URL = "https://www.keellssuper.com"
SL_TIMEZONE = ZoneInfo("Asia/Colombo")


def discover_itemcodes():
    """
    Get Keells product itemcodes from sitemap.xml.
    """

    sitemap_url = (
        f"{BASE_URL}/sitemap.xml"
    )

    response = requests.get(
        sitemap_url,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        timeout=30
    )

    response.raise_for_status()

    html = response.text

    pattern = re.compile(
        r"<loc>\s*"
        r"https?://(?:www\.)?keellssuper\.com/"
        r"productDetail\?itemcode=(\d+)"
        r"(?:&amp;|&)([^<]+)"
        r"</loc>",
        flags=re.IGNORECASE
    )

    items = {}

    for itemcode, raw_name in pattern.findall(
        html
    ):

        name = (
            raw_name
            .replace("_", " ")
            .replace("%20", " ")
            .strip()
        )

        items[itemcode] = {
            "itemcode": itemcode,
            "name_from_sitemap": name,
        }

    return list(items.values())


async def scrape_product(
    page,
    itemcode,
    name_from_sitemap=None
):
    """
    Open one Keells product page in Chromium
    and extract name, price and availability.
    """

    url = (
        f"{BASE_URL}"
        f"/productDetail?itemcode={itemcode}"
    )

    try:

        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        if response is None:
            return None

        if response.status != 200:

            print(
                f"    HTTP {response.status}"
            )

            return {
                "store": "keells",
                "product_id": str(itemcode),
                "sku": str(itemcode),
                "product_name": name_from_sitemap,
                "price": None,
                "availability": "Unknown",
                "observed_at": (
                    datetime.now(
                        SL_TIMEZONE
                    ).isoformat()
                ),
                "source_url": url,
                "http_status": response.status,
            }

        # Wait for the rendered content
        await page.wait_for_timeout(
            2000
        )

        body_text = await page.locator(
            "body"
        ).inner_text()

        lines = [
            line.strip()
            for line in body_text.splitlines()
            if line.strip()
        ]

        # ----------------------------------
        # PRICE
        # ----------------------------------

        price = None
        product_name = None

        for index, line in enumerate(
            lines
        ):

            match = re.match(
                r"^Rs\.?\s*"
                r"([\d,]+(?:\.\d{1,2})?)$",
                line,
                flags=re.IGNORECASE
            )

            if match:

                price = float(
                    match.group(1)
                    .replace(",", "")
                )

                # Normally product name is
                # directly before the price.
                if index > 0:

                    candidate = lines[
                        index - 1
                    ]

                    # Avoid accidentally selecting
                    # generic navigation text.
                    if candidate not in [
                        "Home",
                        "Grocery",
                        "Login",
                        "Register"
                    ]:
                        product_name = candidate

                break

        # Fallback name
        if not product_name:
            product_name = (
                name_from_sitemap
            )

        # ----------------------------------
        # AVAILABILITY
        # ----------------------------------

        lower_text = body_text.lower()

        if "out of stock" in lower_text:

            availability = (
                "Out of Stock"
            )

        elif "add to cart" in lower_text:

            availability = (
                "In Stock"
            )

        else:

            availability = "Unknown"

        # ----------------------------------
        # RECORD
        # ----------------------------------

        return {
            "store": "keells",

            "product_id": str(itemcode),

            "sku": str(itemcode),

            "product_name": product_name,

            "brand": None,

            "category": None,

            "unit_size": None,

            "uom": None,

            "pack_size": None,

            "price": price,

            "mrp": None,

            "discount": None,

            "inventory": None,

            "availability": availability,

            "is_saleable": (
                True
                if availability == "In Stock"
                else (
                    False
                    if availability ==
                    "Out of Stock"
                    else None
                )
            ),

            "max_order_quantity": None,

            "min_order_quantity": None,

            "image_url": None,

            "web_image_url": None,

            "category_code": None,

            "observed_at": (
                datetime.now(
                    SL_TIMEZONE
                ).isoformat()
            ),

            "source_url": url,

            "http_status": response.status,
        }

    except Exception as exc:

        print(
            f"    ERROR {itemcode}: {exc}"
        )

        return {
            "store": "keells",
            "product_id": str(itemcode),
            "sku": str(itemcode),
            "product_name": name_from_sitemap,
            "price": None,
            "availability": "Unknown",
            "observed_at": (
                datetime.now(
                    SL_TIMEZONE
                ).isoformat()
            ),
            "source_url": url,
            "error": str(exc),
        }


async def scrape_keells(
    max_products=None,
    request_delay=1.0
):
    """
    Scrape Keells products using a browser.

    max_products:
        None = all discovered products.
        Use 10/20 while testing.
    """

    print("=" * 60)
    print("KEELLS SCRAPER")
    print("=" * 60)

    # ----------------------------------
    # 1. Discover itemcodes
    # ----------------------------------

    products = discover_itemcodes()

    print(
        f"Keells itemcodes discovered: "
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

    # ----------------------------------
    # 2. Open browser ONCE
    # ----------------------------------

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        context = await browser.new_context(
            viewport={
                "width": 1366,
                "height": 900
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/153.0.0.0 "
                "Safari/537.36"
            ),
        )

        page = await context.new_page()

        # ----------------------------------
        # 3. Scrape products
        # ----------------------------------

        for index, product in enumerate(
            products,
            start=1
        ):

            itemcode = product[
                "itemcode"
            ]

            print(
                f"[{index}/{len(products)}] "
                f"Itemcode={itemcode}"
            )

            record = await scrape_product(
                page,
                itemcode,
                product.get(
                    "name_from_sitemap"
                )
            )

            if record:

                results.append(record)

                print(
                    f"    "
                    f"{record.get('product_name')} | "
                    f"Rs {record.get('price')} | "
                    f"{record.get('availability')}"
                )

            await asyncio.sleep(
                request_delay
            )

        await browser.close()

    print()
    print(
        f"Keells records collected: "
        f"{len(results)}"
    )

    return results


if __name__ == "__main__":

    products = asyncio.run(
        scrape_keells(
            max_products=10
        )
    )

    print(
        f"Finished. Records: {len(products)}"
    )