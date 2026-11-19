from __future__ import annotations

import json
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from azure.core.exceptions import AzureError

from .config_loader import load_pack, load_pricing
from .export import export_csv, export_json, store_export
from .runner import ComparisonRunner
from .schemas import PublicConfig, RunRequest, RunSnapshot

ROOT = Path(__file__).resolve().parents[1]


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pack = load_pack(os.getenv("WEBIQ_PACK_FILE", ROOT / "config" / "packs" / "manufacturing.json"))
        pricing = load_pricing(os.getenv("WEBIQ_PRICING_FILE", ROOT / "config" / "pricing.json"))
        demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
        app.state.config = PublicConfig(pack=pack, pricing=pricing, demoMode=demo_mode)
        yield

    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(enable_live_metrics=True)

    application = FastAPI(title="Web IQ comparison API", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-correlation-id"],
    )

    @application.get("/api/config", response_model=PublicConfig)
    async def get_config(request: Request) -> PublicConfig:
        return request.app.state.config

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/api/runs")
    async def run_comparison(request: RunRequest, http_request: Request):
        config: PublicConfig = http_request.app.state.config
        if request.scopeName and request.scopeName != config.pack.scopeName:
            raise HTTPException(422, "設定済みスコープと一致しません")
        if request.presetId and request.presetId not in {p.id for p in config.pack.presets}:
            raise HTTPException(422, "不明なプリセットIDです")
        if request.allowedDomains and request.allowedDomains != config.pack.allowedDomains:
            raise HTTPException(422, "許可ドメインはパック設定で固定されています")
        request.allowedDomains = list(config.pack.allowedDomains)
        if request.scopeName and any(item not in {"web", "news"} for item in request.responseFilter):
            raise HTTPException(422, "スコープありではWebとNewsだけを指定できます")
        if request.scopeName and not request.allowedDomains:
            raise HTTPException(422, "スコープ指定時はパックにallowedDomainsが必要です")
        try:
            runner = ComparisonRunner(config.pack, config.pricing, config.demoMode)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))

        async def events():
            try:
                async for event in runner.stream(request):
                    yield f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"
            finally:
                await runner.close()

        return StreamingResponse(events(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        })

    @application.post("/api/export")
    async def export_snapshot(snapshot: RunSnapshot, format: str = Query("json", pattern="^(json|csv)$")):
        content = export_csv(snapshot) if format == "csv" else export_json(snapshot)
        try:
            await store_export(snapshot, format, content)
        except AzureError as exc:
            raise HTTPException(503, "書き出しファイルの保存に失敗しました") from exc
        safe_run_id = "".join(c for c in snapshot.runId if c.isalnum() or c in "-_")[:80] or "run"
        media_type = "text/csv; charset=utf-8" if format == "csv" else "application/json; charset=utf-8"
        return Response(content, media_type=media_type, headers={
            "Content-Disposition": f'attachment; filename="webiq-{safe_run_id}.{format}"',
            "X-Content-Type-Options": "nosniff",
        })

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        application.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return application


app = create_app()

