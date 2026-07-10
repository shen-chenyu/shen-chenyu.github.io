from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml


JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class Paths:
    state: Path
    collected: Path
    summaries: Path
    issues_dir: Path
    index: Path


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    config.setdefault("arxiv", {})
    config["arxiv"].setdefault(
        "user_agent",
        "shen-chenyu-daily-bot/1.0 (https://github.com/shen-chenyu/shen-chenyu.github.io)",
    )
    config["arxiv"].setdefault("queries", [])

    config.setdefault("issue", {})
    config["issue"].setdefault("lookback_days", 0)
    config["issue"].setdefault("mark_skipped_as_seen", False)
    config["issue"].setdefault("featured_papers", 12)
    config["issue"].setdefault("include_more_section", True)
    config["issue"].setdefault("more_titles_max", 80)

    config.setdefault("data", {})
    config["data"].setdefault("state_path", "data/state.json")
    config["data"].setdefault("collected_path", "data/collected.json")
    config["data"].setdefault("summaries_path", "data/summaries.json")

    config.setdefault("output", {})
    config["output"].setdefault("issues_dir", "daily/issues")
    config["output"].setdefault("index_path", "daily/index.md")

    config.setdefault("llm", {})
    config["llm"].setdefault("enabled", True)
    config["llm"].setdefault("provider_preference", ["deepseek", "openai"])
    config["llm"].setdefault(
        "model", {"deepseek": "deepseek-chat", "openai": "gpt-4o-mini"}
    )
    config["llm"].setdefault("max_items", 10)
    config["llm"].setdefault("trend_enabled", True)
    config["llm"].setdefault("trend_max_items", 25)
    config["llm"].setdefault("digest_enabled", True)
    config["llm"].setdefault("digest_max_items", 40)
    config["llm"].setdefault("temperature", 0)

    return config


def resolve_paths(config: dict[str, Any], config_path: Path) -> Paths:
    base_dir = config_path.resolve().parent

    def p(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else (base_dir / candidate)

    return Paths(
        state=p(config["data"]["state_path"]),
        collected=p(config["data"]["collected_path"]),
        summaries=p(config["data"]["summaries_path"]),
        issues_dir=p(config["output"]["issues_dir"]),
        index=p(config["output"]["index_path"]),
    )


def today_jst_iso() -> str:
    return datetime.now(timezone.utc).astimezone(JST).date().isoformat()


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str) -> datetime:
    # arXiv returns ISO timestamps with "Z"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def coerce_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def published_datetime_utc(item: dict[str, Any]) -> datetime | None:
    published_at = item.get("published_at")
    if not published_at:
        return None
    try:
        dt = parse_datetime(str(published_at))
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def filter_items_by_lookback(
    items: Iterable[dict[str, Any]],
    lookback_days: int,
    *,
    now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    items_list = list(items)
    lookback_days = max(0, int(lookback_days))
    if lookback_days == 0:
        return items_list

    # Interpret lookback in terms of calendar days in JST, not a strict rolling
    # N*24h window. This is more stable for a daily workflow that runs at a fixed
    # time (07:00 JST) and for sources that publish around specific daily times.
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_jst = now_utc.astimezone(JST)
    cutoff_date_jst = now_jst.date() - timedelta(days=lookback_days)

    filtered: list[dict[str, Any]] = []
    for item in items_list:
        published_dt = published_datetime_utc(item)
        if published_dt is None:
            filtered.append(item)
            continue
        published_date_jst = published_dt.astimezone(JST).date()
        if published_date_jst >= cutoff_date_jst:
            filtered.append(item)
    return filtered


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_text_if_changed(path: Path, content: str) -> bool:
    content = content if content.endswith("\n") else content + "\n"
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None

    if existing == content:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def write_json_if_changed(path: Path, data: Any) -> bool:
    content = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return write_text_if_changed(path, content)


def load_state(state_path: Path) -> dict[str, Any]:
    state = read_json(state_path, default={"last_run_date_jst": None, "seen_ids": []})
    state.setdefault("last_run_date_jst", None)
    state.setdefault("seen_ids", [])
    if not isinstance(state["seen_ids"], list):
        raise ValueError("state.seen_ids must be a list")
    return state


def compute_new_items(
    collected_items: Iterable[dict[str, Any]], state: dict[str, Any]
) -> list[dict[str, Any]]:
    seen = set(state.get("seen_ids", []))
    return [item for item in collected_items if item.get("id") not in seen]


def stable_sort_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[str, str]:
        published = item.get("published_at") or ""
        return (published, item.get("id") or "")

    return sorted(items, key=sort_key, reverse=True)


def first_sentence(text: str, max_len: int = 220) -> str:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return ""

    for sep in (". ", "? ", "! "):
        if sep in cleaned:
            cleaned = cleaned.split(sep, 1)[0].strip() + sep.strip()
            break

    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned
