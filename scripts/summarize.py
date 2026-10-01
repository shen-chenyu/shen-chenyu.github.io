from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.common import (
    coerce_int,
    compute_new_items,
    filter_items_by_lookback,
    first_sentence,
    load_config,
    load_state,
    read_json,
    resolve_paths,
    stable_sort_items,
    today_jst_iso,
    write_json_if_changed,
)


def _pick_llm_provider(config: dict[str, Any]) -> tuple[str, str] | None:
    keys = {
        "openai": os.getenv("OPENAI_API_KEY"),
        "deepseek": os.getenv("DEEPSEEK_API_KEY"),
    }
    for provider in config.get("llm", {}).get("provider_preference", ["deepseek", "openai"]):
        key = keys.get(provider)
        if key:
            return provider, key
    return None


def _default_base_url(provider: str) -> str:
    if provider == "deepseek":
        return "https://api.deepseek.com/v1"
    return "https://api.openai.com/v1"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def summarize_one(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    item: dict[str, Any],
) -> dict[str, Any]:
    prompt = (
        "Return ONLY a JSON object with this schema:\n"
        '{ "one_liner": string, "whats_new": string[] }\n'
        "Constraints:\n"
        "- one_liner: <= 200 chars, plain text.\n"
        "- whats_new: 2-5 bullet-like strings, each <= 120 chars, plain text.\n"
        "- No markdown, no extra keys.\n\n"
        f"Title: {item.get('title','')}\n"
        f"Authors: {', '.join(item.get('authors') or [])}\n"
        f"Abstract: {item.get('abstract','')}\n"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You summarize arXiv papers concisely and precisely."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }

    url = base_url.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    data = _extract_json_object(content)
    if not data:
        raise ValueError("LLM returned non-JSON content")

    one_liner = str(data.get("one_liner", "")).strip()
    whats_new = data.get("whats_new") or []
    if not isinstance(whats_new, list):
        whats_new = []
    whats_new = [str(x).strip() for x in whats_new if str(x).strip()]

    if not one_liner:
        one_liner = first_sentence(item.get("abstract", ""))

    return {"one_liner": one_liner, "whats_new": whats_new, "provider": provider, "model": model}


def summarize_trend(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    def clip(text: str, max_chars: int) -> str:
        text = " ".join((text or "").strip().split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    parts: list[str] = []
    for idx, item in enumerate(items, start=1):
        parts.append(f"{idx}) {clip(item.get('title',''), 180)}")
        parts.append(f"   Abstract: {clip(item.get('abstract',''), 700)}")

    prompt = (
        "Return ONLY a JSON object with this schema:\n"
        '{ "trend_summary": string, "themes": string[], "keywords": string[] }\n'
        "Constraints:\n"
        "- trend_summary: 2-4 sentences, plain text. If the set spans multiple research areas, mention that explicitly.\n"
        "- themes: 3-6 short phrases. Prefer prefixing each theme with a short tag like 'Materials:' or 'AI:' when helpful.\n"
        "- keywords: 6-12 keywords/phrases.\n"
        "- No markdown, no extra keys.\n\n"
        "Guidance:\n"
        "- The paper set may mix domains (e.g., materials/physics simulation and AI/LLM work). Reflect that without forcing a fixed balance.\n"
        "- Base tags on the paper titles/abstracts (and any category hints visible).\n\n"
        "Papers:\n"
        + "\n".join(parts)
        + "\n"
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You infer daily research trends from paper titles and abstracts.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }

    url = base_url.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    data = _extract_json_object(content)
    if not data:
        raise ValueError("LLM returned non-JSON content")

    trend_summary = str(data.get("trend_summary", "")).strip()
    themes = data.get("themes") or []
    keywords = data.get("keywords") or []
    if not isinstance(themes, list):
        themes = []
    if not isinstance(keywords, list):
        keywords = []
    themes = [str(x).strip() for x in themes if str(x).strip()]
    keywords = [str(x).strip() for x in keywords if str(x).strip()]

    return {
        "trend_summary": trend_summary,
        "themes": themes,
        "keywords": keywords,
        "provider": provider,
        "model": model,
    }


def summarize_digest(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    items: list[dict[str, Any]],
    featured_count: int,
) -> dict[str, Any]:
    def clip(text: str, max_chars: int) -> str:
        text = " ".join((text or "").strip().split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    featured_count = max(1, int(featured_count))

    parts: list[str] = []
    for idx, item in enumerate(items, start=1):
        raw = item.get("raw") or {}
        primary = raw.get("primary_category") if isinstance(raw, dict) else None
        queries = raw.get("queries") if isinstance(raw, dict) else None
        if not isinstance(queries, list):
            queries = []
        queries = [str(q).strip() for q in queries if str(q).strip()]

        parts.append(f"{idx}) ID: {item.get('id','')}")
        parts.append(f"   Title: {clip(item.get('title',''), 200)}")
        if primary:
            parts.append(f"   Category: {primary}")
        if queries:
            parts.append(f"   Query: {', '.join(queries[:3])}")
        parts.append(f"   Abstract: {clip(item.get('abstract',''), 800)}")

    prompt = (
        "You are writing a concise daily research newspaper for a technical reader.\n"
        "The paper set may mix domains (e.g., materials/physics simulation and AI/LLM work).\n"
        "Use the provided Query and Category hints when helpful, but do not assume any fixed set of queries.\n"
        "Return ONLY a JSON object with this schema:\n"
        "{\n"
        '  \"headline\": string,\n'
        '  \"lede\": string,\n'
        '  \"highlights\": string[],\n'
        '  \"themes\": string[],\n'
        '  \"keywords\": string[],\n'
        '  \"featured_ids\": string[]\n'
        "}\n"
        "Constraints:\n"
        "- headline: <= 90 chars, plain text.\n"
        "- lede: 2-4 sentences, plain text.\n"
        "- highlights: 4-7 short bullet-like strings.\n"
        "- themes: 3-6 short phrases. Prefer prefixing each theme with a short tag like 'Materials:' or 'AI:' when helpful.\n"
        "- keywords: 6-12 keywords/phrases.\n"
        f"- featured_ids: pick up to {featured_count} IDs from the list (use IDs exactly; no invented IDs).\n"
        "- No markdown, no extra keys.\n\n"
        "Selection guidance:\n"
        "- If multiple domains or queries are present, try to make featured_ids diverse across them when possible (no strict quota).\n"
        "Papers:\n"
        + "\n".join(parts)
        + "\n"
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You produce structured daily research digests from paper titles and abstracts.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }

    url = base_url.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    data = _extract_json_object(content)
    if not data:
        raise ValueError("LLM returned non-JSON content")

    headline = str(data.get("headline", "")).strip()
    lede = str(data.get("lede", "")).strip()
    highlights = data.get("highlights") or []
    themes = data.get("themes") or []
    keywords = data.get("keywords") or []
    featured_ids = data.get("featured_ids") or []

    def norm_list(value: Any, *, max_len: int) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for x in value:
            s = str(x).strip()
            if s:
                out.append(s)
            if len(out) >= max_len:
                break
        return out

    highlights = norm_list(highlights, max_len=7)
    themes = norm_list(themes, max_len=6)
    keywords = norm_list(keywords, max_len=12)
    featured_ids = norm_list(featured_ids, max_len=featured_count)

    # Keep only IDs that actually exist in the provided list.
    valid_ids = {str(i.get("id")) for i in items if i.get("id")}
    seen: set[str] = set()
    kept: list[str] = []
    for fid in featured_ids:
        if fid in valid_ids and fid not in seen:
            kept.append(fid)
            seen.add(fid)
    featured_ids = kept

    return {
        "headline": headline,
        "lede": lede,
        "highlights": highlights,
        "themes": themes,
        "keywords": keywords,
        "featured_ids": featured_ids,
        "provider": provider,
        "model": model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Optionally summarize new items with an LLM.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    paths = resolve_paths(config, config_path)

    if not config.get("llm", {}).get("enabled", True):
        print("LLM summarization disabled in config (llm.enabled=false).")
        return 0

    picked = _pick_llm_provider(config)
    if not picked:
        print("No LLM API key found (set OPENAI_API_KEY or DEEPSEEK_API_KEY). Skipping summaries.")
        return 0
    provider, api_key = picked

    collected = read_json(paths.collected, default=None)
    if not collected:
        raise SystemExit(f"Missing collected items at {paths.collected}. Run scripts/collect.py first.")

    state = load_state(paths.state)
    new_items = stable_sort_items(compute_new_items(collected, state))
    lookback_days = coerce_int(config.get("issue", {}).get("lookback_days"), default=0)
    issue_items = stable_sort_items(filter_items_by_lookback(new_items, lookback_days))
    date_jst = today_jst_iso()

    if not issue_items:
        print("No new items to summarize.")
        return 0

    max_items = int(config.get("llm", {}).get("max_items", 10))

    existing = read_json(paths.summaries, default={"summaries": {}, "issues": {}})
    summaries: dict[str, Any] = existing.get("summaries") if isinstance(existing, dict) else {}
    if not isinstance(summaries, dict):
        summaries = {}
    issues: dict[str, Any] = existing.get("issues") if isinstance(existing, dict) else {}
    if not isinstance(issues, dict):
        issues = {}

    base_url = config.get("llm", {}).get("base_url", {}).get(provider) or _default_base_url(provider)
    model = config.get("llm", {}).get("model", {}).get(provider) or (
        "deepseek-v4-flash" if provider == "deepseek" else "gpt-4o-mini"
    )
    temperature = float(config.get("llm", {}).get("temperature", 0))

    featured_count = coerce_int(config.get("issue", {}).get("featured_papers"), default=12)

    changed = False

    digest_enabled = bool(config.get("llm", {}).get("digest_enabled", True))
    digest_max_items = coerce_int(config.get("llm", {}).get("digest_max_items"), default=40)
    need_digest = (
        digest_enabled
        and issue_items
        and (
            date_jst not in issues
            or not isinstance(issues.get(date_jst), dict)
            or "digest" not in issues[date_jst]
        )
    )
    if need_digest:
        try:
            issues[date_jst] = issues.get(date_jst) if isinstance(issues.get(date_jst), dict) else {}
            issues[date_jst]["digest"] = summarize_digest(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                items=issue_items[: max(1, digest_max_items)],
                featured_count=max(1, featured_count),
            )
            changed = True
            print(f"Summarized digest for {date_jst}")
        except Exception as e:
            print(f"Failed to summarize digest for {date_jst}: {e}")

    digest = None
    if date_jst in issues and isinstance(issues.get(date_jst), dict):
        d = issues[date_jst].get("digest")
        if isinstance(d, dict):
            digest = d

    item_by_id = {i.get("id"): i for i in issue_items if i.get("id")}
    featured_ids: list[str] = []
    if digest and isinstance(digest.get("featured_ids"), list):
        featured_ids = [str(x) for x in digest["featured_ids"] if str(x)]

    prioritized: list[dict[str, Any]] = []
    used: set[str] = set()
    for fid in featured_ids:
        item = item_by_id.get(fid)
        if item and fid not in used:
            prioritized.append(item)
            used.add(fid)
    for item in issue_items:
        item_id = item.get("id")
        if item_id and item_id in used:
            continue
        prioritized.append(item)

    to_summarize = prioritized[:max_items]
    for item in to_summarize:
        item_id = item.get("id")
        if not item_id or item_id in summaries:
            continue
        try:
            summaries[item_id] = summarize_one(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                item=item,
            )
            changed = True
            print(f"Summarized {item_id}")
        except Exception as e:
            print(f"Failed to summarize {item_id}: {e}")

    trend_enabled = bool(config.get("llm", {}).get("trend_enabled", True))
    trend_max_items = coerce_int(config.get("llm", {}).get("trend_max_items"), default=25)
    need_trend = (
        trend_enabled
        and issue_items
        and (
            date_jst not in issues
            or not isinstance(issues.get(date_jst), dict)
            or "trend" not in issues[date_jst]
        )
    )
    if need_trend:
        try:
            issues[date_jst] = issues.get(date_jst) if isinstance(issues.get(date_jst), dict) else {}
            issues[date_jst]["trend"] = summarize_trend(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                items=issue_items[: max(1, trend_max_items)],
            )
            changed = True
            print(f"Summarized trend for {date_jst}")
        except Exception as e:
            print(f"Failed to summarize trend for {date_jst}: {e}")

    if not changed:
        print("No new summaries created.")
        return 0

    payload = {"summaries": summaries, "issues": issues}
    write_json_if_changed(paths.summaries, payload)
    print(f"Wrote summaries → {paths.summaries}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
