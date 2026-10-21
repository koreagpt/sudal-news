"""뉴스 사이에 끼우는 협회 강의 카드: 매일 다른 강의를, 그날 이야기와 자연스럽게 이어지는 말로 소개한다.

강의 정보는 data/courses.json(사이트에 적힌 내용만)에서 가져오고, 소개 문구에는 그 사실만 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

from . import llm

STYLES = [
    ("공감", "독자가 겪을 법한 상황에 공감하며 시작한다 (예: '~할 때 막막했다면')."),
    ("오늘 연결", "오늘 뉴스나 웹툰 이야기에서 자연스럽게 이어 간다 (예: '오늘 웹툰처럼 ~라면')."),
    ("팁", "짧은 업무 팁처럼 말한다 (예: '~는 이렇게 하면 편해요')."),
    ("질문", "가볍게 질문을 던진다 (예: '~, 아직 손으로 하고 있나요?')."),
    ("수달 추천", "수달 사원이 동료에게 슬쩍 권하는 느낌으로 쓴다."),
]

INSTRUCTIONS = """너는 '한국GPT협회 수달일보'의 편집자다. AI 뉴스 6건 사이에 협회 강의 하나를 자연스럽게 소개하는 카드를 쓴다.
광고 티를 줄이고, 독자가 '아 이런 거에 도움 되는 강의가 있구나' 하고 느끼게 쓴다.

규칙
- 후보 중 오늘 이야기와 가장 자연스럽게 이어지는 강의 하나를 고른다. 딱 맞는 게 없으면 일반 직장인에게 유용한 것을 고른다.
- 강의 정보(facts)에 적힌 내용만 쓴다. 가격, 할인, 수강 효과·시간 절약 수치, '최고·1위·무조건' 같은 과장, 마감 압박은 쓰지 않는다.
- 뉴스의 사실을 바꾸거나 강의와 억지로 엮지 않는다. 연결이 약하면 그냥 일상적인 필요로 소개한다.
- 지정한 말투 유형(style)을 따른다.
- hook: 카드 첫 줄. 22자 이내.
- pitch: 이 강의가 무엇에 도움이 되는지 한두 문장, 70자 이내, 존댓말.
- comment: 수달 사원의 한마디. 반말, 30자 이내, 이모지 없이."""

SCHEMA = {
    "type": "object",
    "properties": {
        "course_id": {"type": "string"},
        "hook": {"type": "string"},
        "pitch": {"type": "string"},
        "comment": {"type": "string"},
    },
    "required": ["course_id", "hook", "pitch", "comment"],
    "additionalProperties": False,
}


def load_courses(project: Path) -> list[dict]:
    path = project / "data" / "courses.json"
    return json.loads(path.read_text(encoding="utf-8"))["courses"] if path.exists() else []


def _recent_ids(project: Path, day: str, days: int = 7) -> set[str]:
    """최근 며칠 동안 이미 소개한 강의 (매일 다른 강의가 나오게)."""
    seen, today = set(), date.fromisoformat(day)
    for back in range(1, days + 1):
        path = project / "data" / "news" / f"{(today - timedelta(days=back)).isoformat()}.json"
        if path.exists():
            ad = json.loads(path.read_text(encoding="utf-8")).get("ad") or {}
            if ad.get("course_id"):
                seen.add(ad["course_id"])
    return seen


def _today_text(news: dict, webtoon_title: str = "") -> str:
    parts = [f"{item['title']} — {item.get('summary', '')}" for item in news.get("items", [])]
    if webtoon_title:
        parts.append(f"오늘 웹툰: {webtoon_title}")
    if (news.get("webtoon_suggestion") or {}).get("idea"):
        parts.append(f"웹툰 아이디어: {news['webtoon_suggestion']['idea']}")
    return "\n".join(parts)


def candidates(courses: list[dict], text: str, recent: set[str], day: str) -> list[dict]:
    """오늘 이야기와 관련 있는 강의 2개 + 무작위 2개 (최근에 나온 강의는 빼고)."""
    pool = [course for course in courses if course["id"] not in recent] or courses
    rng = random.Random(int(hashlib.sha256(day.encode()).hexdigest(), 16))

    generic = {"AI", "GPT", "&", "과정", "코스", "기본과정", "심화과정", "고급", "기본", "(기본과정)", "(고급", "과정)", "챗GPT", "생성형"}

    def score(course):
        words = [w for w in course["good_for"] + course["title"].replace(",", " ").split() if w not in generic]
        return sum(1 for word in words if len(word) >= 2 and word in text) + rng.random() * 0.8

    ranked = sorted(pool, key=score, reverse=True)
    chosen = ranked[:2]
    rest = [course for course in pool if course not in chosen]
    rng.shuffle(rest)
    return chosen + rest[:2]


def _fallback(course: dict, style: str) -> dict:
    """GPT 없이 쓰는 간단한 소개 (강의 사실만으로)."""
    topic = course["good_for"][0]
    hooks = {  # 조사(은/는/이/가)가 붙지 않는 문장으로만 만든다
        "공감": f"{topic} 고민이라면",
        "오늘 연결": f"오늘 같은 날 필요한 {topic} 강의",
        "팁": f"{topic}, 더 편하게 하는 법",
        "질문": f"{topic}, 아직 손으로 하나요?",
        "수달 추천": "수달 사원이 슬쩍 권하는 강의",
    }
    return {"hook": hooks.get(style, hooks["공감"]), "pitch": course["facts"], "comment": "나도 이건 좀 들어봐야겠다."}


def make(project: Path, config: dict, day: str, news: dict, webtoon_title: str = "") -> dict | None:
    courses = load_courses(project)
    if not courses:
        return None
    text = _today_text(news, webtoon_title)
    pool = candidates(courses, text, _recent_ids(project, day), day)
    style_name, style_rule = STYLES[int(hashlib.sha256(f"style{day}".encode()).hexdigest(), 16) % len(STYLES)]
    by_id = {course["id"]: course for course in pool}

    copy, chosen = None, pool[0]
    if llm.has_key():
        listing = "\n".join(f"- id={c['id']} | {c['title']} ({c['format']}) | facts: {c['facts']}" for c in pool)
        try:
            data = llm.ask_json(
                config["curation"]["model"], INSTRUCTIONS,
                f"오늘 이야기:\n{text}\n\n강의 후보:\n{listing}\n\n말투 유형(style): {style_name} — {style_rule}",
                SCHEMA, "course_card", "low",
            )
            if data["course_id"] in by_id:
                chosen = by_id[data["course_id"]]
                copy = {key: data[key].strip() for key in ("hook", "pitch", "comment")}
        except Exception as error:  # 강의 카드가 실패해도 뉴스 발행은 계속
            print(f"[경고] 강의 카드 문구 생성 실패, 기본 문구로: {type(error).__name__}: {error}")
    copy = copy or _fallback(chosen, style_name)
    return {"course_id": chosen["id"], "title": chosen["title"], "url": chosen["url"], "format": chosen["format"],
            "style": style_name, **copy}
