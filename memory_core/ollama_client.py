"""Pinned local-only Ollama client. Never downloads or calls cloud models."""
import json
import time
import urllib.request
from urllib.parse import urlparse

BASE = "http://127.0.0.1:11434"
MODEL = "mimo-9b:latest"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Local model redirects are disabled")


def request(path, body=None, timeout=90):
    if path not in ("/api/tags", "/api/ps", "/api/show", "/api/chat"):
        raise ValueError("Unsupported local endpoint")
    url = BASE + path
    assert urlparse(url).hostname == "127.0.0.1"
    if body is not None and body.get("model", MODEL) != MODEL:
        raise ValueError("Only the installed mimo-9b:latest is allowed")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def inspect():
    tags = request("/api/tags")
    tag = next((row for row in tags.get("models", []) if row.get("name") == MODEL), None)
    if tag is None:
        raise RuntimeError("Installed MiMo model not found; no download attempted")
    info = request("/api/show", {"model": MODEL})
    if info.get("remote_model") or info.get("remote_host") or info.get("details", {}).get("format") != "gguf":
        raise RuntimeError("A local GGUF is required; cloud inference is disabled")
    return {"endpoint": BASE, "model": MODEL, "digest": tag.get("digest"), "size_bytes": tag.get("size"), "details": info.get("details"), "capabilities": info.get("capabilities"), "general_name": info.get("model_info", {}).get("general.name")}


def chat(system, payload, schema, *, max_tokens=384):
    started = time.perf_counter()
    out = request("/api/chat", {"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "format": schema, "stream": False, "think": False, "keep_alive": "5m", "options": {"temperature": 0, "num_ctx": 4096, "num_predict": max_tokens}}, timeout=120)
    content = out.get("message", {}).get("content", "")
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        value = None
    return {"value": value, "raw": content, "wall_ms": (time.perf_counter() - started) * 1000, "model": out.get("model"), "done_reason": out.get("done_reason"), **{key: out.get(key) for key in ("total_duration", "load_duration", "prompt_eval_count", "eval_count", "prompt_eval_duration", "eval_duration")}}
