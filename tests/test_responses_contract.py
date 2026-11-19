from backend.clients import _parse_model_sources


def test_parses_message_url_citations_when_action_results_are_missing():
    response_output = [{
        "type": "message",
        "content": [{
            "type": "output_text",
            "text": "根拠付き回答 [1]",
            "annotations": [{
                "type": "url_citation",
                "url": "https://www.meti.go.jp/example",
                "title": "経済産業省",
            }],
        }],
    }]

    citations, evidence = _parse_model_sources(response_output, lambda url: "公的機関")

    assert citations[0].title == "経済産業省"
    assert citations[0].classification == "公的機関"
    assert citations[0].url.endswith("/example")
    assert evidence[0].text == "取得不可"
