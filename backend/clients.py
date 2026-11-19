from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Callable

import httpx
from urllib.parse import urlsplit
from azure.identity.aio import DefaultAzureCredential
from openai import AsyncAzureOpenAI, BadRequestError, RateLimitError

from .schemas import Citation, ColumnResult, Evidence, Metrics, Pack, RunRequest
from .security import classify_url, host_allowed, safe_http_url

Labeler = Callable[[str], str]


def _values(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, str, int, float, bool)):
        return value
    return value.model_dump() if hasattr(value, "model_dump") else value.__dict__


class AdapterError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


class SharedModelClient:
    def __init__(self) -> None:
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self._credential: DefaultAzureCredential | None = None
        self.client: AsyncAzureOpenAI | None = None

    @property
    def available(self) -> bool:
        # DefaultAzureCredential can use a host-provided Managed Identity without
        # AZURE_* variables. Only endpoint and deployment must be explicit.
        return bool(self.endpoint and self.deployment)

    async def _token_provider(self) -> str:
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        token = await self._credential.get_token("https://cognitiveservices.azure.com/.default")
        return token.token

    async def _client(self) -> AsyncAzureOpenAI:
        if self.client is None:
            kwargs = {
                "azure_endpoint": self.endpoint,
                "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            else:
                kwargs["azure_ad_token_provider"] = self._token_provider
            self.client = AsyncAzureOpenAI(**kwargs)
        return self.client

    async def run(self, request: RunRequest, column: str, evidence: list[dict] | None = None, allowed_domains: list[str] | None = None) -> Any:
        client = await self._client()
        if evidence is None:
            tool: dict[str, Any] = {"type": "web_search"}
            if allowed_domains:
                tool["filters"] = {
                    "allowed_domains": list(dict.fromkeys(domain.split("/", 1)[0] for domain in allowed_domains))
                }
            instructions = (
                "回答前に必ずweb_searchツールを1回以上使用してください。必ず質問に直接答え、日本語で簡潔に回答してください。根拠内だけで答え、引用URLを回答の出典として付けてください。"
                "取得できない事実は推測せず「取得不可」としてください。"
            )
            request_body = {
                "model": self.deployment,
                "instructions": instructions,
                "input": request.question,
                "tools": [tool],
                "tool_choice": "auto",
                "include": ["web_search_call.action.sources", "web_search_call.results"],
            }
            try:
                return await client.responses.create(**request_body)
            except BadRequestError as exc:
                error_text = str(exc.body or exc)
                if "web_search_call.results" in error_text:
                    request_body["include"] = ["web_search_call.action.sources"]
                    try:
                        return await client.responses.create(**request_body)
                    except BadRequestError:
                        pass
                category = "DOMAIN_FILTER" if "allowed_domains" in error_text else "WEB_SEARCH_REQUEST"
                error_code = str(getattr(exc, "code", "") or "").replace("-", "_").upper()
                error_param = str(getattr(exc, "param", "") or "").replace("[", "_").replace("]", "").replace(".", "_").upper()
                raise AdapterError(
                    "_".join(part for part in ("FOUNDRY", category, error_code, error_param) if part),
                    "FoundryのWeb検索要求が受け付けられませんでした",
                ) from exc
            except RateLimitError as exc:
                for attempt, fallback_delay in enumerate((2, 5, 10), start=1):
                    retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after")
                    try:
                        delay = min(max(float(retry_after), 1), 15) if retry_after else fallback_delay
                    except ValueError:
                        delay = fallback_delay
                    await asyncio.sleep(delay)
                    try:
                        return await client.responses.create(**request_body)
                    except RateLimitError as retry_exc:
                        exc = retry_exc
                raise AdapterError(
                    "FOUNDRY_RATE_LIMIT",
                    "Foundryのレート上限に達しました",
                    {"attempts": 4, "retryAfter": retry_after},
                ) from exc
        evidence_text = "\n\n".join(
            f'[{item["id"]}] {item.get("title", "取得不可")}\nURL: {item.get("url", "取得不可")}\n{item.get("text", "取得不可")}'
            for item in evidence
        )
        instructions = (
            "以下の検証済み根拠だけを使って日本語で回答してください。根拠外の知識や推測は禁止です。"
            "回答中で使った事実には必ず [evidence ID] を付け、URLを根拠IDからだけ参照してください。"
            "根拠が空なら「根拠なし」とだけ答えてください。\n\n" + evidence_text
        )
        return await client.responses.create(model=self.deployment, instructions=instructions, input=request.question)

    async def close(self) -> None:
        if self.client:
            await self.client.close()
        if self._credential:
            await self._credential.close()


class DemoModelClient:
    async def run(self, request: RunRequest, column: str, evidence: list[dict] | None = None, allowed_domains: list[str] | None = None) -> dict:
        await asyncio.sleep({"A": 0.35, "B": 0.5, "C": 0.4}.get(column, 0.3))
        if evidence is not None:
            refs = " ".join(f"[{item['id']}]" for item in evidence[:2])
            return {"output_text": f"デモ回答: 検証済み根拠の範囲で、質問「{request.question}」に関する公開情報を整理しました。{refs}", "usage": {"input_tokens": 420, "output_tokens": 135, "output_tokens_details": {"reasoning_tokens": 0}}}
        suffix = "全Web検索" if column == "A" else "許可ドメイン限定"
        return {
            "output_text": f"デモ回答 ({suffix}): 一次情報と公開された近況に基づき、要件・期限・対応優先順位を確認する必要があります。本回答は接続確認用の確定的な例です。",
            "usage": {"input_tokens": 310, "output_tokens": 115, "output_tokens_details": {"reasoning_tokens": 0}},
            "tool_usage": {"web_search": {"num_requests": 1}},
            "output": [{"type": "web_search_call", "action": {"sources": [{"title": "経済産業省 公開情報（デモ）", "url": "https://www.meti.go.jp/demo/report"}]}}],
        }

    async def close(self) -> None:
        return None


class ResponseAdapter:
    def __init__(self, model: SharedModelClient | DemoModelClient, pack: Pack, pricing: Any):
        self.model, self.pack, self.pricing = model, pack, pricing

    @property
    def labeler(self) -> Labeler:
        return lambda url: classify_url(url, [x.model_dump() for x in self.pack.classifications])

    async def search_column(self, request: RunRequest, column: str, emit: Callable) -> ColumnResult:
        started = time.perf_counter()
        await emit("progress", "検索を開始しています")
        domains = request.allowedDomains if column == "B" else []
        await emit("progress", f"{'許可ドメイン限定検索' if domains else 'Web検索'}を実行しています")
        response = await self.model.run(request, column, allowed_domains=domains)
        data = _as_dict(response)
        await emit("progress", "検索結果と回答を整理しています")
        answer = str(data.get("output_text") or getattr(response, "output_text", "") or "取得不可")
        citations, evidence = _parse_model_sources(data.get("output", []), self.labeler)
        if column == "B":
            rejected = [
                str(item.url) for item in evidence + citations
                if str(item.url) != "取得不可" and not host_allowed(str(item.url), domains)
            ]
            if rejected:
                raise AdapterError("ALLOWED_DOMAIN_REJECTED", "検索結果に許可外ドメインが含まれています")
        usage = data.get("usage") or {}
        details = usage.get("output_tokens_details") or {}
        tool = (data.get("tool_usage") or {}).get("web_search") or {}
        estimated_cost = _estimate_cost(
            self.pricing, usage.get("input_tokens"), usage.get("output_tokens"),
            tool.get("num_requests"), "ab",
        )
        unavailable = [name for name, value in {
            "inputTokens": usage.get("input_tokens"), "outputTokens": usage.get("output_tokens"),
            "reasoningTokens": details.get("reasoning_tokens"), "searchRequests": tool.get("num_requests"),
            "estimatedCost": estimated_cost,
        }.items() if value is None]
        return ColumnResult(
            columnId=column, label="検索制限なし" if column == "A" else "許可ドメイン限定",
            answer=answer, citations=citations, evidence=evidence,
            metrics=Metrics(elapsedMs=int((time.perf_counter()-started)*1000),
                inputTokens=usage.get("input_tokens"), outputTokens=usage.get("output_tokens"),
                reasoningTokens=details.get("reasoning_tokens"), searchRequests=tool.get("num_requests"),
                searchRequestUnit="Bing web_search リクエスト", estimatedCost=estimated_cost,
                costCurrency=self.pricing.currency if estimated_cost is not None else None,
                unavailableFields=unavailable),
            settings={"allowedDomains": domains, "search": "web_search"},
        )


class WebIQAdapter:
    ENDPOINT = "https://api.microsoft.ai/v3/auto"
    SCOPE = "https://api.microsoft.ai/.default"

    def __init__(self, model: SharedModelClient | DemoModelClient, pack: Pack, pricing: Any):
        self.model, self.pack, self.pricing = model, pack, pricing
        self.api_key = os.getenv("WEB_IQ_API_KEY") or os.getenv("WEBIQ_API_KEY")
        self.app_id = os.getenv("WEB_IQ_APP_ID") or os.getenv("WEBIQ_APP_ID")

    async def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Content-Type": "application/json", "x-apikey": self.api_key}
        credential = DefaultAzureCredential()
        try:
            token = await credential.get_token(self.SCOPE)
            return {"Content-Type": "application/json", "Authorization": f"Bearer {token.token}"}
        finally:
            await credential.close()

    async def run(self, request: RunRequest, emit: Callable) -> ColumnResult:
        started = time.perf_counter()
        await emit("progress", "Web IQの根拠を取得しています")
        if isinstance(self.model, DemoModelClient):
            data = _demo_webiq(request)
        else:
            payload: dict[str, Any] = {
                "query": request.question, "mode": request.mode,
                "language": "ja", "region": "JP",
                "responseFilter": request.responseFilter,
            }
            if request.scopeName:
                payload.update(scopeName=request.scopeName, failOnMissingScope=True)
                payload["responseFilter"] = list(dict.fromkeys(request.responseFilter + ["web", "news"]))
            timeout = httpx.Timeout(float(os.getenv("WEBIQ_TIMEOUT_SECONDS", "90")))
            async with httpx.AsyncClient(timeout=timeout) as client:
                endpoint = os.getenv("WEBIQ_ENDPOINT", self.ENDPOINT)
                if self.app_id and not self.api_key:
                    separator = "&" if "?" in endpoint else "?"
                    endpoint = f"{endpoint}{separator}APPID={self.app_id}"
                response = await client.post(endpoint, json=payload, headers=await self._headers())
            if response.is_error:
                error_code = None
                try:
                    body = response.json()
                    error = body.get("error")
                    if not isinstance(error, dict):
                        error = {}
                    details = error.get("details") or body.get("details") or []
                    detail_code = next(
                        (
                            detail.get("code")
                            for detail in details
                            if isinstance(detail, dict) and detail.get("code")
                        ),
                        None,
                    )
                    error_code = body.get("code") or error.get("code") or detail_code or error.get("type")
                except (ValueError, AttributeError):
                    pass
                if not error_code:
                    known_error = re.search(
                        r"(Auth(?:NoToken|TokenParse|InvalidApiKey|enticationFailed|ExpiredTrial|MissingEntryId|"
                        r"AppIdSelectionRequired|UnauthorizedEntryId|UnauthorizedAppId|UnauthorizedService|"
                        r"BatchEndpointRequired|McpWebForbidden|ContentFormatForbidden))",
                        response.text,
                    )
                    error_code = known_error.group(1) if known_error else None
                safe_code = str(error_code or "UNKNOWN").replace("-", "_").upper()
                if not safe_code.replace("_", "").isalnum():
                    safe_code = "UNKNOWN"
                raise AdapterError(
                    f"WEBIQ_HTTP_{response.status_code}_{safe_code}",
                    "Web IQのリクエストに失敗しました",
                )
            data = response.json()

        if request.scopeName and data.get("scopeApplied") is not True:
            raise AdapterError("SCOPE_NOT_APPLIED", "指定したWeb IQスコープを適用できませんでした")
        evidence, citations = _parse_webiq_results(data, lambda url: classify_url(url, [x.model_dump() for x in self.pack.classifications]))
        cited_evidence_ids = {evidence_id for citation in citations for evidence_id in citation.evidenceIds}
        for index, item in enumerate(evidence):
            if item.id in cited_evidence_ids or str(item.url) == "取得不可":
                continue
            citation_id = f"evidence-citation-{index + 1}"
            item.citationIds.append(citation_id)
            citations.append(Citation(
                id=citation_id,
                title=item.title,
                url=item.url,
                source=item.source,
                excerpt=item.text,
                evidenceIds=[item.id],
                classification=classify_url(str(item.url), [x.model_dump() for x in self.pack.classifications]),
            ))
        scoped_sources = [
            str(item.url) for item in evidence
            if str(item.url) != "取得不可"
        ] + [str(item.url) for item in citations]
        if request.scopeName and (not scoped_sources or any(
            not host_allowed(url, request.allowedDomains) for url in scoped_sources
        )):
            raise AdapterError("SCOPE_URL_REJECTED", "スコープ外のURLがWeb IQ結果に含まれています")
        valid_evidence = [item.model_dump(mode="json") for item in evidence]
        await emit("progress", "検証済み根拠から回答を生成しています")
        generated = await self.model.run(request, "C", evidence=valid_evidence)
        generated_data = _as_dict(generated)
        answer = str(generated_data.get("output_text") or getattr(generated, "output_text", "") or "根拠なし")
        usages = [generated_data.get("usage") or {}]
        cited_ids = set(re.findall(r"\[([^\]]+)\]", answer))
        if evidence and not cited_ids:
            generated = await self.model.run(request, "C", evidence=valid_evidence)
            generated_data = _as_dict(generated)
            answer = str(generated_data.get("output_text") or getattr(generated, "output_text", "") or "根拠なし")
            usages.append(generated_data.get("usage") or {})
            cited_ids = set(re.findall(r"\[([^\]]+)\]", answer))
            if evidence and not cited_ids:
                references = " ".join(f"[{item.id}]" for item in evidence)
                answer = f"{answer}\n\n参照根拠: {references}"
                cited_ids = {item.id for item in evidence}
        unresolved = cited_ids - {item.id for item in evidence}
        if unresolved:
            raise AdapterError("UNKNOWN_CITATION", "回答に未検証の根拠IDが含まれています")
        input_tokens = _sum_usage(usages, "input_tokens")
        output_tokens = _sum_usage(usages, "output_tokens")
        reasoning_tokens = _sum_usage([usage.get("output_tokens_details") or {} for usage in usages], "reasoning_tokens")
        estimated_cost = _estimate_cost(self.pricing, input_tokens, output_tokens, 1, request.mode)
        absent = [name for name, value in {
            "inputTokens": input_tokens, "outputTokens": output_tokens,
            "reasoningTokens": reasoning_tokens, "estimatedCost": estimated_cost,
        }.items() if value is None]
        return ColumnResult(
            columnId="C", label="Web IQ Auto", answer=answer, citations=citations, evidence=evidence,
            scopeApplied=data.get("scopeApplied") if request.scopeName or "scopeApplied" in data else None,
            metrics=Metrics(elapsedMs=int((time.perf_counter()-started)*1000),
                inputTokens=input_tokens, outputTokens=output_tokens,
                reasoningTokens=reasoning_tokens, searchRequests=1,
                searchRequestUnit="Web IQ Auto APIリクエスト（内部検索数ではありません）",
                estimatedCost=estimated_cost,
                costCurrency=self.pricing.currency if estimated_cost is not None else None,
                unavailableFields=absent),
            settings={"mode": request.mode, "scopeName": request.scopeName, "responseFilter": request.responseFilter,
                      "failOnMissingScope": bool(request.scopeName), "language": "ja", "region": "JP"},
        )


def _as_dict(value: Any) -> dict:
    value = _values(value)
    return value if isinstance(value, dict) else {}


def _text_or(value: Any, fallback: str = "取得不可") -> str:
    return str(value) if value not in (None, "") else fallback


def _parse_model_sources(output: list, label: Labeler) -> tuple[list[Citation], list[Evidence]]:
    citations, evidence = [], []
    for item_index, raw in enumerate(output or []):
        item = _as_dict(raw)
        if item.get("type") == "web_search_call":
            action = _as_dict(item.get("action"))
            # Newer Responses payloads expose terminal results separately from source selection.
            candidates = list(action.get("sources") or []) + list(item.get("results") or [])
            for result_index, raw_source in enumerate(candidates):
                source = _as_dict(raw_source)
                url = safe_http_url(source.get("url"))
                if url == "取得不可":
                    continue
                source_id = str(source.get("id") or f"ab-{item_index+1}-{result_index+1}")
                citations.append(Citation(id=f"cite-{source_id}", title=_text_or(source.get("title")),
                    url=url, source=_text_or(source.get("source") or url), excerpt=_text_or(source.get("excerpt") or source.get("snippet")),
                    evidenceIds=[source_id], classification=label(url)))
                evidence.append(Evidence(id=source_id, title=_text_or(source.get("title")), url=url,
                    source=_text_or(source.get("source")), text=_text_or(source.get("excerpt") or source.get("snippet")),
                    citationIds=[f"cite-{source_id}"], structured={k: v for k, v in source.items() if k not in {"title", "url", "excerpt", "snippet", "id"}}))
        for message_index, raw_content in enumerate(item.get("content") or []):
            content = _as_dict(raw_content)
            if content.get("type") != "output_text":
                continue
            for annotation_index, raw_annotation in enumerate(content.get("annotations") or []):
                annotation = _as_dict(raw_annotation)
                if annotation.get("type") != "url_citation":
                    continue
                url = safe_http_url(annotation.get("url"))
                if url == "取得不可":
                    continue
                source_id = f"ab-{item_index + 1}-message-{message_index + 1}-{annotation_index + 1}"
                citation_id = f"cite-{source_id}"
                citations.append(Citation(
                    id=citation_id,
                    title=_text_or(annotation.get("title")),
                    url=url,
                    source=_text_or(urlsplit(url).hostname),
                    excerpt="取得不可",
                    evidenceIds=[source_id],
                    classification=label(url),
                ))
                evidence.append(Evidence(
                    id=source_id,
                    title=_text_or(annotation.get("title")),
                    url=url,
                    source=_text_or(urlsplit(url).hostname),
                    text="取得不可",
                    citationIds=[citation_id],
                ))
    return _dedupe(citations, "id"), _dedupe(evidence, "id")


def _parse_webiq_results(data: dict, label: Labeler) -> tuple[list[Evidence], list[Citation]]:
    evidence, citations = [], []
    results = data.get("results") or data.get("answer", {}).get("results") or []
    if not results and (data.get("evidence") or data.get("citations")):
        results = [data]
    for result_index, raw_result in enumerate(results):
        result = _as_dict(raw_result)
        raw_evidence = result.get("evidence")
        evidence_items = raw_evidence if isinstance(raw_evidence, list) else ([raw_evidence] if raw_evidence else [result])
        raw_citations = result.get("citations") or result.get("references") or data.get("citations") or []
        for index, raw_item in enumerate(evidence_items):
            item = _as_dict(raw_item)
            evidence_id = str(item.get("id") or f"c-{result_index+1}-{index+1}")
            first_citation = _as_dict(raw_citations[0]) if raw_citations else {}
            raw_url = item.get("url") or item.get("link") or result.get("url") or first_citation.get("url") or first_citation.get("hostPageUrl")
            url = safe_http_url(raw_url)
            citation_ids = [str(c.get("id") or f"citation-{result_index+1}-{i+1}")
                            for i, c in enumerate(raw_citations) if isinstance(c, dict)]
            content = item.get("content")
            structured = content if isinstance(content, dict) else {}
            text = content if isinstance(content, str) else _text_or(item.get("text") or item.get("excerpt"), "")
            evidence.append(Evidence(id=evidence_id, title=_text_or(item.get("title") or result.get("title")),
                url=url, source=_text_or(item.get("source") or item.get("publisher") or first_citation.get("source") or result.get("source")),
                text=text, citationIds=citation_ids, kind=str(item.get("type") or result.get("type") or "evidence"),
                structured=structured))
    for result_index, result in enumerate(results):
        for citation_index, raw_citation in enumerate(result.get("citations") or []):
            i = result_index * 100 + citation_index
            citation = _as_dict(raw_citation)
            evidence_owner = [e for e in evidence if str(e.id).startswith(f"c-{result_index+1}-")]
            citation.setdefault("id", f"citation-{result_index+1}-{citation_index+1}")
            citation.setdefault("evidenceIds", [e.id for e in evidence_owner])
            url = safe_http_url(citation.get("url") or citation.get("link") or citation.get("hostPageUrl"))
            if url == "取得不可":
                continue
            citations.append(Citation(id=str(citation.get("id")),
                title=_text_or(citation.get("title")), url=url,
                source=_text_or(citation.get("source") or citation.get("publishedBy") or citation.get("contentSource")),
                excerpt=_text_or(evidence_owner[0].text if evidence_owner else citation.get("excerpt") or citation.get("text")),
                publishedAt=_text_or(citation.get("lastUpdatedAt") or citation.get("publishedAt") or citation.get("observedAt")
                                     or citation.get("crawledAt") or citation.get("date") or citation.get("updatedAt")),
                dateKind="観測日" if citation.get("observedAt") else "更新日" if citation.get("lastUpdatedAt") else _text_or(citation.get("dateKind")),
                evidenceIds=[str(x) for x in citation.get("evidenceIds", [])],
                classification=label(url)))
    for i, raw_citation in enumerate(data.get("citations") or []):
        citation = _as_dict(raw_citation)
        url = safe_http_url(citation.get("url") or citation.get("link") or citation.get("hostPageUrl"))
        if url == "取得不可":
            continue
        evidence_ids = citation.get("evidenceIds") or citation.get("evidenceId") or []
        evidence_ids = [str(evidence_ids)] if not isinstance(evidence_ids, list) else [str(x) for x in evidence_ids]
        citations.append(Citation(id=str(citation.get("id") or f"citation-{i+1}"),
            title=_text_or(citation.get("title")), url=url, source=_text_or(citation.get("source") or citation.get("publisher")),
            excerpt=_text_or(citation.get("excerpt") or citation.get("text")),
            publishedAt=_text_or(citation.get("lastUpdatedAt") or citation.get("publishedAt") or citation.get("observedAt")
                                 or citation.get("crawledAt") or citation.get("date") or citation.get("updatedAt")),
            dateKind=_text_or(citation.get("dateKind")), evidenceIds=evidence_ids, classification=label(url)))
    return _dedupe(evidence, "id"), _dedupe(citations, "id")


def _resolve_citations(cited_ids: set[str], evidence: list[Evidence], citations: list[Citation]) -> list[Citation]:
    used_citation_ids = {c for item in evidence if item.id in cited_ids for c in item.citationIds}
    used_evidence = {item.id for item in evidence if item.id in cited_ids}
    selected = [c for c in citations if c.id in used_citation_ids or set(c.evidenceIds) & used_evidence]
    return selected


def _dedupe(items: list[Any], attribute: str) -> list[Any]:
    result, seen = [], set()
    for item in items:
        key = getattr(item, attribute)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _demo_webiq(request: RunRequest) -> dict:
    evidence = {
        "id": "c-demo-1", "title": "Web IQ 検証済み公開根拠（デモ）",
        "url": "https://www.meti.go.jp/demo/webiq", "source": "経済産業省",
        "text": "公開資料に基づき、対象事項の要件、期限、最新の変更点を確認する必要があります。",
        "citationIds": ["c-cite-1"],
    }
    return {
        "scopeApplied": True if request.scopeName else None,
        "results": [{
            "type": "web", "evidence": evidence,
            "citations": [{"id": "c-cite-1", "title": evidence["title"], "url": evidence["url"],
                           "source": evidence["source"], "evidenceIds": [evidence["id"]],
                           "publishedAt": "2026-11-18", "dateKind": "公開日"}],
        }],
    }


def _sum_usage(usages: list[dict], field: str) -> int | None:
    values = [usage.get(field) for usage in usages]
    return None if any(value is None for value in values) else sum(values)


def _estimate_cost(pricing: Any, input_tokens: int | None, output_tokens: int | None,
                   search_requests: int | None, search_kind: str) -> float | None:
    values = [
        pricing.model.get("inputPerMillionTokens"), pricing.model.get("outputPerMillionTokens"),
        input_tokens, output_tokens, search_requests,
    ]
    if any(value is None for value in values):
        return None
    if search_kind == "ab":
        search_rate = pricing.search.get("abPerRequest")
    elif search_kind == "advanced":
        search_rate = pricing.search.get("webIqAdvancedPerRequest")
    else:
        search_rate = pricing.search.get("webIqLitePerRequest")
    if search_rate is None:
        return None
    return round(
        (input_tokens / 1_000_000) * pricing.model["inputPerMillionTokens"]
        + (output_tokens / 1_000_000) * pricing.model["outputPerMillionTokens"]
        + search_requests * search_rate,
        8,
    )
