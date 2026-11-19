import asyncio
import os
import re

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.clients import DemoModelClient, WebIQAdapter, _estimate_cost
from backend.schemas import Pack, Pricing, RunRequest


def test_demo_run_streams_three_independent_columns(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    with TestClient(create_app()) as client:
        response = client.post("/api/runs", json={
            "question": "製造業の規制動向を教えてください",
            "mode": "lite",
            "scopeName": "manufacturing-public-sources",
            "responseFilter": ["web", "news"],
        })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(re.findall(r"event: progress", response.text)) >= 3
    assert len(re.findall(r"event: result", response.text)) == 3
    assert len(re.findall(r"event: done", response.text)) == 3
    for column in ("A", "B", "C"):
        assert f'"columnId":"{column}"' in response.text


def test_scope_without_domains_is_rejected(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    with TestClient(create_app()) as client:
        response = client.post("/api/runs", json={"question": "質問", "scopeName": "scope"})
    assert response.status_code == 422


def test_cost_requires_actual_usage_and_configured_rates():
    pricing = Pricing(version="v", model={"inputPerMillionTokens": 2, "outputPerMillionTokens": 4},
                      search={"abPerRequest": 0.1})
    assert _estimate_cost(pricing, 1_000_000, 500_000, 2, "ab") == 4.2
    assert _estimate_cost(pricing, 1_000_000, 500_000, None, "ab") is None
    assert _estimate_cost(pricing, 1_000_000, 500_000, 2, "lite") is None


@pytest.mark.parametrize("missing_usage", [False, True])
def test_webiq_retry_accounts_for_all_model_calls(missing_usage):
    class RetryModel(DemoModelClient):
        def __init__(self):
            self.calls = 0

        async def run(self, *args, **kwargs):
            self.calls += 1
            usage = {"input_tokens": 100, "output_tokens": 50,
                     "output_tokens_details": {"reasoning_tokens": 10}}
            if self.calls == 1 and missing_usage:
                usage.pop("input_tokens")
            return {"output_text": "回答" if self.calls == 1 else "回答 [c-demo-1]", "usage": usage}

    model = RetryModel()
    pricing = Pricing(version="v", model={"inputPerMillionTokens": 2, "outputPerMillionTokens": 4},
                      search={"webIqLitePerRequest": 0.1})
    adapter = WebIQAdapter(model, Pack(id="p", title="p", presets=[]), pricing)

    async def emit(*args):
        pass

    result = asyncio.run(adapter.run(RunRequest(question="test"), emit))
    assert model.calls == 2
    assert result.metrics.outputTokens == 100
    assert result.metrics.reasoningTokens == 20
    if missing_usage:
        assert result.metrics.inputTokens is None
        assert result.metrics.estimatedCost is None
    else:
        assert result.metrics.inputTokens == 200
        assert result.metrics.estimatedCost == 0.1008

