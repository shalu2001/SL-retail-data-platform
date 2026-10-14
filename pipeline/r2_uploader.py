import logging
import os
from pathlib import Path
from typing import Optional
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_r2_client():
    """Initializes and returns a boto3 S3 client configured for Cloudflare R2."""
    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key_id = os.environ.get("R2_ACCESS_KEY_ID")
    secret_access_key = os.environ.get("R2_SECRET_ACCESS_KEY")

    if not all([account_id, access_key_id, secret_access_key]):
        missing = [
            k for k, v in {
                "R2_ACCOUNT_ID": account_id,
                "R2_ACCESS_KEY_ID": access_key_id,
                "R2_SECRET_ACCESS_KEY": secret_access_key,
            }.items() if not v
        ]
        raise ValueError(f"Missing required Cloudflare R2 environment variables: {missing}")

    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_bronze_directory(
    local_dir: str = "data/raw",
    bucket_name: Optional[str] = None
) -> int:
    """
    Finds all compressed raw snapshot files in data/raw and uploads them to the Bronze bucket.
    Object key structure: bronze/{store}/{filename}
    """
    bucket = bucket_name or os.environ.get("R2_BUCKET_NAME")
    if not bucket:
        raise ValueError("Bucket name must be provided or set via R2_BUCKET_NAME environment variable.")

    base_path = Path(local_dir)
    if not base_path.exists():
        logger.warning("Local raw data directory '%s' does not exist. Nothing to upload.", local_dir)
        return 0

    client = get_r2_client()
    uploaded_count = 0

    # Look for both .json.gz and .csv.gz snapshots
    files_to_upload = list(base_path.rglob("*.json.gz")) + list(base_path.rglob("*.csv.gz"))

    if not files_to_upload:
        logger.warning("No snapshot files (.json.gz / .csv.gz) found inside '%s'.", local_dir)
        return 0

    for file_path in files_to_upload:
        # relative_path -> e.g. "keells/2026-10-14.json.gz"
        relative_path = file_path.relative_to(base_path)
        r2_key = f"bronze/{relative_path.as_posix()}"

        logger.info("Uploading %s -> r2://%s/%s", file_path, bucket, r2_key)
        try:
            client.upload_file(
                Filename=str(file_path),
                Bucket=bucket,
                Key=r2_key,
                ExtraArgs={"ContentType": "application/gzip"}
            )
            uploaded_count += 1
            logger.info("Successfully uploaded %s", r2_key)
        except ClientError as e:
            logger.error("Failed to upload %s: %s", file_path, e)
            raise

    logger.info("Bronze upload finished. Total files uploaded: %d", uploaded_count)
    return uploaded_count


if __name__ == "__main__":
    upload_bronze_directory()