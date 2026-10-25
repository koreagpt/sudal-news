"""AI 사용법 블로그 글 시험판: 공감 4컷 → 글(따라 하기·복사용 질문) → 해결 4컷 → 글(주의할 점·마무리).

일보와 같은 캐릭터·그림체·검수 규칙으로 웹툰 2장을 그리고, 블로그에 옮길 글까지 써서
data/drafts/blog/ 에 blog.html(미리보기), blog.json, part1.jpg, part2.jpg 로 남긴다. 게시는 하지 않는다.

사용 예
  HOST_TEST=mungmung python make_blog_sample.py "회의 메모 정리, 챗GPT한테 맡기는 법"
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from html import escape
from pathlib import Path

from newsbot import KST, llm, webtoon
from newsbot.style import NATURAL_KOREAN

PROJECT = Path(__file__).resolve().parent
OUT = PROJECT / "data" / "drafts" / "blog"

BLOG_RULES = """

이번에는 일보가 아니라 'AI 기초 사용법' 블로그 글이다. 독자는 회사나 일상에서 AI를 아직 잘 못 다루는 어른들이다.
불편하고 막막한 마음을 먼저 알아주고(공감), 이럴 때는 이렇게 하면 된다(해결)를 쉽게 보여 준다.

웹툰은 4컷 두 편이다. 두 편 모두 위의 대본 규칙(4컷, 말풍선 길이, 쉬운 말, 화면 방향, 연기)을 그대로 따른다.
- part1 (공감): 1컷 평범한 업무 장면 → 2컷 막히는 순간 → 3컷 혼자 해 보다 더 꼬임(피식 웃게) → 4컷 조연이 "AI한테 이렇게 물어봐" 하고 알려 줌.
  part1의 title은 블로그 글 제목을 14자 이내로 줄인 것, subtitle은 독자가 공감할 상황 한 줄.
- part2 (해결): 1컷 알려 준 대로 AI에게 물어봄 → 2컷 결과가 나와서 놀람 → 3컷 "여기만 고쳐 줘" 하고 한 번 더 시킴(AI는 대화하듯 다시 시키면 된다) → 4컷 일이 금방 끝나고 여유.
  part2의 title은 '이렇게 물어보면 돼요'처럼 해결을 말하는 14자 이내 제목.
- 말풍선은 짧게. 실제로 입력할 긴 질문 문장은 말풍선에 쓰지 말고 아래 글(prompt)에 쓴다.
- 서비스는 챗GPT·클로드·제미나이 중 주제에 맞는 것 하나만 쓴다. 버튼 위치·메뉴 이름처럼 자주 바뀌는 화면 설명은 쓰지 않는다.

글(블로그 본문)은 웹툰 사이사이에 들어간다. 존댓말, 짧은 문장, 어른도 바로 이해하는 단어.
- blog_title: 검색에 잘 걸리는 쉬운 제목 (30자 이내, 예: '회의 메모 정리, 챗GPT한테 5분 만에 맡기는 법')
- intro: 공감으로 여는 2~3문장
- when: '이럴 때 써요' 한두 문장
- steps: 따라 하기 3~4단계, 단계마다 한 문장
- prompt: 그대로 복사해서 쓰는 질문 한 개 (실제로 바로 쓸 수 있게 구체적으로, [ ] 칸에 자기 내용을 넣게)
- refine: 결과를 다듬을 때 이어서 쓰는 질문 예시 2개
- cautions: 주의할 점 2~3개 (개인정보·회사 기밀 넣지 않기, 결과는 한 번 확인하기 등)
- outro: 마무리 한두 문장 (협회 강의를 억지로 홍보하지 말고 '더 배우고 싶다면' 정도로)
- tags: 블로그 태그 5~8개 (# 없이)
"""


def plan_schema(bible: dict) -> dict:
    part = webtoon.script_schema(bible)
    text_list = {"type": "array", "items": {"type": "string"}}
    props = {
        "blog_title": {"type": "string"}, "intro": {"type": "string"}, "when": {"type": "string"},
        "steps": text_list, "prompt": {"type": "string"}, "refine": text_list, "cautions": text_list,
        "outro": {"type": "string"}, "tags": text_list, "part1": part, "part2": part,
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def render(plan: dict, host: dict) -> str:
    steps = "".join(f"<li>{escape(s)}</li>" for s in plan["steps"])
    refine = "".join(f"<li>“{escape(s)}”</li>" for s in plan["refine"])
    cautions = "".join(f"<li>{escape(s)}</li>" for s in plan["cautions"])
    tags = " ".join(f"#{escape(t)}" for t in plan["tags"])
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(plan['blog_title'])}</title>
<style>
body {{ margin: 0; background: #f4f4f4; font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; color: #222; }}
.post {{ max-width: 720px; margin: 0 auto; background: #fff; padding: 32px 20px 48px; line-height: 1.8; font-size: 16px; }}
.note {{ font-size: 12.5px; color: #888; border: 1px dashed #bbb; padding: 6px 10px; border-radius: 6px; margin-bottom: 18px; }}
h1 {{ font-size: 26px; line-height: 1.4; margin: 0 0 6px; }}
.by {{ color: #888; font-size: 13px; margin-bottom: 24px; }}
h2 {{ font-size: 19px; margin: 32px 0 8px; padding-left: 10px; border-left: 4px solid #2c3553; }}
img {{ width: 100%; border-radius: 8px; margin: 18px 0; display: block; }}
.prompt {{ background: #f7f3e8; border: 1px solid #e3d9bf; border-radius: 8px; padding: 14px 16px; white-space: pre-wrap; font-size: 15px; }}
.tags {{ color: #2c6e49; font-size: 14px; margin-top: 28px; }}
.cta {{ display: inline-block; margin-top: 8px; background: #2c3553; color: #fff; text-decoration: none; padding: 10px 14px; border-radius: 8px; font-weight: 700; }}
</style></head><body><article class="post">
<p class="note">블로그 자동화 시험판 (게시 안 함) · 주인공 {escape(host['name'])} · {datetime.now(KST):%Y-%m-%d}</p>
<h1>{escape(plan['blog_title'])}</h1>
<p class="by">한국GPT협회 AI 정보 블로그</p>
<p>{escape(plan['intro'])}</p>
<img src="part1.jpg" alt="{escape(plan['part1']['alt'])}">
<h2>이럴 때 써요</h2><p>{escape(plan['when'])}</p>
<h2>따라 하기</h2><ol>{steps}</ol>
<h2>그대로 복사해서 쓰는 질문</h2><div class="prompt">{escape(plan['prompt'])}</div>
<img src="part2.jpg" alt="{escape(plan['part2']['alt'])}">
<h2>결과를 다듬고 싶을 때</h2><ul>{refine}</ul>
<h2>주의할 점</h2><ul>{cautions}</ul>
<h2>마무리</h2><p>{escape(plan['outro'])}</p>
<a class="cta" href="https://gptkoreaclass.com/">한국GPT협회 온라인 강의 보러 가기</a>
<p class="tags">{tags}</p>
</article></body></html>"""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    topic = " ".join(argv) or "회의 메모 정리, 챗GPT한테 맡기는 법"
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    settings = config["webtoon"]
    day = datetime.now(KST).date().isoformat()
    bible = webtoon.load_bible(PROJECT, day)
    host = bible["host"]
    OUT.mkdir(parents=True, exist_ok=True)

    print(f"블로그 시험판: 「{topic}」 (주인공 {host['name']})")
    instructions = webtoon.script_instructions(bible) + BLOG_RULES + "\n" + NATURAL_KOREAN
    plan = llm.ask_json(settings["script_model"], instructions, f"오늘의 사용법 주제: {topic}", plan_schema(bible), "blog_plan", "low")
    for name in ("part1", "part2"):
        verdict = webtoon.check_script(settings["review_model"], plan[name])
        print(f"  {name} 대본 이해되는지: {'통과' if verdict['clear'] else '아쉬움 — ' + ' / '.join(verdict['problems'])}")
    (OUT / "blog.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    source = {"title": topic, "source": "한국GPT협회 AI 정보 블로그", "link": ""}
    for name in ("part1", "part2"):
        print(f"  {name} 그리는 중: {plan[name]['title']}")
        for round_no in range(1, 3):  # 그림이 검수에서 떨어지면 같은 대본으로 한 번 더
            status = webtoon.make(PROJECT, config, day, {}, save=False, script=plan[name], source=source)
            # 시안 파일 이름이 날짜 기준이라, 다음 편을 그리기 전에 바로 옮겨 둔다
            if status.get("ok"):
                shutil.copy2(PROJECT / "data" / "drafts" / status["draft"], OUT / f"{name}.jpg")
                break
        else:
            print(f"  [안내] {name} 웹툰이 검수를 통과하지 못했습니다.")
    (OUT / "blog.html").write_text(render(plan, host), encoding="utf-8")
    print(f"블로그 시험판 완성 → {OUT.relative_to(PROJECT)}/blog.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
