from __future__ import annotations

import csv
import io
import json
import os
from datetime import UTC, datetime

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient
from .schemas import RunSnapshot
from .security import spreadsheet_safe


def export_json(snapshot: RunSnapshot) -> bytes:
    return (json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def export_csv(snapshot: RunSnapshot) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["recordType", "columnId", "recordId", "title", "content", "url", "status", "metrics"])
    for column in snapshot.columns:
        writer.writerow(["column", column.columnId, spreadsheet_safe(snapshot.runId), spreadsheet_safe(column.label), spreadsheet_safe(column.answer),
                         "", column.status, json.dumps(column.metrics.model_dump(mode="json"), ensure_ascii=False)])
        for evidence in column.evidence:
            writer.writerow(["evidence", column.columnId, spreadsheet_safe(evidence.id), spreadsheet_safe(evidence.title),
                             spreadsheet_safe(evidence.text), evidence.url, column.status, ""])
        for citation in column.citations:
            writer.writerow(["citation", column.columnId, spreadsheet_safe(citation.id), spreadsheet_safe(citation.title),
                             spreadsheet_safe(citation.excerpt), citation.url, column.status, ""])
        if not column.evidence:
            writer.writerow(["evidence", column.columnId, "", "根拠なし", "", "", column.status, ""])
        if column.error:
            writer.writerow(["error", column.columnId, "", "", spreadsheet_safe(column.error.get("message", "")), "",
                             column.status, json.dumps(column.error, ensure_ascii=False)])
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


async def store_export(snapshot: RunSnapshot, format: str, content: bytes) -> None:
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    if not account_url:
        return
    safe_run_id = "".join(c for c in snapshot.runId if c.isalnum() or c in "-_")[:80] or "run"
    day = datetime.now(UTC).strftime("%Y/%m/%d")
    blob_name = f"{day}/{safe_run_id}.{format}"
    credential = DefaultAzureCredential()
    service = BlobServiceClient(account_url, credential=credential)
    try:
        blob = service.get_blob_client(
            container=os.getenv("EXPORT_CONTAINER", "exports"),
            blob=blob_name,
        )
        await blob.upload_blob(
            content,
            overwrite=True,
            metadata={"schemaVersion": "1", "pricingVersion": snapshot.pricingVersion or "unknown"},
        )
    finally:
        await service.close()
        await credential.close()
