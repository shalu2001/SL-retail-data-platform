from datetime import datetime
import gzip
import json
import logging
from pathlib import Path
import random
import time
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logger = logging.getLogger(__name__)
SL_TIMEZONE = ZoneInfo("Asia/Colombo")


class KeellsScraper:
    BASE_URL = "https://zebraliveback.keellssuper.com"

    def __init__(self, outlet_code: str = "SCDR    ", request_timeout: int = 25):
        self.outlet_code = outlet_code
        self.timeout = request_timeout
        self.session_id: Optional[str] = None
        self.session = self._init_session()

    def _init_session(self) -> requests.Session:
        """Configures a requests session with connection-level retries and standard headers."""
        session = requests.Session()
        session.headers.update({
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-GB,en;q=0.9",
            "origin": "https://www.keellssuper.com",
            "referer": "https://www.keellssuper.com/",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        })

        retries = Retry(
            total=4,
            backoff_factor=2,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

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

    def _fetch_page(self, page_no: int, items_per_page: int, max_retries: int = 4) -> Dict[str, Any]:
        """
        Fetches a single page with proactive backoff for HTTP 429 and automatic
        re-authentication on session expiry (401/403).
        """
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

        base_backoff = 15  # seconds

        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)

                # 1. Handle HTTP 429 Rate Limiting
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    wait_time = int(retry_after) if (retry_after and retry_after.isdigit()) else (base_backoff * attempt)
                    logger.warning(
                        "Keells returned 429 on page %d (Attempt %d/%d). Sleeping %ds before retry...",
                        page_no, attempt, max_retries, wait_time
                    )
                    time.sleep(wait_time)
                    continue

                # 2. Handle Session Expiry
                if resp.status_code in (401, 403):
                    logger.warning("Session expired (HTTP %d). Re-authenticating...", resp.status_code)
                    self.authenticate()
                    time.sleep(2)
                    continue

                resp.raise_for_status()
                payload = resp.json()

                # Internal status code check
                if payload.get("statusCode") in (401, 403):
                    logger.warning("Internal code %s. Re-authenticating...", payload.get("statusCode"))
                    self.authenticate()
                    time.sleep(2)
                    continue

                return payload

            except (requests.RequestException, ValueError) as err:
                logger.warning(
                    "Network error on Keells page %d (Attempt %d/%d): %s",
                    page_no, attempt, max_retries, err
                )
                time.sleep(4 * attempt)

        raise RuntimeError(f"Unable to fetch page {page_no} after {max_retries} retry attempts.")

    def run(self, items_per_page: int = 96, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Executes pagination across the Keells catalog.
        Returns a normalized record list conforming to the Bronze ingestion layer.
        """
        all_records = []
        current_page = 1
        total_pages = 1
        observed_at = datetime.now(SL_TIMEZONE).isoformat()

        logger.info("Initiating full catalog harvest for outlet: %s (batch size: %d)", self.outlet_code.strip(), items_per_page)

        while current_page <= total_pages:
            try:
                payload = self._fetch_page(page_no=current_page, items_per_page=items_per_page)
            except RuntimeError as err:
                logger.error("Pagination aborted on page %d: %s. Preserving %d items.", current_page, err, len(all_records))
                break

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

            # Safe throttle between pages with random jitter
            time.sleep(random.uniform(3.0, 4.5))

        logger.info("Keells scrape finished. Total records collected: %d", len(all_records))
        return all_records


def scrape_keells(items_per_page: int = 96, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
    """Helper entry point for pipeline/daily_ingestion.py"""
    scraper = KeellsScraper()
    return scraper.run(items_per_page=items_per_page, max_pages=max_pages)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    scraper = KeellsScraper()
    data = scraper.run(items_per_page=96, max_pages=None)

    date_str = datetime.now(SL_TIMEZONE).strftime("%Y-%m-%d")
    output_dir = Path("data/raw/keells")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{date_str}.json.gz"

    with gzip.open(out_file, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    logger.info("Complete! Saved %d items to %s", len(data), out_file)