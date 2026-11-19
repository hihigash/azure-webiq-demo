import asyncio
import pytest

from backend.clients import AdapterError, DemoModelClient, WebIQAdapter
from backend.schemas import Pack, Pricing, RunRequest


def test_scope_rejects_unapplied_scope(monkeypatch):
    pack = Pack(id="p", title="p", presets=[])
    pricing = Pricing(version="v", model={}, search={})
    adapter = WebIQAdapter(DemoModelClient(), pack, pricing)
    monkeypatch.setattr("backend.clients._demo_webiq", lambda request: {"scopeApplied": False, "results": []})
    async def emit(*args): pass
    with pytest.raises(AdapterError, match="適用できません"):
        asyncio.run(adapter.run(RunRequest(question="test", scopeName="scope", allowedDomains=["example.com"]), emit))


def test_scope_rejects_out_of_domain_result(monkeypatch):
    pack = Pack(id="p", title="p", presets=[])
    pricing = Pricing(version="v", model={}, search={})
    adapter = WebIQAdapter(DemoModelClient(), pack, pricing)
    monkeypatch.setattr("backend.clients._demo_webiq", lambda request: {
        "scopeApplied": True,
        "results": [{"evidence": {"id": "x", "url": "https://evil.example/e", "text": "x"}}],
    })
    async def emit(*args): pass
    with pytest.raises(AdapterError, match="スコープ外"):
        asyncio.run(adapter.run(RunRequest(question="test", scopeName="scope", allowedDomains=["example.com"]), emit))

