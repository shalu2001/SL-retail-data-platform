from datetime import datetime, timezone
import gzip
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import requests
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
import random

logger = logging.getLogger(__name__)
SL_TIMEZONE = ZoneInfo("Asia/Colombo")


class KeellsScraper:
    BASE_URL = "https://zebraliveback.keellssuper.com"

    def __init__(self, outlet_code: str = "SCDR    ", request_timeout: int = 20):
        self.outlet_code = outlet_code
        self.timeout = request_timeout
        self.session = requests.Session()
        self.session_id: Optional[str] = None

        self.session.headers.update({
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-GB,en;q=0.9",
            "origin": "https://www.keellssuper.com",
            "referer": "https://www.keellssuper.com/",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        })

    def authenticate(self) -> str:
        """Obtains a new guest userSessionID from the backend login service."""
        url = f"{self.BASE_URL}/1.0/Login/GuestLogin"
        logger.info("Requesting fresh guest session token...")

        resp = self.session.post(url, headers={"content-length": "0"}, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        session_id = data.get("result", {}).get("userSessionID")
        if not session_id:
            raise ValueError(f"Failed to extract userSessionID from GuestLogin: {data}")

        self.session_id = session_id
        self.session.headers["usersessionid"] = self.session_id
        self.session.headers["sessionid"] = self.session_id
        logger.info("Acquired Keells session: %s", self.session_id)
        return self.session_id

    def _fetch_page(self, page_no: int, items_per_page: int) -> Dict[str, Any]:
        """Fetches a page with retry logic for handling unexpected session expiry."""
        if not self.session_id:
            self.authenticate()

        url = f"{self.BASE_URL}/2.0/WebV2/GetItemDetails"
        params = {
            "pageNo": page_no,
            "itemsPerPage": items_per_page,
            "outletCode": self.outlet_code,
            "departmentId": "",
            "subDepartmentId": "",
            "categoryId": "",
            "itemDescription": "    ",
            "itemPricefrom": 0,
            "itemPriceTo": 500000,
            "isFeatured": 0,
            "isPromotionOnly": "false    ",
            "promotionCategory": "",
            "sortBy": "default",
            "BrandId": "",
            "storeName": "    ",
            "subDeaprtmentCode": "",
            "isShowOutofStockItems": "true",
            "brandName": "",
        }

        for attempt in range(2):
            resp = self.session.get(url, params=params, timeout=self.timeout)

            if resp.status_code in (401, 403):
                logger.warning("Received HTTP %d. Re-authenticating session...", resp.status_code)
                self.authenticate()
                continue

            resp.raise_for_status()
            payload = resp.json()

            if payload.get("statusCode") in (401, 403):
                logger.warning("Internal status code %d returned. Re-authenticating...", payload.get("statusCode"))
                self.authenticate()
                continue

            return payload

        raise RuntimeError(f"Unable to fetch page {page_no} after retry attempts.")

    def run(self, items_per_page: int = 48, max_pages: Optional[int] = None, delay_seconds: float = 0.4) -> List[Dict[str, Any]]:
        """
        Executes pagination across the entire store catalog.
        Returns a normalized record list conforming to the Bronze ingestion layer.
        """
        all_records = []
        current_page = 1
        total_pages = 1
        observed_at = datetime.now(SL_TIMEZONE).isoformat()

        logger.info("Initiating full catalog harvest for outlet: %s", self.outlet_code.strip())

        while current_page <= total_pages:
            payload = self._fetch_page(page_no=current_page, items_per_page=items_per_page)

            detail_result = payload.get("result", {}).get("itemDetailResult", {})
            total_pages = detail_result.get("pageCount", 1)
            raw_items = detail_result.get("itemDetails", [])

            if max_pages:
                total_pages = min(total_pages, max_pages)

            for item in raw_items:
                raw_price = float(item.get("amount") or 0.0)
                discount_val = float(item.get("discountValue") or 0.0)

                record = {
                    "store": "keells",
                    "product_id": str(item.get("itemID")),
                    "sku": str(item.get("itemCode")),
                    "product_name": item.get("name"),
                    "brand": None,
                    "category": item.get("categoryCode"),
                    "unit_size": None,
                    "uom": item.get("uom"),
                    "pack_size": None,
                    "price": raw_price - discount_val if discount_val > 0 else raw_price,
                    "mrp": raw_price,
                    "discount": discount_val,
                    "inventory": float(item.get("stockInHand") or 0.0),
                    "availability": "In Stock" if bool(item.get("isAvailable")) else "Out of Stock",
                    "is_saleable": bool(item.get("isSellingToday")),
                    "observed_at": observed_at,
                    "source_url": f"https://www.keellssuper.com/product/{item.get('itemCode')}",
                    "image_url": item.get("imageUrl"),
                }
                all_records.append(record)

            logger.info("Scraped Page %d/%d (Total collected: %d)", current_page, total_pages, len(all_records))
            current_page += 1
            time.sleep(random.uniform(1.8, 2.5))

        return all_records


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    scraper = KeellsScraper()
    data = scraper.run(items_per_page=48, max_pages=None)

    # Automatically save snapshot to data/raw/keells/YYYY-MM-DD.json.gz
    date_str = datetime.now(SL_TIMEZONE).strftime("%Y-%m-%d")
    output_dir = Path("data/raw/keells")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{date_str}.json.gz"

    with gzip.open(out_file, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    logger.info("Complete! Saved %d items to %s", len(data), out_file)

def _get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.keellssuper.com",
        "Referer": "https://www.keellssuper.com/",
    })
    
    # Configure retry logic for rate limits and transient server errors
    retries = Retry(
        total=5,
        backoff_factor=2,  # Wait 2s, 4s, 8s, 16s...
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session