"""오늘의 뉴스 하나로 수달 사원 4컷 웹툰을 만든다: 대본 → 작화 → 검수.

컷온 웹툰 제작 스킬(인물 고정값, 짧고 정확한 대사, 가상 상황 표기, 실제 결과물 검수)과
애니메이션 작화·표정·행동·배경 스킬(설정집, 연기 브리프, 컷별 배경 밀도, 검수 순서)을 자동화했다.
설정은 data/bible.json 에 있다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import KST, lettering, llm
from .style import NATURAL_KOREAN

NOTE = "AI 뉴스를 바탕으로 한 가상 상황입니다."
SHOTS = ["롱샷", "미디엄", "클로즈업", "인서트"]
DENSITIES = ["establishing", "context", "contact", "none"]
DENSITY_EN = {
    "establishing": "wide establishing background that clearly introduces the place",
    "context": "background keeps the main structures and recurring props of the place",
    "contact": "minimal background, only the desk, chair or props the character touches",
    "none": "plain soft color background with a simple mood effect, no setting",
}
# 그림 지시문에서 지우는 실존 서비스·회사·언론사 이름 (이름을 보면 그림 모델이 진짜 로고를 그린다)
BRANDS = [
    "ChatGPT", "챗GPT", "챗지피티", "OpenAI", "오픈AI", "GPT", "제미나이", "Gemini", "구글", "Google", "클로드", "Claude",
    "앤트로픽", "Anthropic", "코파일럿", "Copilot", "마이크로소프트", "Microsoft", "애플", "Apple", "아이폰", "iPhone",
    "삼성", "갤럭시", "Galaxy", "네이버", "Naver", "카카오", "Kakao", "라이트룸", "Lightroom", "어도비", "Adobe", "포토샵",
    "메타", "Meta", "인스타그램", "유튜브", "YouTube", "퍼플렉시티", "Perplexity", "노션", "Notion", "슬랙", "Slack",
    "엔비디아", "NVIDIA", "아마존", "Amazon", "그록", "Grok", "딥시크", "DeepSeek", "미드저니", "Midjourney",
    "AI타임스", "TechCrunch", "테크크런치", "The Verge", "더버지", "연합뉴스", "전자신문", "블로터", "지디넷", "ZDNet",
]
_BRAND_RE = re.compile("|".join(re.escape(name) for name in sorted(BRANDS, key=len, reverse=True)), re.IGNORECASE)


def _generic(text: str) -> str:
    """그림 지시문 속 실존 이름을 일반 명사로 바꾼다 (대사·제목은 글꼴로 넣으니 그대로 둔다)."""
    return _BRAND_RE.sub("AI 앱", text)


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
        f"- 말투: {main.get('voice', '')}",
        "[조연 — 이 인물만 쓴다]",
    ]
    lines += [f"- {c['name']} ({c['species']}): {c['look']} 성격: {c['personality']} 역할: {c['role']} 말투: {c.get('voice', '')}"
              for c in bible["cast"]]
    if bible.get("relationships"):
        lines.append("[호칭·높임말 — 반드시 지킨다]")
        lines += [f"- {rule}" for rule in bible["relationships"]]
    if bible.get("series"):
        lines.append(f"[연재 방식] {bible['series']['format']} {bible['series']['variety']}")
    lines.append("[장소 설정집 — id: 배치 / 빛]")
    lines += [f"- {loc['id']} {loc['name']}: {loc['layout']} / {loc['light']}" for loc in bible["locations"]]
    return "\n".join(lines)


def recent_episodes(project: Path, day: str, limit: int = 5) -> str:
    """최근 자동 웹툰 요약 (역할·장소·결말이 반복되지 않게 대본 작가에게 준다)."""
    path = project / "data" / "webtoons.json"
    if not path.exists():
        return ""
    toons = [t for t in json.loads(path.read_text(encoding="utf-8")) if t.get("auto") and t["date"] < day and t.get("script")]
    lines = []
    for toon in toons[-limit:]:
        script = toon["script"]
        places = "·".join(dict.fromkeys(panel.get("location", "?") for panel in script["panels"]))
        talkers = "→".join(bubble["speaker"] for panel in script["panels"] for bubble in panel["bubbles"])
        lines.append(f"- {toon['date']} 「{script['title']}」 장소 {places} / 말한 순서 {talkers} / 마무리 \"{script['closing_line1']} {script['closing_line2']}\"")
    return "\n".join(lines)


def script_instructions(bible: dict) -> str:
    return f"""너는 '한국GPT협회 수달일보'의 웹툰 작가다. 매일 아침 AI 뉴스 하나를 소재로 수달 사원이 주인공인 세로 4컷 웹툰 대본을 쓴다.

{_bible_text(bible)}

이야기 원칙 (회차 완결형, 정보형 웹툰)
- 독자가 따라 할 수 있는 한 가지 문제를 정한다. 4컷 흐름: 1컷 수달이 겪는 구체적인 불편 → 2컷 소식을 접하거나 방법을 시도 → 3컷 결과에서 판단이 필요한 지점을 발견(확인·수정·선택) → 4컷 무엇이 달라졌는지 행동으로 보여 주며 닫는다.
- 수달이 이번 화에서 바뀌는 것(막막함→선택, 시큰둥→관심 등)이 하나 있어야 한다.
- 최근 회차와 역할·장소·결말 방식을 겹치지 않게 한다. 같은 인물이 매번 정답을 알려 주는 구도를 반복하지 않는다.
- 뉴스에 없는 사실(수치, 날짜, 기능, 발언)을 사실처럼 쓰지 않는다. 필요하면 일반적인 상황으로 표현한다.
- 실존 인물의 얼굴, 실제 회사 로고, 실제 제품 화면을 그리지 않는다. 서비스 이름은 대사에 꼭 필요할 때만 쓴다.
- scene·acting(그림 지시)에는 서비스·회사·언론사 이름을 쓰지 않는다. 'AI 채팅 앱', '사진 앱', '뉴스 기사'처럼 일반 이름으로 쓴다.
- 혐오, 비하, 정치적 편향, 공포 조장 없이 따뜻하고 피식 웃게 되는 톤으로 쓴다.
- 협회나 강의 광고 문구는 넣지 않는다.
- 마무리 두 줄은 훈계나 표어가 아니라 이번 화에서 달라진 점을 담은 담백한 한 마디로 쓴다 ("~하자", "~해야 한다" 같은 명령·설교 피하기).

대화 원칙 (자연스러운 대화·감정 대사)
- 모든 대사는 바로 앞의 말이나 행동에 대한 반응이다. 두 사람이 각자 설명을 번갈아 읽는 독백 교환을 쓰지 않는다.
- 인물은 자기가 아는 것만 말한다. 작가가 아는 정보를 인물에게 대신 읽히지 않는다.
- 설정집의 말투와 호칭·높임말을 지킨다. 수달은 대리님·팀장님께 존댓말을 쓴다.
- 감정은 이유와 행동으로 보여 준다. 느낌표·말줄임표를 남발하지 않는다.
- 한 말풍선은 한 번의 말하기 호흡이다. A→B→A처럼 번갈아 말하면 말풍선을 나누고, 같은 사람이 이어서 하는 말은 한 컷에 두 개까지만.

연기 규칙 (표정·행동)
- beat: 그 컷에서 독자가 새로 알게 되는 것 하나.
- acting: 누가 무엇을 보는지(시선), 손이 무엇을 쥐거나 만지는지(접촉), 몸 자세와 표정을 함께 쓴다. 얼굴만으로 감정을 해결하지 않는다.
- 수달은 연기 습관을 지킨다. 감탄·웃음 같은 큰 변화는 3컷이나 4컷 한 번에 몰아 준다.
- 같은 크기의 얼굴 클로즈업을 연달아 쓰지 않는다. 롱샷=공간, 미디엄=행동, 클로즈업=감정, 인서트=단서.
- 말풍선이 있는 컷은 말하는 인물의 얼굴이 보이는 롱샷·미디엄·클로즈업으로 한다. 화면이나 손만 크게 보이는 인서트는 말풍선 둘 곳이 없으니 쓰지 않는다.
- 조연은 설정집 인물만, 필요할 때만 쓴다. 수달과 같은 종의 다른 캐릭터를 만들지 않는다.

배경 규칙
- location은 설정집의 id 중 하나. 설정집에 없는 곳이면 "other".
- density: 1컷은 장소를 알리는 establishing이나 context. 같은 장소가 이어지면 contact나 none으로 줄여 인물과 말풍선이 먼저 읽히게 한다. 장소가 바뀌면 다시 context.
- 설정집의 고정 배치(창 위치, 책상, 화분 등)를 바꾸지 않는다.

글자 규칙 (그림에 그대로 그려지므로 짧고 정확하게)
- title(14자 이내): 처음 보는 사람이 제목만 읽고 '무슨 AI 이야기인지' 바로 알 수 있게 쓴다. 오늘 다루는 AI 기능이나 업무(슬라이드, 회의록, 장보기, 챗봇 기억 등)와 그로 인해 생긴 변화나 상황을 담는다.
  은유·말장난·속뜻만으로 된 제목은 쓰지 않는다. 나쁜 예: '엎기 전에', '설명도 이사 중' (무슨 이야기인지 모름). 좋은 예: '슬라이드, 구성부터 보기', 'AI에게 장보기 맡긴 날', '챗봇 바꿔도 설명은 한 번'.
- subtitle(18자 이내): 제목을 보충해 오늘 웹툰의 상황이나 뉴스 핵심을 한 번 더 짚는다. 제목과 같은 말을 반복하지 않는다.
- panels는 정확히 4개. 컷마다 말풍선 1~2개, 말풍선 하나는 18자 이내, 전체 말풍선 6개 이하. 말풍선 글은 의미 단위로 읽히게 쓴다(조사·어미만 따로 떨어지지 않게).
- speaker는 "수달", "AI", 또는 조연 이름.
- closing_line1, closing_line2는 각각 18자 이내.
- scene은 그림 작가에게 주는 장면 설명(장소, 구도, 소품) 2문장 이내.
- alt는 시각장애인을 위한 4컷 전체 설명. 300자 이내.

{NATURAL_KOREAN}
- 제목과 마무리 두 줄도 이 말투 규칙을 따른다. 광고 문구나 교훈 같은 말 대신, 동료가 피식 웃으며 할 법한 말로 쓴다."""


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


REVIEW_INSTRUCTIONS = """너는 웹툰 검수자다. 첫 번째 이미지는 완성된 4컷 웹툰, 두 번째 이미지는 주인공 수달 사원의 인물 기준 그림이다.
제목, 말풍선, 마무리 문구는 글꼴로 정확히 넣은 것이니 철자는 보지 않는다. 그 대신 아래를 엄격하게 본다. 애매하면 문제로 적는다.
- 위에서 아래로 컷이 정확히 4개인가.
- 그림 속(말풍선·제목·마무리 문구 밖)에 글자, 숫자, 깨진 글씨, 간판 글자, 화면 속 글자, 빈 말풍선이 그려져 있는가. 있으면 art_text에 위치와 함께 적는다. 화면·서류의 단순한 선이나 도형은 괜찮다.
- 모든 컷의 수달이 인물 기준과 같은 캐릭터인가. 같은 인물인지는 종·털 색(베이지)·크림색 주둥이·얼굴 생김새·체형으로 판단한다. 옷은 장소에 따라 달라도 된다: 사무실에서는 남색 카디건·흰 셔츠·사원증, 집이나 출퇴근 길에서는 사원증이 없거나 남색 계열 편한 옷이어도 같은 인물이다. 같은 장소의 연속 컷 안에서 옷이 바뀌는 것만 문제로 본다. character_consistent가 false면 character_notes에 컷 번호와 무엇이 다른지 구체적으로 적는다.
- 조연이 누구인지 바로 알아볼 수 있고 주인공과 헷갈리지 않는가. cast_distinct가 false인 경우는 이것뿐이다: 조연의 종(동물)·얼굴 무늬·안경·옷 색이 기준 시트와 달라 다른 인물로 보일 때, 또는 주인공과 닮은 다른 수달이 있을 때. 사원증·꼬리·바지처럼 구도상 가려지거나 작게 생략된 부분, 체격의 작은 차이는 false 사유가 아니다(필요하면 cast_notes에만 적는다). 조연이 없으면 true.
- 대본에 없는 배경 인물·동물(엑스트라)이 보이면 extras에 컷 번호와 함께 적는다. 엑스트라만으로 cast_distinct를 false로 하지 않는다.
- 실존 회사 로고나 실존 인물 얼굴처럼 보이는 것이 없는가.
- bubble_issues: 말풍선이 얼굴·눈·손·중요한 소품을 가리는지, 꼬리가 엉뚱한 인물을 가리키는지, 읽는 순서가 헷갈리는지. 컷 번호와 함께 적는다.
- acting_notes: 시선·접촉·연기에서 아쉬운 점."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "panel_count": {"type": "integer"},
        "art_text": {"type": "array", "items": {"type": "string"}},
        "character_consistent": {"type": "boolean"},
        "character_notes": {"type": "array", "items": {"type": "string"}},
        "cast_distinct": {"type": "boolean"},
        "cast_notes": {"type": "array", "items": {"type": "string"}},
        "extras": {"type": "array", "items": {"type": "string"}},
        "has_real_logo_or_person": {"type": "boolean"},
        "bubble_issues": {"type": "array", "items": {"type": "string"}},
        "acting_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["panel_count", "art_text", "character_consistent", "character_notes", "cast_distinct", "cast_notes", "extras",
                 "has_real_logo_or_person", "bubble_issues", "acting_notes"],
    "additionalProperties": False,
}

REGION_INSTRUCTIONS = """너는 웹툰 식자 담당의 보조다. 글자 없이 그려진 컷 이미지마다 인물 위치를 표시한다.
- 좌표는 그 컷 이미지 안의 비율(왼쪽 위 0,0 ~ 오른쪽 아래 1,1)이다.
- characters: 컷에 보이는 대본 인물마다 name(대본에 적힌 이름 그대로), 머리 상자(head_x0~head_y1, 귀까지 포함),
  몸 전체 상자(body_x0~body_y1), 입 위치(mouth_x, mouth_y), 얼굴(눈·코·입)이 보이는지 face_visible. 뒷모습이면 false이고 입 위치는 머리 쪽 가장자리로 한다.
  화자가 'AI'면 그 화면이나 휴대전화를 머리 상자로, 화면 가운데를 입으로 한다.
- keep_clear: 말풍선이 가리면 안 되는 것(물건을 쥔 손, 가리키는 손끝, 이야기에 중요한 화면·서류)의 상자.
- feedback이 있으면 지난번 말풍선이 가린 부분을 keep_clear에 꼭 넣는다."""

BOX = {"type": "number"}
REGION_SCHEMA = {
    "type": "object",
    "properties": {
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "characters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "head_x0": BOX, "head_y0": BOX, "head_x1": BOX, "head_y1": BOX,
                                "body_x0": BOX, "body_y0": BOX, "body_x1": BOX, "body_y1": BOX,
                                "mouth_x": BOX, "mouth_y": BOX,
                                "face_visible": {"type": "boolean"},
                            },
                            "required": ["name", "head_x0", "head_y0", "head_x1", "head_y1",
                                         "body_x0", "body_y0", "body_x1", "body_y1", "mouth_x", "mouth_y", "face_visible"],
                            "additionalProperties": False,
                        },
                    },
                    "keep_clear": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"x0": BOX, "y0": BOX, "x1": BOX, "y1": BOX},
                            "required": ["x0", "y0", "x1", "y1"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["characters", "keep_clear"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["panels"],
    "additionalProperties": False,
}
FACE_LIMIT = 0.12  # 말풍선이 얼굴을 이보다 많이 가려야만 둘 수 있으면 그림을 다시 그린다


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


def write_script(model: str, source: dict, bible: dict, recent: str = "") -> dict:
    lines = [
        f"뉴스 제목: {source.get('title') or source.get('original_title')}",
        f"원제목: {source.get('original_title', '')}",
        f"요약: {source.get('summary', '')}",
        f"출처: {source.get('source', '')}",
    ]
    if source.get("idea"):
        lines.append(f"편집자의 4컷 아이디어: {source['idea']}")
    if recent:
        lines.append("최근 회차 (역할·장소·결말을 겹치지 않게):\n" + recent)
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


def image_prompt(script: dict, feedback: list[str], bible: dict) -> str:
    """글자 없는 4컷 그림만 요청한다. 제목·말풍선·마무리 문구는 나중에 글꼴로 넣는다."""
    style, main = bible["style"], bible["main"]
    locations = {loc["id"]: loc for loc in bible["locations"]}
    cast = _cast_in(script, bible)

    panels = []
    for number, panel in enumerate(script["panels"], 1):
        place = locations.get(panel["location"])
        where = f"Location: {place['name']} — {place['layout']} Light: {place['light']}" if place else "Location: as described."
        speakers = ", ".join(sorted({bubble["speaker"] for bubble in panel["bubbles"]}))
        panels.append(
            f"Panel {number} ({SHOT_EN[panel['shot']]}; {DENSITY_EN[panel['density']]}). {where}\n"
            f"  Acting: {_generic(panel['acting'])} Scene: {_generic(panel['scene'])}\n"
            f"  Bubble space: leave a clearly empty background area (wall, window or ceiling, about 35% of the panel width "
            f"and 40% of its height) right above or beside {speakers}'s head for speech bubbles; no faces or hands there."
        )
    cast_lines = "\n".join(f"- {c['name']} ({c['species']}): {c['look']}" for c in cast) or "- none"

    prompt = f"""Draw ONLY the artwork of a vertical 4-panel webtoon, with absolutely no text.
Reference images: the first is the otter main character sheet, the second is the supporting cast model sheet. Match their character designs and soft drawing style exactly, and paint full warm background scenes.
Style: {style['profile']} Shapes: {style['shape']} Lines: {style['line']} Color: {style['color']} Light: {style['light']} Background: {style['background']}

Main character (otter): keep identical in every panel: {'; '.join(main['fixed'])}.
Allowed changes: {'; '.join(main['allowed_variation'])}.
Never: {'; '.join(main['forbidden'])}.
Supporting characters (exactly as in the cast sheet, clearly different species and silhouette from the otter):
{cast_lines}
No other characters at all: no background coworkers, extras or crowds, and no other animals. The office is quiet apart from the named characters.

Page layout: four panels stacked from top to bottom, each a full-width rectangle with a thin dark border and small side margins. Separate the panels with plain cream gutters about 24 pixels tall. Small plain cream margin above the first panel and below the last panel. Keep each location's fixed layout consistent between panels.
{chr(10).join(panels)}

No text anywhere: no speech bubbles, no captions, no title, no letters, no numbers, no signs, no logos, no watermarks. Phone, laptop and monitor screens and papers show only simple icons, blocks or lines; app icons are plain generic shapes (a speech bubble, a lock, a star), never any real app logo or company wordmark. Show where each character looks and what their hands touch; hands and objects connect, nothing floats."""
    if feedback:
        prompt += "\n\nThe previous attempt had these problems. Fix them:\n- " + "\n- ".join(feedback)
    return prompt


def art_image_width(art: Path) -> int:
    from PIL import Image

    with Image.open(art) as image:
        return image.width


def detect_regions(model: str, art: Path, panels: list[tuple[int, int]], script: dict, feedback: list[str]) -> list[dict]:
    """컷마다 인물의 머리·몸·입 위치와 가리면 안 되는 곳을 표시받는다 (픽셀 좌표로 돌려줌)."""
    from PIL import Image

    image = Image.open(art).convert("RGB")
    width = image.width
    parts, crops = [], []
    for number, ((top, bottom), panel) in enumerate(zip(panels, script["panels"]), 1):
        crop_path = art.with_name(f"{art.stem}-panel{number}.jpg")
        image.crop((0, top, width, bottom)).save(crop_path, quality=85)
        crops.append(crop_path)
        names = ", ".join(dict.fromkeys(panel["characters"] + [b["speaker"] for b in panel["bubbles"]]))
        parts.append({"type": "input_text", "text": f"{number}컷 — 등장·말하는 인물: {names}"})
        parts.append(llm.image_part(crop_path))
    if feedback:
        parts.append({"type": "input_text", "text": "feedback (지난 말풍선 배치의 문제):\n- " + "\n- ".join(feedback)})
    data = llm.ask_json(model, REGION_INSTRUCTIONS, [{"role": "user", "content": parts}], REGION_SCHEMA, "panel_regions", "low")
    for crop_path in crops:
        crop_path.unlink(missing_ok=True)

    regions = []
    for (top, bottom), found in zip(panels, data["panels"] + [{"characters": [], "keep_clear": []}] * 4):
        h = bottom - top
        clamp = lambda value: min(max(float(value), 0.0), 1.0)  # noqa: E731
        heads = [{
            "name": c["name"],
            "box": (clamp(c["head_x0"]) * width, clamp(c["head_y0"]) * h, clamp(c["head_x1"]) * width, clamp(c["head_y1"]) * h),
            "body": (clamp(c["body_x0"]) * width, clamp(c["body_y0"]) * h, clamp(c["body_x1"]) * width, clamp(c["body_y1"]) * h),
            "mouth": (clamp(c["mouth_x"]) * width, clamp(c["mouth_y"]) * h),
            "face_visible": bool(c.get("face_visible", True)),
        } for c in found["characters"]]
        keep = [(clamp(k["x0"]) * width, clamp(k["y0"]) * h, clamp(k["x1"]) * width, clamp(k["y1"]) * h) for k in found["keep_clear"]]
        regions.append({"heads": heads, "keep_clear": keep})
    return regions


def layout_bubbles(width: int, panels: list[tuple[int, int]], script: dict, regions: list[dict],
                   lenient: bool = False) -> tuple[list, list[str]]:
    """표시된 위치로 말풍선 자리를 계산하고, 얼굴·중요한 소품을 가릴 수밖에 없는 컷을 알려 준다.

    lenient(마지막 시도)면 얼굴을 크게 가리는 경우만 문제로 본다 — 웹툰을 통째로 버리지 않기 위해.
    """
    layout, crowded = [], []
    for number, ((top, bottom), panel, region) in enumerate(zip(panels, script["panels"], regions), 1):
        bubbles = [(b["text"], b["speaker"]) for b in panel["bubbles"]]
        placed = lettering.place_bubbles(width, bottom - top, bubbles, region["heads"], region["keep_clear"])
        layout.append(placed)
        for bubble, spec in zip(panel["bubbles"], placed):
            if lenient:
                bad = spec["face_overlap"] > FACE_LIMIT * 2
            else:
                bad = spec["face_overlap"] > FACE_LIMIT or spec.get("closer_to_other") or spec.get("clear_overlap", 0) > 0.45
            if bad:
                crowded.append(f"Panel {number}: leave a clearly empty background area (about 35% of the panel width) "
                               f"above or beside {bubble['speaker']}'s head for a speech bubble; keep other heads away from it.")
    return layout, crowded


def review(model: str, image: Path, character: Path, script: dict, bible: dict, cast_sheet: Path | None = None) -> dict:
    cast = _cast_in(script, bible)
    cast_text = "\n".join(f"- {c['name']} ({c['species']}): {c['look']}" for c in cast) or "- 없음"
    speakers = []
    for number, panel in enumerate(script["panels"], 1):
        speakers += [f"{number}컷: {bubble['speaker']} — {bubble['text']}" for bubble in panel["bubbles"]]
    content = [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "말풍선과 화자:\n" + "\n".join(speakers) + "\n\n등장해야 하는 조연:\n" + cast_text},
            llm.image_part(image),
            llm.image_part(character),
        ],
    }]
    if cast and cast_sheet and cast_sheet.exists():  # 조연이 나오는 날만 세 번째로 조연 기준 시트를 붙인다
        content[0]["content"].append({"type": "input_text", "text": "세 번째 이미지는 조연 기준 시트다. 조연이 이 그림과 같은지 확인한다."})
        content[0]["content"].append(llm.image_part(cast_sheet))
    result = llm.ask_json(model, REVIEW_INSTRUCTIONS, content, REVIEW_SCHEMA, "webtoon_review", "low")
    result["art_ok"] = (
        result["panel_count"] == 4
        and not result["art_text"]
        and result["character_consistent"]
        and result["cast_distinct"]
        and not result["has_real_logo_or_person"]
    )
    return result


def make_cast_sheet(project: Path, config: dict) -> Path:
    """조연 기준 시트를 한 번 그려 data/reference/cast-sheet.jpg 로 저장한다 (매일 웹툰의 참고 이미지용)."""
    settings, bible = config["webtoon"], load_bible(project)
    style, main = bible["style"], bible["main"]
    cast = "\n".join(
        f"- {c['species']} ({c['name']}): {c['look']} Personality: {c['personality']}" for c in bible["cast"]
    )
    prompt = f"""Create a character model sheet on a plain cream background, in exactly the same art style as the second reference image.
Style: {style['profile']} Shapes: {style['shape']} Lines: {style['line']} Color: {style['color']}

Top row: a height line-up of three full-body characters standing side by side, front view, neutral pose:
1. The otter office worker from the first reference image, unchanged ({'; '.join(main['fixed'])}).
2 and 3. These supporting office workers, clearly different species and silhouettes from the otter:
{cast}

Bottom row: for each supporting character only, a side view full body plus three head close-ups (neutral, excited, thoughtful), lined up under that character.

Keep every character's colors, clothes, glasses and proportions identical everywhere on the sheet. No text, no labels, no names, no logos, no background scenery."""
    references = [project / settings["references"][0], project / settings["style_reference"]]
    image = llm.draw(settings["image_model"], prompt, references, "1536x1024", "high")
    target = project / "data" / "reference" / "cast-sheet.jpg"
    target.write_bytes(image)
    print(f"조연 기준 시트 저장 → {target.relative_to(project)}")
    return target


def _og_crop(path: Path) -> list[int]:
    """카톡 썸네일에 쓸 윗부분(제목과 1~2컷) 영역."""
    from PIL import Image

    with Image.open(path) as image:
        width = image.width
    left, right = round(width * 0.2), round(width * 0.94)
    return [left, 0, right, round((right - left) * 570 / 520)]


def make(project: Path, config: dict, day: str, news: dict, topic: int | None = None, save: bool = True) -> dict:
    """웹툰을 만들어 data/webtoons에 저장하고 결과(성공 여부·시도·문제)를 돌려준다.

    1) 대본 → 2) 글자 없는 4컷 작화 → 3) 컷 찾기 → 4) 말풍선 자리 정하기 → 5) 글꼴로 식자 → 6) 검수.
    그림에 문제가 있으면 다시 그리고, 말풍선 위치만 문제면 그림은 두고 자리만 다시 정한다.
    """
    from PIL import Image

    settings = config["webtoon"]
    source = pick_topic(news, topic)
    references = [project / path for path in settings["references"]]
    bible = load_bible(project)
    cast_sheet = project / bible["cast_sheet"] if bible.get("cast_sheet") else None
    source_name = source.get("source", "")
    status = {
        "ok": False,
        "attempts": 0,
        "topic": source.get("title") or source.get("original_title"),
        "source": source_name,
        "problems": [],
        "made_at": datetime.now(KST).isoformat(timespec="minutes"),
    }

    script = write_script(settings["script_model"], source, bible, recent_episodes(project, day))
    status["title"] = script["title"]
    status["script"] = script  # 검수에서 떨어져도 대본은 남겨 둔다
    drafts = project / "data" / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    feedback: list[str] = []
    page = None
    for attempt in range(1, settings["max_attempts"] + 1):
        status["attempts"] = attempt
        quality = settings["quality"] if attempt == 1 else settings["retry_quality"]
        print(f"  웹툰 작화 {attempt}차 시도 (화질 {quality}, 글자 없이)")
        art = drafts / f"{day}-try{attempt}-art.jpg"
        art.write_bytes(llm.draw(settings["image_model"], image_prompt(script, feedback, bible), references, settings["size"], quality))
        with Image.open(art) as art_image:
            panels = lettering.find_panels(art_image)
        if len(panels) != 4:
            feedback = [f"Panels must be four separate rectangles divided by clearly visible plain cream gutters (found {len(panels)})."]
            status["problems"] = feedback
            print(f"  컷 4개를 찾지 못함 ({len(panels)}개) → 다시 그림")
            continue

        lettered = lettering.merge_bubbles(script)  # 같은 사람이 연달아 하는 말은 한 말풍선에
        bubble_feedback: list[str] = []
        crowded: list[str] = []
        for layout_try in range(1, 3):  # 그림은 그대로 두고 말풍선 자리만 최대 2번 계산
            regions = detect_regions(settings["review_model"], art, panels, lettered, bubble_feedback)
            layout, crowded = layout_bubbles(art_image_width(art), panels, lettered, regions,
                                             lenient=attempt == settings["max_attempts"])
            if crowded:
                break
            page = drafts / f"{day}-try{attempt}.jpg"
            lettering.compose(art, page, lettered, layout, panels, NOTE, source_name)
            verdict = review(settings["review_model"], page, references[0], script, bible, cast_sheet)
            status["acting_notes"] = verdict["acting_notes"] + [f"엑스트라: {extra}" for extra in verdict["extras"]]
            bubble_feedback = verdict["bubble_issues"]
            if not verdict["art_ok"] or not bubble_feedback:
                break
            print(f"  말풍선 자리 다시 계산 {layout_try}회차: {bubble_feedback}")
        if crowded:  # 말풍선 둘 곳이 없는 그림 → 자리를 남기라고 다시 그린다
            feedback = crowded
            status["problems"] = crowded
            print(f"  말풍선 둘 빈 곳이 없음 → 다시 그림: {crowded}")
            continue
        status["bubble_issues"] = bubble_feedback
        if verdict["art_ok"]:
            status["problems"] = bubble_feedback
            break
        feedback = verdict["art_text"] + ([] if verdict["character_consistent"] else
               ["The otter must match the character sheet: " + ("; ".join(verdict["character_notes"]) or "same face, fur and proportions in every panel")]) \
            + ([] if verdict["cast_distinct"] else ["Supporting characters must match the cast sheet: " + "; ".join(verdict["cast_notes"])]) \
            + ([f"Remove background extras: {'; '.join(verdict['extras'])}"] if verdict["extras"] else []) \
            + (["Remove anything that looks like a real logo or real person."] if verdict["has_real_logo_or_person"] else [])
        status["problems"] = feedback
        print(f"  검수 미통과: {feedback}")
    else:
        print("  [안내] 검수를 통과한 웹툰이 없어 어제 웹툰을 유지합니다. 시도한 그림은 data/drafts/에 있습니다.")
        return status

    if not save:  # 시험 실행: 결과는 data/drafts/에만 남긴다
        status.update(ok=True, image=None, draft=page.name)
        print(f"  시험 실행 완료 → data/drafts/{page.name} (게시하지 않음)")
        return status

    path = project / "data" / "webtoons.json"
    webtoons = json.loads(path.read_text(encoding="utf-8"))
    for old in [toon for toon in webtoons if toon["date"] == day and toon.get("auto")]:
        (project / "data" / "webtoons" / old["image"]).unlink(missing_ok=True)  # 같은 날 다시 만들면 이전 그림 교체
    webtoons = [toon for toon in webtoons if not (toon["date"] == day and toon.get("auto"))]

    stamp = datetime.now(KST).strftime("%H%M%S")
    filename = f"{day}-{stamp}.jpg"
    target = project / "data" / "webtoons" / filename
    target.write_bytes(page.read_bytes())
    webtoons.append({
        "id": f"{day}-{stamp}",
        "date": day,
        "title": script["title"],
        "subtitle": script["subtitle"],
        "image": filename,
        "alt": script["alt"],
        "message": f"{script['closing_line1']} {script['closing_line2']}",
        "note": NOTE,
        "source_name": source_name,
        "source_url": source.get("link", ""),
        "og_crop": _og_crop(target),
        "auto": True,
        "lettering": "font",
        "script": script,
    })
    path.write_text(json.dumps(webtoons, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status.update(ok=True, image=filename)
    print(f"  웹툰 완성 → data/webtoons/{filename} ({script['title']})")
    return status
