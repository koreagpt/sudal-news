"""RSS/Atom 피드에서 최근 AI 뉴스 후보를 모은다. 표준 라이브러리만 사용."""
from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import KST

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
USER_AGENT = "Mozilla/5.0 (compatible; SudalNewsBot/1.0)"

# 일반 IT 매체에서 AI 기사만 고르기 위한 키워드
AI_PATTERN = re.compile(
    r"(?<![A-Za-z])(AI|AGI|LLM|GPT|GenAI)(?![A-Za-z])|인공지능|생성형|챗GPT|챗지피티|오픈AI|앤트로픽|"
    r"클로드|제미나이|코파일럿|딥러닝|머신러닝|에이전트|파운데이션 모델|OpenAI|Anthropic|Claude|Gemini|"
    r"Copilot|ChatGPT|Llama|Mistral|DeepSeek|딥시크|xAI|Grok|그록|Perplexity|퍼플렉시티",
    re.IGNORECASE,
)


def _text(element, *tags):
    for tag in tags:
        found = element.find(tag)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _clean(value: str, limit: int = 400) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def _parse_date(value: str):
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:  # 국내 매체의 시간대 없는 표기는 한국 시간으로 본다
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(timezone.utc)


def _parse_feed(feed: dict, data: bytes) -> list[dict]:
    root = ET.fromstring(data)
    entries = root.findall(".//item")
    atom = not entries
    if atom:
        entries = root.findall(f".//{ATOM}entry")
    items = []
    for entry in entries:
        if atom:
            title = _text(entry, f"{ATOM}title")
            link_el = entry.find(f"{ATOM}link[@rel='alternate']")
            if link_el is None:  # Element는 자식이 없으면 거짓이라 `or`를 쓰지 않는다
                link_el = entry.find(f"{ATOM}link")
            link = link_el.get("href", "") if link_el is not None else ""
            summary = _text(entry, f"{ATOM}summary", f"{ATOM}content")
            published = _text(entry, f"{ATOM}published", f"{ATOM}updated")
            source = feed["name"]
        else:
            title = _text(entry, "title")
            link = _text(entry, "link")
            summary = _text(entry, "description")
            published = _text(entry, "pubDate", f"{DC}date")
            source = _text(entry, "source") or feed["name"]
            # 구글뉴스 제목 끝의 " - 언론사" 꼬리표 제거
            if feed["id"].startswith("gnews") and title.endswith(f" - {source}"):
                title = title[: -len(source) - 3]
        title = _clean(title, 200)
        if not title or not link.startswith("http"):
            continue
        summary = _clean(summary)
        if summary.startswith(title):  # 구글뉴스는 설명이 제목 반복
            summary = ""
        items.append({
            "title": title,
            "link": link.strip(),
            "snippet": summary,
            "source": source,
            "feed_id": feed["id"],
            "lang": feed.get("lang", "ko"),
            "published": _parse_date(published),
        })
    return items


def _download(feed: dict):
    request = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return feed, _parse_feed(feed, response.read()), None
    except Exception as error:  # 피드 하나가 실패해도 나머지로 진행
        return feed, [], f"{type(error).__name__}: {error}"


def _key(title: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", title.lower())[:28]


def collect(feeds: list[dict], window_hours: int, now: datetime | None = None) -> tuple[list[dict], dict]:
    """최근 window_hours 안의 AI 기사 후보를 중복 없이 최신순으로 반환."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)
    report, seen_links, seen_titles, results = {}, set(), set(), []
    with ThreadPoolExecutor(max_workers=8) as pool:
        downloads = list(pool.map(_download, feeds))
    for feed, items, error in downloads:
        kept = 0
        for item in items:
            if item["published"] is None or not (since <= item["published"] <= now + timedelta(hours=1)):
                continue
            if not feed.get("ai_only") and not AI_PATTERN.search(item["title"] + " " + item["snippet"]):
                continue
            key = _key(item["title"])
            if item["link"] in seen_links or key in seen_titles:
                continue
            seen_links.add(item["link"])
            seen_titles.add(key)
            results.append(item)
            kept += 1
        report[feed["id"]] = {"fetched": len(items), "kept": kept, "error": error}
    results.sort(key=lambda item: item["published"], reverse=True)
    return results, report


def balance(candidates: list[dict], limit: int, per_feed: int = 12) -> list[dict]:
    """한 피드가 후보를 독차지하지 않도록 피드당 개수를 제한."""
    counts, picked = {}, []
    for item in candidates:
        if counts.get(item["feed_id"], 0) >= per_feed:
            continue
        counts[item["feed_id"]] = counts.get(item["feed_id"], 0) + 1
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked
