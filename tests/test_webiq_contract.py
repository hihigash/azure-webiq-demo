from backend.clients import _parse_webiq_results
from backend.security import host_allowed


def test_parses_documented_web_iq_evidence_and_citations():
    data = {
        "results": [{
            "evidence": {
                "type": "text/news",
                "content": "公開資料の本文抜粋",
            },
            "citations": [{
                "contentSource": "news",
                "source": "経済産業省",
                "title": "規制ニュース",
                "url": "https://www.meti.go.jp/news/1",
                "lastUpdatedAt": "2026-11-18T00:00:00Z",
            }],
        }],
        "scopeApplied": True,
        "traceId": "trace-id",
    }

    evidence, citations = _parse_webiq_results(data, lambda url: "公的機関")

    assert evidence[0].kind == "text/news"
    assert evidence[0].text == "公開資料の本文抜粋"
    assert evidence[0].url.startswith("https://www.meti.go.jp/")
    assert citations[0].url.startswith("https://www.meti.go.jp/")
    assert citations[0].publishedAt == "2026-11-18T00:00:00Z"
    assert citations[0].evidenceIds == [evidence[0].id]
    assert citations[0].id in evidence[0].citationIds


def test_path_prefixes_do_not_match_similarly_named_paths_or_hosts():
    assert host_allowed("https://www.nipponsteel.com/ir/report", ["nipponsteel.com/ir"])
    assert not host_allowed("https://www.nipponsteel.com/irregular", ["nipponsteel.com/ir"])
    assert not host_allowed("https://nipponsteel.com.evil.test/ir", ["nipponsteel.com/ir"])
