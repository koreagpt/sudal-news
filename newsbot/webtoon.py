"""오늘의 뉴스 하나로 수달 사원 4컷 웹툰을 만든다: 대본 → 작화 → 검수.

컷온 웹툰 제작 스킬의 원칙(인물 고정값 유지, 짧고 정확한 대사, 가상 상황 표기,
실제 결과물 검수, 결함 있는 결과는 완성으로 처리하지 않기)을 자동화했다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import KST, llm

CHARACTER = (
    "수달 사원: 늘 피곤해 보이는 반쯤 감긴 눈, 베이지색 털, 크림색 주둥이와 가슴, "
    "남색 카디건, 흰 셔츠, 목에 건 사원증, 회색 바지. 무뚝뚝하지만 다정하다. 한국GPT협회에 다닌다."
)

SCRIPT_INSTRUCTIONS = f"""너는 '한국GPT협회 수달일보'의 웹툰 작가다. 매일 아침 AI 뉴스 하나를 소재로 수달 사원이 주인공인 세로 4컷 웹툰 대본을 쓴다.

주인공 고정 설정 (바꾸지 않는다)
- {CHARACTER}
- 배경은 사무실, 집, 출퇴근길 같은 평범한 직장인의 일상이다.

이야기 원칙
- 뉴스의 핵심을 직장인 일상 장면으로 옮긴다. 1컷 상황 → 2컷 AI에게 시도하거나 소식을 접함 → 3컷 발견·반전 → 4컷 정리와 여운.
- 뉴스에 없는 사실(수치, 날짜, 기능, 발언)을 사실처럼 쓰지 않는다. 필요하면 일반적인 상황으로 표현한다.
- 실존 인물의 얼굴, 실제 회사 로고, 실제 제품 화면을 그리지 않는다. 서비스 이름은 대사에 꼭 필요할 때만 쓴다.
- 혐오, 비하, 정치적 편향, 공포 조장 없이 따뜻하고 피식 웃게 되는 톤으로 쓴다.
- 협회나 강의 광고 문구는 넣지 않는다. 마무리 문구는 AI를 잘 쓰는 태도에 대한 짧은 생각으로 끝낸다.

글자 규칙 (그림에 그대로 그려지므로 짧고 정확하게)
- title 12자 이내, subtitle 16자 이내.
- panels는 정확히 4개. 컷마다 말풍선 1~2개, 말풍선 하나는 18자 이내, 전체 말풍선 6개 이하.
- speaker는 "수달", "AI", 또는 꼭 필요한 조연 이름 하나.
- closing_line1, closing_line2는 각각 18자 이내.
- scene은 그림 작가에게 주는 장면 설명이다. 장소, 수달의 행동과 표정, 소품, 구도를 2문장 이내로 쓴다.
- alt는 시각장애인을 위한 4컷 전체 설명이다. 300자 이내."""

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene": {"type": "string"},
                    "bubbles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"speaker": {"type": "string"}, "text": {"type": "string"}},
                            "required": ["speaker", "text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["scene", "bubbles"],
                "additionalProperties": False,
            },
        },
        "closing_line1": {"type": "string"},
        "closing_line2": {"type": "string"},
        "alt": {"type": "string"},
    },
    "required": ["title", "subtitle", "panels", "closing_line1", "closing_line2", "alt"],
    "additionalProperties": False,
}

REVIEW_INSTRUCTIONS = """너는 웹툰 검수자다. 첨부된 첫 번째 이미지는 새로 그린 4컷 웹툰, 두 번째 이미지는 주인공 수달 사원의 인물 기준 그림이다.
아래 기준으로 엄격하게 확인하고, 애매하면 통과시키지 않는다.
- 위에서 아래로 컷이 정확히 4개인가.
- 함께 준 '그려야 할 글자' 목록(제목, 말풍선, 마무리 문구, 하단 안내·출처)이 한 글자도 틀리지 않고 읽히는가. 깨진 글자, 빠진 글자, 엉뚱한 글자, 목록에 없는 읽히는 글자가 있으면 text_errors에 적는다.
- 문장부호(마침표, 쉼표, 말줄임표, 물음표)만 조금 다른 것은 오류가 아니다.
- 배경 소품(서류, 화면, 메모)의 읽을 수 없는 선이나 장식 무늬는 오류가 아니다. 다만 깨진 한글처럼 보이는 글자가 눈에 띄게 크면 오류다.
- 모든 컷의 수달이 인물 기준과 같은 캐릭터인가 (베이지 털, 크림색 주둥이, 남색 카디건, 흰 셔츠, 사원증).
- 실존 회사 로고나 실존 인물 얼굴처럼 보이는 것이 없는가.
problems에는 다시 그릴 때 고쳐야 할 점을 짧게 적는다."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "panel_count": {"type": "integer"},
        "text_errors": {"type": "array", "items": {"type": "string"}},
        "character_consistent": {"type": "boolean"},
        "has_real_logo_or_person": {"type": "boolean"},
        "problems": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["panel_count", "text_errors", "character_consistent", "has_real_logo_or_person", "problems"],
    "additionalProperties": False,
}

NOTE = "AI 뉴스를 바탕으로 한 가상 상황입니다."


def pick_topic(news: dict, topic: int | None = None) -> dict:
    """웹툰 소재: 지정한 번호의 뉴스 → AI 추천 → 첫 번째 뉴스 순."""
    items = news.get("items", [])
    if topic and 1 <= topic <= len(items):
        item = items[topic - 1]
        return {"idea": "", **item}
    if news.get("webtoon_suggestion"):
        return news["webtoon_suggestion"]
    if items:
        return {"idea": "", **items[0]}
    raise RuntimeError("웹툰 소재로 쓸 뉴스가 없습니다.")


def write_script(model: str, source: dict) -> dict:
    lines = [
        f"뉴스 제목: {source.get('title') or source.get('original_title')}",
        f"원제목: {source.get('original_title', '')}",
        f"요약: {source.get('summary', '')}",
        f"출처: {source.get('source', '')}",
    ]
    if source.get("idea"):
        lines.append(f"편집자의 4컷 아이디어: {source['idea']}")
    script = llm.ask_json(model, SCRIPT_INSTRUCTIONS, "\n".join(lines), SCRIPT_SCHEMA, "webtoon_script", "low")
    if len(script["panels"]) != 4:
        raise RuntimeError(f"대본의 컷 수가 4개가 아닙니다: {len(script['panels'])}개")
    return script


def image_prompt(script: dict, source_name: str, feedback: list[str]) -> str:
    panels = []
    for number, panel in enumerate(script["panels"], 1):
        bubbles = " / ".join(f'{bubble["speaker"]}: "{bubble["text"]}"' for bubble in panel["bubbles"])
        panels.append(f"Panel {number}: {panel['scene']} Speech bubbles — {bubbles}")
    prompt = f"""Create a vertical 4-panel Korean webtoon page, clean warm digital illustration in exactly the same art style as the second reference image.
Main character: the otter office worker from the first reference image (character sheet). Keep his face, half-closed tired eyes, beige fur, cream muzzle and chest, navy cardigan, white shirt, ID card on a lanyard and grey trousers identical in every panel.

Layout from top to bottom:
- Header on a cream background: large bold rounded Korean title "{script['title']}" with a soft yellow highlighter stripe behind it, and a smaller subtitle "{script['subtitle']}" under it.
- Four stacked horizontal panels with thin dark borders and small gutters.
{chr(10).join(panels)}
- Footer on a cream background: two lines of large bold Korean text, first line "{script['closing_line1']}" in dark navy, second line "{script['closing_line2']}" in dark brown with a yellow highlighter stripe.
- Tiny grey text at the very bottom: left "{NOTE}", right "소재: {source_name}".

Text rules: render every Korean string exactly as written, character by character. Put dialogue in white rounded speech bubbles with dark outlines whose tails point to the speaker. Documents, papers, phone and laptop screens in the scenes show only simple icons, blocks or lines, never letters. Do not add any other text, English words, signatures, watermarks, brand logos or real people."""
    if feedback:
        prompt += "\n\nThe previous attempt had these problems. Fix them:\n- " + "\n- ".join(feedback)
    return prompt


def review(model: str, image: Path, character: Path, script: dict, source_name: str) -> dict:
    expected = [f"제목: {script['title']}", f"부제: {script['subtitle']}"]
    for number, panel in enumerate(script["panels"], 1):
        expected += [f"{number}컷 말풍선 ({bubble['speaker']}): {bubble['text']}" for bubble in panel["bubbles"]]
    expected += [f"마무리 1: {script['closing_line1']}", f"마무리 2: {script['closing_line2']}",
                 f"하단 왼쪽 작은 글씨: {NOTE}", f"하단 오른쪽 작은 글씨: 소재: {source_name}"]
    content = [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "그려야 할 글자 (이 밖의 읽히는 글자는 없어야 함):\n" + "\n".join(expected)},
            llm.image_part(image),
            llm.image_part(character),
        ],
    }]
    result = llm.ask_json(model, REVIEW_INSTRUCTIONS, content, REVIEW_SCHEMA, "webtoon_review", "low")
    result["passed"] = (
        result["panel_count"] == 4
        and not result["text_errors"]
        and result["character_consistent"]
        and not result["has_real_logo_or_person"]
    )
    return result


def _og_crop(path: Path) -> list[int]:
    """카톡 썸네일에 쓸 윗부분(제목과 1~2컷) 영역."""
    from PIL import Image

    with Image.open(path) as image:
        width = image.width
    left, right = round(width * 0.2), round(width * 0.94)
    return [left, 0, right, round((right - left) * 570 / 520)]


def make(project: Path, config: dict, day: str, news: dict, topic: int | None = None) -> dict:
    """웹툰을 만들어 data/webtoons에 저장하고 결과(성공 여부·시도·문제)를 돌려준다."""
    settings = config["webtoon"]
    source = pick_topic(news, topic)
    references = [project / path for path in settings["references"]]
    status = {
        "ok": False,
        "attempts": 0,
        "topic": source.get("title") or source.get("original_title"),
        "source": source.get("source"),
        "problems": [],
        "made_at": datetime.now(KST).isoformat(timespec="minutes"),
    }

    script = write_script(settings["script_model"], source)
    status["title"] = script["title"]
    status["script"] = script  # 검수에서 떨어져도 대본은 남겨 둔다 (사람이 시안을 직접 채택할 때 사용)
    drafts = project / "data" / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    feedback: list[str] = []
    for attempt in range(1, settings["max_attempts"] + 1):
        status["attempts"] = attempt
        quality = settings["quality"] if attempt == 1 else settings["retry_quality"]
        print(f"  웹툰 작화 {attempt}차 시도 (화질 {quality})")
        image = llm.draw(
            settings["image_model"], image_prompt(script, source.get("source", ""), feedback),
            references, settings["size"], quality,
        )
        draft = drafts / f"{day}-try{attempt}.jpg"
        draft.write_bytes(image)
        verdict = review(settings["review_model"], draft, references[0], script, source.get("source", ""))
        feedback = verdict["text_errors"] + verdict["problems"]
        status["problems"] = feedback
        if verdict["passed"]:
            break
        print(f"  검수 미통과: {feedback}")
    else:
        print("  [안내] 검수를 통과한 웹툰이 없어 어제 웹툰을 유지합니다. 시도한 그림은 data/drafts/에 있습니다.")
        return status

    path = project / "data" / "webtoons.json"
    webtoons = json.loads(path.read_text(encoding="utf-8"))
    for old in [toon for toon in webtoons if toon["date"] == day and toon.get("auto")]:
        (project / "data" / "webtoons" / old["image"]).unlink(missing_ok=True)  # 같은 날 다시 만들면 이전 그림 교체
    webtoons = [toon for toon in webtoons if not (toon["date"] == day and toon.get("auto"))]

    stamp = datetime.now(KST).strftime("%H%M%S")
    filename = f"{day}-{stamp}.jpg"
    target = project / "data" / "webtoons" / filename
    target.write_bytes(draft.read_bytes())
    webtoons.append({
        "id": f"{day}-{stamp}",
        "date": day,
        "title": script["title"],
        "subtitle": script["subtitle"],
        "image": filename,
        "alt": script["alt"],
        "message": f"{script['closing_line1']} {script['closing_line2']}",
        "note": NOTE,
        "source_name": source.get("source", ""),
        "source_url": source.get("link", ""),
        "og_crop": _og_crop(target),
        "auto": True,
        "script": script,
    })
    path.write_text(json.dumps(webtoons, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status.update(ok=True, image=filename)
    print(f"  웹툰 완성 → data/webtoons/{filename} ({script['title']})")
    return status
