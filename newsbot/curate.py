"""후보 기사 중 오늘의 뉴스를 고르고 한국어로 요약한다.

ANTHROPIC_API_KEY가 있으면 Claude가 선별·요약하고,
없거나 실패하면 키워드 점수로 고르는 기본 모드로 동작한다.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone

CATEGORIES = ["서비스·제품", "업무활용", "연구·기술", "기업·투자", "정책·사회", "교육"]

SYSTEM_PROMPT = """너는 '한국GPT협회 수달일보'의 편집자다. 수달일보는 AI 교육 회사 한국GPT협회(기업강의·온라인교육)에 다니는 수달 사원이 매일 아침 협회 카카오 오픈채팅방에 올리는 AI 뉴스 브리핑이다.
독자는 AI를 업무와 생활에 써보고 싶은 한국 직장인과 학습자다. 개발자나 투자자가 아니다.

편집 원칙
- 독자가 "오, 나도 써볼 수 있겠다" 또는 "이건 알아둬야겠다"라고 느낄 기사를 고른다. 새 서비스·기능, 업무 활용 사례, 일상에 영향을 주는 정책·사회 변화가 우선이다.
- 같은 사건을 다룬 기사는 하나만 고른다. 한 회사 소식이 여러 개를 차지하지 않게 주제를 고르게 섞는다.
- 실적·주가, 지자체 행사·협약·MOU, 단순 인사·사옥 이전, 보도자료성 홍보 기사는 피한다.
- 영어 기사도 고를 수 있다. 제목과 요약은 반드시 자연스러운 한국어로 쓴다.
- 제공된 제목과 발췌에 있는 사실만 쓴다. 발췌에 없는 수치·날짜·인용·평가를 지어내지 않는다. 정보가 적으면 짧게 쓴다.

작성 규칙
- title_ko: 원문 의미를 지킨 간결한 한국어 제목. 40자 이내. 낚시성 과장 금지.
- summary_ko: 무엇이 일어났는지 1~2문장, 120자 이내. 존댓말(~했습니다/~입니다).
- sudal_comment: 한국GPT협회에 다니는, 피곤하지만 다정한 수달 사원이 동료에게 건네는 한마디. 반말, 40자 이내, 독자 입장에서 의미를 짚는다. 이모지 금지. 협회나 강의 홍보 문구는 넣지 않는다.
- category: 주어진 목록 중 하나.
- 마지막으로, 고른 기사 중 직장인의 일상 장면으로 4컷 웹툰을 만들기 가장 좋은 기사 하나를 webtoon에 지정하고, 수달 사원이 등장하는 4컷 아이디어를 한 문장으로 쓴다."""


def _schema(count: int) -> dict:
    item = {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "integer"},
            "title_ko": {"type": "string"},
            "summary_ko": {"type": "string"},
            "sudal_comment": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES},
        },
        "required": ["candidate_id", "title_ko", "summary_ko", "sudal_comment", "category"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": item},
            "webtoon": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "idea": {"type": "string"},
                },
                "required": ["candidate_id", "idea"],
                "additionalProperties": False,
            },
        },
        "required": ["items", "webtoon"],
        "additionalProperties": False,
    }


def _candidate_block(candidates: list[dict]) -> str:
    lines = []
    for index, item in enumerate(candidates):
        when = item["published"].astimezone(timezone.utc).strftime("%m-%d %H:%M UTC")
        snippet = f"\n   발췌: {item['snippet'][:300]}" if item["snippet"] else ""
        lines.append(f"[{index}] ({item['source']}, {when}) {item['title']}{snippet}")
    return "\n".join(lines)


def _source_entry(item: dict) -> dict:
    return {
        "link": item["link"],
        "source": item["source"],
        "original_title": item["title"],
        "lang": item["lang"],
        "published": item["published"].isoformat(),
    }


def curate_with_claude(candidates: list[dict], count: int, model: str) -> dict:
    import anthropic  # 기본 모드만 쓸 때는 SDK 없이도 동작하도록 여기서 불러온다

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"오늘의 후보 기사 {len(candidates)}개다. 이 중 {count}개를 골라 작성 규칙대로 정리해줘. "
                f"candidate_id는 대괄호 안 번호다. 독자에게 가장 흥미로운 순서로 정렬해줘.\n\n"
                + _candidate_block(candidates)
            ),
        }],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _schema(count)},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 요청을 거절했습니다.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("응답이 max_tokens에서 잘렸습니다.")
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)

    items, used = [], set()
    for entry in data["items"]:
        index = entry["candidate_id"]
        if not (0 <= index < len(candidates)) or index in used:
            continue  # 없는 번호나 중복은 버린다 (링크는 항상 실제 후보에서 가져온다)
        used.add(index)
        items.append({
            "title": entry["title_ko"].strip(),
            "summary": entry["summary_ko"].strip(),
            "comment": entry["sudal_comment"].strip(),
            "category": entry["category"],
            **_source_entry(candidates[index]),
        })
        if len(items) >= count:
            break
    if not items:
        raise RuntimeError("유효한 기사가 하나도 선택되지 않았습니다.")

    webtoon = None
    pick = data.get("webtoon") or {}
    if 0 <= pick.get("candidate_id", -1) < len(candidates):
        webtoon = {"idea": pick["idea"].strip(), **_source_entry(candidates[pick["candidate_id"]])}
    return {"mode": "claude", "model": response.model, "items": items, "webtoon_suggestion": webtoon}


# ---- 기본 모드 (API 없이 키워드 점수) ----

SOURCE_WEIGHT = {"aitimes": 3.0, "zdnet_kr": 2.5, "etnews": 2.5, "bloter": 2.0, "gnews_kr": 1.0}
BOOST = re.compile(
    r"챗GPT|오픈AI|OpenAI|구글|제미나이|클로드|앤트로픽|엔비디아|삼성|네이버|카카오|메타|애플|"
    r"마이크로소프트|(?<![A-Za-z])MS(?![A-Za-z])|코파일럿|딥시크|퍼플렉시티|xAI"
)
PRACTICAL = re.compile(r"출시|공개|기능|무료|업무|활용|써보고서|앱|에이전트|업데이트|도입|교육")
PENALTY = re.compile(r"실적|주가|영업익|매출|자문단|성료|신간|협약|MOU|사옥|이전|개최|선정|수상|인사|부고|포럼")


def _score(item: dict, now: datetime) -> float:
    title = item["title"]
    hours = max((now - item["published"]).total_seconds() / 3600, 0)
    score = SOURCE_WEIGHT.get(item["feed_id"], 1.0)
    score += 2.0 if BOOST.search(title) else 0
    score += 1.0 if PRACTICAL.search(title) else 0
    score -= 2.5 if PENALTY.search(title) else 0
    return score + 2.0 * math.exp(-hours / 18)


def curate_basic(candidates: list[dict], count: int) -> dict:
    now = datetime.now(timezone.utc)
    korean = [item for item in candidates if item["lang"] == "ko"]  # 번역 없이 보여줄 수 있는 기사만
    ranked = sorted(korean, key=lambda item: _score(item, now), reverse=True)
    items, per_source = [], {}
    for item in ranked:
        if per_source.get(item["source"], 0) >= 2:
            continue
        per_source[item["source"]] = per_source.get(item["source"], 0) + 1
        items.append({"title": item["title"], "summary": "", "comment": "", "category": "AI 뉴스", **_source_entry(item)})
        if len(items) >= count:
            break
    return {"mode": "basic", "model": None, "items": items, "webtoon_suggestion": None}


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def curate(candidates: list[dict], count: int, model: str, use_claude: bool = True) -> dict:
    if use_claude and has_credentials():
        try:
            return curate_with_claude(candidates, count, model)
        except Exception as error:
            print(f"[경고] Claude 선별 실패, 기본 모드로 진행합니다: {type(error).__name__}: {error}")
    elif use_claude:
        print("[안내] ANTHROPIC_API_KEY가 없어 기본 모드(키워드 선별, 요약 없음)로 진행합니다.")
    return curate_basic(candidates, count)
