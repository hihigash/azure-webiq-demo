from fastapi.testclient import TestClient

from backend.app import create_app


def snapshot():
    return {
        "runId": "run-1",
        "question": "question",
        "columns": [{
            "columnId": "A", "label": "A", "answer": "=HYPERLINK(\"https://evil.example\")",
            "citations": [{"id": "c", "title": "title", "url": "https://example.com"}],
            "evidence": [{"id": "e", "title": "e", "url": "https://example.com", "text": "+formula"}],
            "metrics": {},
        }],
    }


def test_export_json_and_csv_are_downloads(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    with TestClient(create_app()) as client:
        json_response = client.post("/api/export?format=json", json=snapshot())
        csv_response = client.post("/api/export?format=csv", json=snapshot())
    assert json_response.headers["content-disposition"].endswith('webiq-run-1.json"')
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    assert b"'=HYPERLINK" in csv_response.content
    assert b"'+formula" in csv_response.content
