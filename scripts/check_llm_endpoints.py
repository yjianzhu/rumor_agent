"""Probe LLM/Embedding endpoints via curl_cffi (read-only).

Never writes or rewrites config.toml; edit endpoints manually after reviewing results.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tomllib
from typing import Any

from curl_cffi import requests as curl_requests

_IMPERSONATE = "chrome136"
_TIMEOUT = 15


# ── Probing ──────────────────────────────────────────────────────────────────

def _build_headers(ep: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if ep.get("api_key"):
        headers["Authorization"] = f"Bearer {ep['api_key']}"
    return headers


def _probe_chat(ep: dict[str, Any], model: str, timeout: float) -> tuple[bool, str]:
    url = f"{ep['api_base'].rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    resp = curl_requests.post(
        url, json=payload, headers=_build_headers(ep),
        impersonate=_IMPERSONATE, timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"] or ""
    return True, f"ok, reply={text!r}"


def _probe_embedding(ep: dict[str, Any], model: str, timeout: float) -> tuple[bool, str]:
    url = f"{ep['api_base'].rstrip('/')}/embeddings"
    payload = {"model": model, "input": ["hello"]}
    resp = curl_requests.post(
        url, json=payload, headers=_build_headers(ep),
        impersonate=_IMPERSONATE, timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    dim = len(data["data"][0]["embedding"])
    return True, f"ok, dim={dim}"


def _probe_endpoint(
    ep: dict[str, Any],
    default_model: str,
    timeout: float,
    *,
    kind: str,
) -> tuple[bool, str]:
    model = (ep.get("model") or default_model).strip()
    if not model:
        return False, "missing model"
    if not ep.get("api_base"):
        return False, "missing api_base"

    probe = _probe_embedding if kind == "embedding" else _probe_chat
    try:
        return probe(ep, model, timeout)
    except Exception as exc:
        return False, _fmt_error(exc)


def _fmt_error(exc: Exception) -> str:
    msg = str(exc).replace("\n", " ")
    if "<html" in msg.lower() or "<head" in msg.lower():
        import re
        title = re.search(r"<title>(.*?)</title>", msg, re.IGNORECASE | re.DOTALL)
        hint = title.group(1).strip() if title else "HTML error page"
        return f"{type(exc).__name__}: WAF/HTML ({hint})"
    if len(msg) > 200:
        msg = msg[:197] + "..."
    return msg


# ── TOML (read-only) ─────────────────────────────────────────────────────────

def _read_toml(path: str) -> dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


# ── CLI ───────────────────────────────────────────────────────────────────────

_STYLE_LABELS = {
    "chat": "/chat/completions",
    "embedding": "/embeddings",
}


def _check_section(
    endpoints: list[dict],
    default_model: str,
    timeout: float,
    *,
    kind: str,
) -> tuple[list[dict], list[dict]]:
    available: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    api_label = _STYLE_LABELS.get(kind, "")

    for i, ep in enumerate(endpoints, start=1):
        if not isinstance(ep, dict):
            unavailable.append({"raw": ep, "_error": "not a dict"})
            print(f"  [{i}/{len(endpoints)}] FAIL (not a valid endpoint object)")
            continue

        ok, reason = _probe_endpoint(ep, default_model, timeout, kind=kind)
        safe_base = ep.get("api_base", "?")
        safe_model = ep.get("model") or default_model

        if ok:
            available.append(dict(ep))
            print(f"  [{i}/{len(endpoints)}] OK   {safe_base} | model={safe_model} | api={api_label}")
            print(f"         {reason}")
        else:
            broken = dict(ep)
            broken["_error"] = reason
            unavailable.append(broken)
            print(f"  [{i}/{len(endpoints)}] FAIL {safe_base} | model={safe_model}")
            print(f"         {reason}")

    return available, unavailable


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe LLM/Embedding endpoints via curl_cffi (browser TLS fingerprint). "
            "Only reads config.toml; does not modify it. Exit 1 if any probe fails."
        ),
    )
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument("--timeout", type=float, default=15.0, help="Request timeout (seconds)")
    parser.add_argument("--skip-embedding", action="store_true", help="Skip embedding endpoint checks")
    args = parser.parse_args()

    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        data = _read_toml(args.config)
    except FileNotFoundError:
        print(f"config not found: {args.config}")
        return 1

    llm = data.get("llm", {})
    emb = data.get("embedding", {})

    # ── LLM endpoints ────────────────────────────────────────────────────
    llm_endpoints = llm.get("endpoints", [])
    llm_available: list[dict] = []
    llm_unavail: list[dict] = []
    if llm_endpoints:
        default_model = llm.get("model", "")
        print(f"[LLM] {len(llm_endpoints)} endpoint(s)")
        llm_available, llm_unavail = _check_section(
            llm_endpoints, default_model, args.timeout, kind="chat",
        )
        print(f"[LLM] available {len(llm_available)}, failed {len(llm_unavail)}")
    else:
        print("[LLM] no [[llm.endpoints]] found, skipping")

    # ── Embedding endpoints ──────────────────────────────────────────────
    emb_endpoints = emb.get("endpoints", [])
    emb_available: list[dict] = []
    emb_unavail: list[dict] = []
    if emb_endpoints and not args.skip_embedding:
        default_emb_model = emb.get("model", "")
        print(f"\n[Embedding] {len(emb_endpoints)} endpoint(s)")
        emb_available, emb_unavail = _check_section(
            emb_endpoints, default_emb_model, args.timeout, kind="embedding",
        )
        print(f"[Embedding] available {len(emb_available)}, failed {len(emb_unavail)}")
    elif not args.skip_embedding:
        print("\n[Embedding] no [[embedding.endpoints]] found, skipping")

    llm_failed = len(llm_unavail) if llm_endpoints else 0
    emb_failed = len(emb_unavail) if (emb_endpoints and not args.skip_embedding) else 0
    return 1 if llm_failed or emb_failed else 0


if __name__ == "__main__":
    sys.exit(main())
