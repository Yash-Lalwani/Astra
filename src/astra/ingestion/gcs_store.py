"""Raw and processed files in GCS."""

import asyncio
import json
from functools import cache
from typing import Any

from google.cloud import storage

from astra.config import settings


def raw_study_path(nct_id: str) -> str:
    return f"raw/studies/{nct_id}.json"


def raw_paper_path(pmid: str) -> str:
    return f"raw/papers/{pmid}.xml"


def processed_study_path(nct_id: str) -> str:
    return f"processed/studies/{nct_id}.json"


def processed_paper_path(pmid: str) -> str:
    return f"processed/papers/{pmid}.json"


@cache
def _bucket() -> storage.Bucket:
    if not (settings.gcs_bucket and settings.gcs_credentials_json):
        raise RuntimeError("GCS_BUCKET and GCS_CREDENTIALS_JSON must be set")
    info = json.loads(settings.gcs_credentials_json)
    return storage.Client.from_service_account_info(info).bucket(settings.gcs_bucket)


async def save_text(path: str, text: str, content_type: str) -> None:
    blob = _bucket().blob(path)
    await asyncio.to_thread(blob.upload_from_string, text, content_type=content_type)


async def save_json(path: str, data: Any) -> None:
    await save_text(path, json.dumps(data, indent=2, default=str), "application/json")
