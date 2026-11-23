"""Normalize common OpenAI-compatible base URLs before storing or calling them."""

import re
from urllib.parse import urlsplit, urlunsplit


def chat_completion_endpoint(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        raise ValueError("模型接口地址格式无效") from None
    if parts.scheme not in {"https", "http"} or not parts.netloc or not hostname:
        raise ValueError("模型接口地址必须为完整的 HTTP(S) 地址")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("模型接口地址不能包含凭证、查询参数或片段")
    if parts.scheme == "http" and hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("远程模型接口必须使用 HTTPS")
    path = parts.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        if path and not (re.search(r"/v\d+$", path) or path.endswith("/beta")):
            raise ValueError("请填写模型 Base URL 或完整的 /chat/completions 地址")
        path += "/chat/completions"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
