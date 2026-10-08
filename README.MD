# Sri Lankan Supermarket Price Intelligence Platform

An ongoing data engineering project for collecting, standardizing, historizing, and analyzing daily grocery prices from major Sri Lankan supermarket platforms.

The platform is designed to turn daily supermarket observations into a reusable analytical dataset for price comparison, price-history analysis, discount tracking, availability analysis, and future anomaly detection.

## Project Status

**Status:** 🚧 Ongoing

Current development has validated the main ingestion approaches for:

- **Cargills Online** — API-based product and price extraction
- **Glomark** — product discovery and product-price endpoint
- **Keells** — sitemap-based product discovery and browser-rendered product-page extraction using Playwright

The daily automated collection, cloud storage, dimensional warehouse, transformation, and analytics layers are being developed next.

---

## Problem

Supermarket prices can change over time, while publicly visible online supermarket catalogs are mainly designed for current shopping rather than historical analysis.

This project aims to create a structured historical dataset that can answer questions such as:

- Which supermarket currently offers the lowest price for a product?
- How has the price of a product changed over time?
- Which products experienced the largest price increases?
- Which products are frequently discounted?
- How do supermarket prices differ for the same or comparable products?
- Which products have unusual price movements?
- What would be the cheapest supermarket for a selected grocery basket?

---

## Architecture

```text
 ┌───────────┐   ┌───────────┐   ┌───────────┐
 │ Cargills  │   │  Glomark  │   │   Keells  │
 └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
       └───────────────┼───────────────┘
                       ▼
          ┌────────────────────────┐
          │    Python Ingestion    │
          │ Requests / Playwright  │
          └────────────┬───────────┘
                       ▼
          ┌────────────────────────┐
          │      Cloudflare R2     │
          │      Bronze / Raw      │
          └────────────┬───────────┘
                       ▼
          ┌────────────────────────┐
          │      Cleaning &        │
          │    Standardization     │
          └────────────┬───────────┘
                       ▼
          ┌────────────────────────┐
          │      Dimensional       │
          │     Data Warehouse     │
          │    (BigQuery target)   │
          └────────────┬───────────┘
                       ▼
          ┌────────────────────────┐
          │          dbt           │
          │   Transformations &    │
          │      Data Quality      │
          └────────────┬───────────┘
                       ▼
          ┌────────────────────────┐
          │        Power BI        │
          │       Analytics        │
          └────────────────────────┘

 GitHub Actions  ->  Daily ingestion
 Apache Airflow  ->  Planned for mature multi-stage orchestration
```

---

## Data Pipeline

### 1. Extract

Each supermarket has a different ingestion mechanism.

#### Cargills

Uses the Cargills Online backend endpoints to:

1. Establish a session
2. Retrieve categories
3. Retrieve products by category
4. Extract product and pricing attributes

#### Glomark

Uses product discovery from the site's available product URLs/sitemap and retrieves current product pricing from the product variation endpoint.

#### Keells

Uses the Keells sitemap to discover product `itemcode` values and Playwright/Chromium to load the JavaScript-rendered product pages.

The Keells ingestion currently extracts:

- Product ID / item code
- Product name
- Price
- Availability
- Saleability
- Source URL
- Observation timestamp

---

## 2. Raw / Bronze Layer

Raw daily observations will be stored in **Cloudflare R2**.

Example:

```text
bronze/
├── cargills/
│   ├── 2026-09-28.json.gz
│   ├── 2026-09-29.json.gz
│   └── ...
│
├── glomark/
│   ├── 2026-09-28.json.gz
│   ├── 2026-09-29.json.gz
│   └── ...
│
└── keells/
    ├── 2026-09-28.json.gz
    ├── 2026-09-29.json.gz
    └── ...
```

The raw layer is intended to preserve the observations as collected so that downstream transformations can be rerun without scraping the websites again.

---

## 3. Data Cleaning and Standardization

Different supermarkets expose different fields and naming conventions.

The pipeline will normalize records into a common schema such as:

```text
store
product_id
sku
product_name
brand
category
unit_size
uom
pack_size
price
mrp
discount
inventory
availability
is_saleable
observed_at
source_url
```

Data-quality rules will be applied in the transformation layer rather than silently deleting information during scraping.

Example:

```text
Raw observation
      ↓
Validation
      ├── Valid record
      └── Suspicious / rejected record
```

Suspicious records can be retained separately for auditing and investigation.

---

## 4. Product Standardization and Matching

The same product may appear differently across supermarkets.

Examples:

```text
Anchor Full Cream Milk Powder 400g
ANCHOR MILK POWDER 400 G
Anchor Full Cream Milk 400g
```

The project will gradually introduce product normalization and entity matching using:

- Text normalization
- Brand extraction
- Unit/weight normalization
- Category information
- Fuzzy matching
- Optional embedding-based matching in a future stage

This will allow meaningful cross-supermarket comparisons.

---

## 5. Dimensional Data Warehouse

The analytical warehouse will use a dimensional/star-schema design.

### Fact table

`fact_price`

```text
date_key
product_key
store_key
price
mrp
discount
availability
inventory
observed_at
```

### Dimensions

`dim_product`

```text
product_key
source_product_id
product_name
brand
category
unit_size
uom
```

`dim_store`

```text
store_key
store_name
```

`dim_date`

```text
date_key
date
day
month
quarter
year
```

A category dimension can also be introduced where useful.

This model is intended to support efficient analytical queries such as price trends, retailer comparisons, and basket analysis.

---

## 6. Historical Price Tracking

A key feature of the project is preserving daily observations rather than overwriting previous prices.

Example:

```text
Product: Anchor Milk Powder 400g

2026-09-28  Cargills  Rs 1050
2026-09-29  Cargills  Rs 1080
2026-09-30  Cargills  Rs 1080
2026-10-01  Cargills  Rs 1120
```

This makes the dataset useful for historical analysis rather than only current-price lookup.

---

## 7. Automation

### GitHub Actions

GitHub Actions will initially handle the daily ingestion schedule.

Planned flow:

```text
Scheduled workflow
      ↓
Run Cargills scraper
      ↓
Run Glomark scraper
      ↓
Run Keells scraper
      ↓
Generate dated raw snapshots
      ↓
Upload to Cloudflare R2
```

### Apache Airflow

Apache Airflow is planned for a later stage when the pipeline becomes more complex and requires multi-step dependency management, retries, monitoring, and DAG-based orchestration.

Airflow is therefore intentionally listed as a **planned technology**, rather than a currently implemented component.

---

## 8. Analytics

The final analytics layer will focus on questions such as:

### Price comparison

```text
Product → Cargills vs Glomark vs Keells
```

### Price history

```text
Product → price by day / week / month
```

### Discount analysis

- Discount frequency
- Discount amount
- Products with recurring promotions

### Availability

- In-stock vs out-of-stock patterns
- Availability changes over time

### Price movement

- Largest increases
- Largest decreases
- Volatility
- Unusual price changes

### Grocery basket analysis

For a selected basket:

```text
Basket
  ↓
Compare total estimated cost
  ↓
Cargills / Glomark / Keells
```

### Future ML / analytics

Potential future additions include:

- Price anomaly detection
- Short-term price forecasting
- Product-level price movement classification

---

## Technology Stack

| Layer | Technology |
|---|---|
| Programming | Python |
| HTTP/API ingestion | Requests |
| Browser automation | Playwright + Chromium |
| Data processing | Pandas |
| Raw object storage | Cloudflare R2 |
| CI/CD & scheduling | GitHub Actions |
| Data warehouse | Google BigQuery (target) |
| Transformation | dbt |
| BI / visualization | Power BI |
| Future orchestration | Apache Airflow |
| Version control | Git / GitHub |

---

## Repository Structure

```text
SL-retail-data-platform/
│
├── scrapers/
│   ├── __init__.py
│   ├── cargills.py
│   ├── glomark.py
│   └── keells.py
│
├── pipeline/
│   ├── __init__.py
│   ├── cleaning.py
│   ├── daily_ingestion.py
│   └── r2_uploader.py
│
├── data/
│   └── raw/
│
├── .github/
│   └── workflows/
│       └── daily_ingestion.yml
│
├── requirements.txt
└── README.md
```

---

## Development Roadmap

- [x] Validate Cargills ingestion approach
- [x] Validate Glomark ingestion approach
- [x] Validate Keells ingestion approach
- [x] Discover large Keells product catalog through sitemap
- [x] Test Keells product extraction with 100 records
- [ ] Standardize all three scraper outputs
- [ ] Implement reusable cleaning/validation layer
- [ ] Create Cloudflare R2 bucket and credentials
- [ ] Implement raw daily snapshot storage
- [ ] Implement GitHub Actions daily ingestion
- [ ] Collect historical observations over time
- [ ] Build product normalization
- [ ] Build cross-store product matching
- [ ] Design dimensional warehouse
- [ ] Load warehouse tables
- [ ] Implement dbt models and data-quality tests
- [ ] Build Power BI dashboard
- [ ] Add basket price comparison
- [ ] Add price anomaly detection
- [ ] Introduce Apache Airflow for mature orchestration

---

## Data Engineering Principles

The project is being designed around the following principles:

### Preserve raw data

Raw observations should remain available in the Bronze layer.

### Do not overwrite historical prices

Each daily observation should be timestamped and retained.

### Separate extraction from transformation

Scrapers collect source data; cleaning and business rules are applied downstream.

### Use a common schema

Different source formats are normalized before entering analytical models.

### Validate data quality

Missing prices, suspicious records, duplicate products, and unexpected source changes should be detected rather than silently ignored.

### Make ingestion reproducible

Daily runs should create deterministic, dated snapshots that can be processed again when required.

---

## Notes on Data Collection

This project is intended for educational and portfolio purposes.

The supermarket platforms are independent third-party services. Before large-scale or long-running collection is enabled, applicable website terms, access rules, robots directives, rate limits, and other usage restrictions should be reviewed.

The collectors should use conservative request rates and avoid bypassing authentication, CAPTCHA, or other access controls.

---

## Goals

The project is intended to demonstrate practical skills in:

- Data ingestion
- Web/API data collection
- Browser automation
- Data lake / object storage
- Data cleaning and validation
- Product entity resolution
- Historical data modeling
- Dimensional data warehousing
- SQL analytics
- Data transformation with dbt
- Workflow automation
- Business intelligence
- Scalable pipeline design

---

## Author

Built as an ongoing personal data engineering project focused on Sri Lankan retail price intelligence.
