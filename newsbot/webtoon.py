"""오늘의 뉴스 하나로 수달 사원 4컷 웹툰을 만든다: 대본 → 작화 → 검수.

컷온 웹툰 제작 스킬(인물 고정값, 짧고 정확한 대사, 가상 상황 표기, 실제 결과물 검수)과
애니메이션 작화·표정·행동·배경 스킬(설정집, 연기 브리프, 컷별 배경 밀도, 검수 순서)을 자동화했다.
설정은 data/bible.json 에 있다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import KST, llm

NOTE = "AI 뉴스를 바탕으로 한 가상 상황입니다."
SHOTS = ["롱샷", "미디엄", "클로즈업", "인서트"]
DENSITIES = ["establishing", "context", "contact", "none"]
DENSITY_EN = {
    "establishing": "wide establishing background that clearly introduces the place",
    "context": "background keeps the main structures and recurring props of the place",
    "contact": "minimal background, only the desk, chair or props the character touches",
    "none": "plain soft color background with a simple mood effect, no setting",
}
SHOT_EN = {"롱샷": "long shot", "미디엄": "medium shot", "클로즈업": "close-up", "인서트": "insert close-up of an object or hands"}


def load_bible(project: Path) -> dict:
    return json.loads((project / "data" / "bible.json").read_text(encoding="utf-8"))


def _bible_text(bible: dict) -> str:
    """대본 작가에게 줄 설정집 요약."""
    style, main = bible["style"], bible["main"]
    lines = [
        "[그림체]",
        f"- {style['profile']} {style['shape']} {style['color']} {style['background']}",
        f"[주인공: {main['name']}] {main['species']}",
        "- 고정: " + "; ".join(main["fixed"]),
        "- 허용 변형: " + "; ".join(main["allowed_variation"]),
        "- 금지: " + "; ".join(main["forbidden"]),
        f"- 성격: {main['personality']}",
        f"- 연기 습관: {main['acting']}",
        "[조연 — 이 인물만 쓴다]",
    ]
    lines += [f"- {c['name']} ({c['species']}): {c['look']} 성격: {c['personality']} 역할: {c['role']}" for c in bible["cast"]]
    lines.append("[장소 설정집 — id: 배치 / 빛]")
    lines += [f"- {loc['id']} {loc['name']}: {loc['layout']} / {loc['light']}" for loc in bible["locations"]]
    return "\n".join(lines)


def script_instructions(bible: dict) -> str:
    return f"""너는 '한국GPT협회 수달일보'의 웹툰 작가다. 매일 아침 AI 뉴스 하나를 소재로 수달 사원이 주인공인 세로 4컷 웹툰 대본을 쓴다.

{_bible_text(bible)}

이야기 원칙
- 뉴스의 핵심을 직장인 일상 장면으로 옮긴다. 1컷 상황 → 2컷 AI에게 시도하거나 소식을 접함 → 3컷 발견·반전 → 4컷 정리와 여운.
- 뉴스에 없는 사실(수치, 날짜, 기능, 발언)을 사실처럼 쓰지 않는다. 필요하면 일반적인 상황으로 표현한다.
- 실존 인물의 얼굴, 실제 회사 로고, 실제 제품 화면을 그리지 않는다. 서비스 이름은 대사에 꼭 필요할 때만 쓴다.
- 혐오, 비하, 정치적 편향, 공포 조장 없이 따뜻하고 피식 웃게 되는 톤으로 쓴다.
- 협회나 강의 광고 문구는 넣지 않는다. 마무리 문구는 AI를 잘 쓰는 태도에 대한 짧은 생각으로 끝낸다.

연기 규칙 (표정·행동)
- beat: 그 컷에서 독자가 새로 알게 되는 것 하나.
- acting: 누가 무엇을 보는지(시선), 손이 무엇을 쥐거나 만지는지(접촉), 몸 자세와 표정을 함께 쓴다. 얼굴만으로 감정을 해결하지 않는다.
- 수달은 연기 습관을 지킨다. 감탄·웃음 같은 큰 변화는 3컷이나 4컷 한 번에 몰아 준다.
- 같은 크기의 얼굴 클로즈업을 연달아 쓰지 않는다. 롱샷=공간, 미디엄=행동, 클로즈업=감정, 인서트=단서.
- 조연은 설정집 인물만, 필요할 때만 쓴다. 수달과 같은 종의 다른 캐릭터를 만들지 않는다.

배경 규칙
- location은 설정집의 id 중 하나. 설정집에 없는 곳이면 "other".
- density: 1컷은 장소를 알리는 establishing이나 context. 같은 장소가 이어지면 contact나 none으로 줄여 인물과 말풍선이 먼저 읽히게 한다. 장소가 바뀌면 다시 context.
- 설정집의 고정 배치(창 위치, 책상, 화분 등)를 바꾸지 않는다.

글자 규칙 (그림에 그대로 그려지므로 짧고 정확하게)
- title 12자 이내, subtitle 16자 이내.
- panels는 정확히 4개. 컷마다 말풍선 1~2개, 말풍선 하나는 18자 이내, 전체 말풍선 6개 이하.
- speaker는 "수달", "AI", 또는 조연 이름.
- closing_line1, closing_line2는 각각 18자 이내.
- scene은 그림 작가에게 주는 장면 설명(장소, 구도, 소품) 2문장 이내.
- alt는 시각장애인을 위한 4컷 전체 설명. 300자 이내."""


def script_schema(bible: dict) -> dict:
    location_ids = [loc["id"] for loc in bible["locations"]] + ["other"]
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "panels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "beat": {"type": "string"},
                        "shot": {"type": "string", "enum": SHOTS},
                        "location": {"type": "string", "enum": location_ids},
                        "density": {"type": "string", "enum": DENSITIES},
                        "characters": {"type": "array", "items": {"type": "string"}},
                        "acting": {"type": "string"},
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
                    "required": ["beat", "shot", "location", "density", "characters", "acting", "scene", "bubbles"],
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
검수 순서: 의도 → 동일성 → 글자 → 시선·접촉 → 연기 → 가독성. 애매하면 통과시키지 않는다.
- 위에서 아래로 컷이 정확히 4개인가.
- 함께 준 '그려야 할 글자' 목록(제목, 말풍선, 마무리 문구, 하단 안내·출처)이 한 글자도 틀리지 않고 읽히는가. 깨진 글자, 빠진 글자, 엉뚱한 글자, 목록에 없는 읽히는 글자가 있으면 text_errors에 적는다.
- 문장부호(마침표, 쉼표, 말줄임표, 물음표)만 조금 다른 것은 오류가 아니다.
- 배경 소품(서류, 화면, 메모)의 읽을 수 없는 선이나 장식 무늬는 오류가 아니다. 다만 깨진 한글처럼 보이는 글자가 눈에 띄게 크면 오류다.
- 모든 컷의 수달이 인물 기준과 같은 캐릭터인가 (베이지 털, 크림색 주둥이, 남색 카디건, 흰 셔츠, 사원증).
- 조연이 설정과 맞고 주인공과 헷갈리지 않는가. 주인공과 닮은 다른 수달이 있으면 cast_distinct는 false다. 조연이 없으면 true.
- 실존 회사 로고나 실존 인물 얼굴처럼 보이는 것이 없는가.
- acting_notes에는 시선이 엉뚱한 곳을 보거나, 손과 물건이 떠 있거나, 말풍선이 얼굴·손을 가리는 등 연기·가독성 문제를 짧게 적는다.
problems에는 다시 그릴 때 고쳐야 할 점을 짧게 적는다."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "panel_count": {"type": "integer"},
        "text_errors": {"type": "array", "items": {"type": "string"}},
        "character_consistent": {"type": "boolean"},
        "cast_distinct": {"type": "boolean"},
        "has_real_logo_or_person": {"type": "boolean"},
        "acting_notes": {"type": "array", "items": {"type": "string"}},
        "problems": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["panel_count", "text_errors", "character_consistent", "cast_distinct",
                 "has_real_logo_or_person", "acting_notes", "problems"],
    "additionalProperties": False,
}


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


def write_script(model: str, source: dict, bible: dict) -> dict:
    lines = [
        f"뉴스 제목: {source.get('title') or source.get('original_title')}",
        f"원제목: {source.get('original_title', '')}",
        f"요약: {source.get('summary', '')}",
        f"출처: {source.get('source', '')}",
    ]
    if source.get("idea"):
        lines.append(f"편집자의 4컷 아이디어: {source['idea']}")
    script = llm.ask_json(model, script_instructions(bible), "\n".join(lines), script_schema(bible), "webtoon_script", "low")
    if len(script["panels"]) != 4:
        raise RuntimeError(f"대본의 컷 수가 4개가 아닙니다: {len(script['panels'])}개")
    return script


def _cast_in(script: dict, bible: dict) -> list[dict]:
    named = set()
    for panel in script["panels"]:
        named.update(panel["characters"])
        named.update(bubble["speaker"] for bubble in panel["bubbles"])
    return [cast for cast in bible["cast"] if any(cast["name"] in name or name in cast["name"] for name in named)]


def image_prompt(script: dict, source_name: str, feedback: list[str], bible: dict) -> str:
    style, main = bible["style"], bible["main"]
    locations = {loc["id"]: loc for loc in bible["locations"]}
    cast = _cast_in(script, bible)

    panels = []
    for number, panel in enumerate(script["panels"], 1):
        place = locations.get(panel["location"])
        where = f"Location: {place['name']} — {place['layout']} Light: {place['light']}" if place else "Location: as described."
        bubbles = " / ".join(f'{bubble["speaker"]}: "{bubble["text"]}"' for bubble in panel["bubbles"])
        panels.append(
            f"Panel {number} ({SHOT_EN[panel['shot']]}; {DENSITY_EN[panel['density']]}). {where}\n"
            f"  Acting: {panel['acting']} Scene: {panel['scene']}\n"
            f"  Speech bubbles — {bubbles}"
        )
    cast_lines = "\n".join(f"- {c['name']} ({c['species']}): {c['look']}" for c in cast) or "- none"

    prompt = f"""Create a vertical 4-panel Korean webtoon page in exactly the same art style as the second reference image.
Style: {style['profile']} Shapes: {style['shape']} Lines: {style['line']} Color: {style['color']} Light: {style['light']} Background: {style['background']}

Main character: the otter office worker from the first reference image (character sheet). Keep these identical in every panel: {'; '.join(main['fixed'])}.
Allowed changes: {'; '.join(main['allowed_variation'])}.
Never: {'; '.join(main['forbidden'])}.
Supporting characters (draw exactly as described, clearly different species and silhouette from the otter):
{cast_lines}
No other otters. Background extras, if any, are simple silhouettes.

Layout from top to bottom:
- Header on a cream background: large bold rounded Korean title "{script['title']}" with a soft yellow highlighter stripe behind it, and a smaller subtitle "{script['subtitle']}" under it.
- Four stacked horizontal panels with thin dark borders and small gutters. Keep each location's fixed layout consistent between panels.
{chr(10).join(panels)}
- Footer on a cream background: two lines of large bold Korean text, first line "{script['closing_line1']}" in dark navy, second line "{script['closing_line2']}" in dark brown with a yellow highlighter stripe.
- Tiny grey text at the very bottom: left "{NOTE}", right "소재: {source_name}".

Staging rules: show where each character is looking and what their hands touch; hands and objects must connect, nothing floats. Speech bubbles never cover faces, hands or the key prop.
Text rules: render every Korean string exactly as written, character by character. Put dialogue in white rounded speech bubbles with dark outlines whose tails point to the speaker. Documents, papers, phone and laptop screens in the scenes show only simple icons, blocks or lines, never letters. Do not add any other text, English words, signatures, watermarks, brand logos or real people."""
    if feedback:
        prompt += "\n\nThe previous attempt had these problems. Fix them:\n- " + "\n- ".join(feedback)
    return prompt


def review(model: str, image: Path, character: Path, script: dict, source_name: str, bible: dict) -> dict:
    expected = [f"제목: {script['title']}", f"부제: {script['subtitle']}"]
    for number, panel in enumerate(script["panels"], 1):
        expected += [f"{number}컷 말풍선 ({bubble['speaker']}): {bubble['text']}" for bubble in panel["bubbles"]]
    expected += [f"마무리 1: {script['closing_line1']}", f"마무리 2: {script['closing_line2']}",
                 f"하단 왼쪽 작은 글씨: {NOTE}", f"하단 오른쪽 작은 글씨: 소재: {source_name}"]
    cast = _cast_in(script, bible)
    cast_text = "\n".join(f"- {c['name']} ({c['species']}): {c['look']}" for c in cast) or "- 없음"
    content = [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "그려야 할 글자 (이 밖의 읽히는 글자는 없어야 함):\n" + "\n".join(expected)
             + "\n\n등장해야 하는 조연:\n" + cast_text},
            llm.image_part(image),
            llm.image_part(character),
        ],
    }]
    result = llm.ask_json(model, REVIEW_INSTRUCTIONS, content, REVIEW_SCHEMA, "webtoon_review", "low")
    result["passed"] = (
        result["panel_count"] == 4
        and not result["text_errors"]
        and result["character_consistent"]
        and result["cast_distinct"]
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
    bible = load_bible(project)
    status = {
        "ok": False,
        "attempts": 0,
        "topic": source.get("title") or source.get("original_title"),
        "source": source.get("source"),
        "problems": [],
        "made_at": datetime.now(KST).isoformat(timespec="minutes"),
    }

    script = write_script(settings["script_model"], source, bible)
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
            settings["image_model"], image_prompt(script, source.get("source", ""), feedback, bible),
            references, settings["size"], quality,
        )
        draft = drafts / f"{day}-try{attempt}.jpg"
        draft.write_bytes(image)
        verdict = review(settings["review_model"], draft, references[0], script, source.get("source", ""), bible)
        feedback = verdict["text_errors"] + verdict["problems"]
        status["acting_notes"] = verdict["acting_notes"]
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
