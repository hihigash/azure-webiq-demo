from __future__ import annotations

from urllib.parse import urlsplit


def safe_http_url(value: object) -> str:
    text = str(value or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return "取得不可"
    parsed = urlsplit(text)
    return text if parsed.netloc and parsed.scheme in ("http", "https") and not parsed.username else "取得不可"


def host_allowed(url: str, allowed_domains: list[str]) -> bool:
    if safe_http_url(url) == "取得不可":
        return False
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.rstrip("/") or "/"
    for rule in allowed_domains:
        rule_host, separator, rule_path = rule.lower().lstrip(".").partition("/")
        if host != rule_host and not host.endswith("." + rule_host):
            continue
        if not separator:
            return True
        prefix = "/" + rule_path.strip("/")
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def classify_url(url: str, classifications: list[dict]) -> str:
    host = (urlsplit(safe_http_url(url)).hostname or "").lower() if safe_http_url(url) != "取得不可" else ""
    for item in classifications:
        if any(host == d or host.endswith("." + d) for d in item.get("domains", [])):
            return item["name"]
    return "その他"


def spreadsheet_safe(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

