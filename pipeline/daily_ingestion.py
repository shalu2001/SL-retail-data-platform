from datetime import datetime
import gzip
import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from scrapers.cargills import scrape_cargills  # Adjust import based on function name
from scrapers.glomark import scrape_glomark
from scrapers.keells import KeellsScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("daily_ingestion")

SL_TZ = ZoneInfo("Asia/Colombo")


def save_bronze_snapshot(store_name: str, records: list, date_str: str) -> Path:
    """Saves raw snapshot as json.gz matching the Bronze lake architecture."""
    output_dir = Path(f"data/raw/{store_name}")
    output_dir.mkdir(parents=True, exist_ok=True)

    file_path = output_dir / f"{date_str}.json.gz"
    with gzip.open(file_path, "wt", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)

    logger.info("Saved %d records to %s", len(records), file_path)
    return file_path


def main():
    date_str = datetime.now(SL_TZ).strftime("%Y-%m-%d")
    logger.info("Starting Daily Ingestion for: %s", date_str)

    # 1. Keells
    try:
        logger.info("Scraping Keells...")
        keells_client = KeellsScraper()
        keells_data = keells_client.run(items_per_page=48, max_pages=None)
        save_bronze_snapshot("keells", keells_data, date_str)
    except Exception as e:
        logger.error("Keells scraping failed: %s", e)

    # 2. Glomark
    try:
        logger.info("Scraping Glomark...")
        glomark_data = scrape_glomark()
        save_bronze_snapshot("glomark", glomark_data, date_str)
    except Exception as e:
        logger.error("Glomark scraping failed: %s", e)

    # 3. Cargills
    try:
        logger.info("Scraping Cargills...")
        cargills_data = scrape_cargills()
        save_bronze_snapshot("cargills", cargills_data, date_str)
    except Exception as e:
        logger.error("Cargills scraping failed: %s", e)

    logger.info("Daily Ingestion complete.")


if __name__ == "__main__":
    main()