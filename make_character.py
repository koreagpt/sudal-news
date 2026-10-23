"""새 당번 사원의 기준 그림(캐릭터 시트) 시안을 그린다.

data/characters/candidates.json 의 시안마다 수달 사원 기준 그림과 같은 구성(전신 1 + 얼굴 3)으로 그려
data/drafts/char-<id>.jpg 에 저장한다 (GitHub 실행에서는 webtoon-drafts 결과물로 받아 볼 수 있다).

사용 예
  python make_character.py            # 모든 시안
  python make_character.py cat-b      # 한 시안만
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from newsbot import llm
from newsbot.webtoon import load_bible

PROJECT = Path(__file__).resolve().parent


def prompt_for(candidate: dict, style: dict) -> str:
    return f"""Create a character model sheet on a plain cream background, in exactly the same layout and art style as the first reference image:
one large full-body front view standing on the left, and three head-and-shoulders close-ups on the right (two on top, one below).
But draw a NEW character instead of the otter: {candidate['look']}
Same proportions and drawing style as the otter (an anthropomorphic animal office worker, about 4 to 5 heads tall), clearly a {candidate['species']}, not an otter.
Personality shown in pose and face: {candidate['attitude']}.
Full body: standing, arms crossed, holding nothing. Close-ups: 1) neutral cool unimpressed face, 2) annoyed face frowning at a smartphone held in its paws, 3) a rare small satisfied smile with eyes closed.
Style: {style['profile']} Shapes: {style['shape']} Lines: {style['line']} Color: {style['color']}
Keep the colors, clothes and markings identical in all four drawings. No text, no labels, no names, no logos, no background scenery."""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    settings, style = config["webtoon"], load_bible(PROJECT)["style"]
    candidates = json.loads((PROJECT / "data" / "characters" / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    chosen = [c for c in candidates if not argv or c["id"] in argv]
    if not llm.has_key():
        print("OPENAI_API_KEY가 없어 그릴 수 없습니다.")
        return 1
    references = [PROJECT / settings["references"][0], PROJECT / settings["style_reference"]]
    drafts = PROJECT / "data" / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    failed = 0
    for candidate in chosen:
        print(f"그리는 중: {candidate['label']}")
        try:
            image = llm.draw(settings["image_model"], prompt_for(candidate, style), references, "1536x1024", "high")
        except Exception as error:  # 한 시안이 실패해도 나머지는 계속
            print(f"  [실패] {type(error).__name__}: {error}")
            failed += 1
            continue
        target = drafts / f"char-{candidate['id']}.jpg"
        target.write_bytes(image)
        print(f"  저장 → {target.relative_to(PROJECT)}")
    return 1 if failed == len(chosen) else 0


if __name__ == "__main__":
    sys.exit(main())
