from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator

from .clients import AdapterError, DemoModelClient, ResponseAdapter, SharedModelClient, WebIQAdapter
from .schemas import ColumnResult, Metrics, Pack, Pricing, RunEvent, RunRequest

logger = logging.getLogger(__name__)


class ComparisonRunner:
    def __init__(self, pack: Pack, pricing: Pricing, demo_mode: bool):
        model = DemoModelClient() if demo_mode else SharedModelClient()
        if not demo_mode and not model.available:
            raise RuntimeError("Azure資格情報がありません。DEMO_MODE=trueを設定するか、Managed Identityを構成してください。")
        self.model = model
        self.responses = ResponseAdapter(model, pack, pricing)
        self.webiq = WebIQAdapter(model, pack, pricing)

    async def stream(self, request: RunRequest) -> AsyncIterator[RunEvent]:
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        sequences = {"A": 0, "B": 0, "C": 0}
        started = time.perf_counter()

        async def emit(column: str, event: str, message: str | None = None, result: ColumnResult | None = None):
            sequences[column] += 1
            await queue.put(RunEvent(event=event, columnId=column, sequence=sequences[column],
                elapsedMs=int((time.perf_counter()-started)*1000), message=message, result=result))

        async def work(column: str):
            async def send(event: str, message: str, result: ColumnResult | None = None):
                await emit(column, event, message, result)
            try:
                timeout = float(os.getenv("COLUMN_TIMEOUT_SECONDS", "120"))
                operation = (self.webiq.run(request, send) if column == "C"
                             else self.responses.search_column(request, column, send))
                try:
                    result = await asyncio.wait_for(operation, timeout=timeout)
                except TimeoutError as exc:
                    raise AdapterError("COLUMN_TIMEOUT", "列の処理がタイムアウトしました") from exc
                await emit(column, "result", result=result)
            except Exception as exc:
                code = exc.code if isinstance(exc, AdapterError) else f"COLUMN_FAILED_{type(exc).__name__}"
                message = exc.message if isinstance(exc, AdapterError) else "列の処理に失敗しました"
                logger.warning(
                    "Comparison column failed: column=%s code=%s exception_type=%s status=%s",
                    column,
                    code,
                    type(exc).__name__,
                    getattr(exc, "status_code", None),
                )
                result = ColumnResult(
                    columnId=column,
                    label={"A": "検索制限なし", "B": "許可ドメイン限定", "C": "Web IQ Auto"}[column],
                    status="error",
                    metrics=Metrics(
                        elapsedMs=int((time.perf_counter() - started) * 1000),
                        unavailableFields=[
                            "inputTokens", "outputTokens", "reasoningTokens",
                            "searchRequests", "estimatedCost",
                        ],
                    ),
                    error={"code": code, "message": message},
                )
                await emit(column, "result", result=result)
                await emit(column, "error", f"{code}: {message}")
            finally:
                await emit(column, "done")

        tasks = [asyncio.create_task(work(column)) for column in ("A", "B", "C")]
        try:
            done_count = 0
            while done_count < 3:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    done_count += int(event.event == "done")
                    yield event
                except TimeoutError:
                    for column in ("A", "B", "C"):
                        if not tasks[("A", "B", "C").index(column)].done():
                            yield RunEvent(event="progress", columnId=column, sequence=sequences[column],
                                           elapsedMs=int((time.perf_counter()-started)*1000), message="処理中")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        await self.model.close()
