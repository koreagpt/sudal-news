"""수달일보 하루치 실행: 뉴스 수집 → 선별·요약 → 웹툰 → 저장 → 페이지 생성.

사용 예
  python daily.py                   # 오늘 뉴스 + 웹툰 만들고 페이지 생성
  python daily.py --basic           # GPT 없이 키워드 선별만 (웹툰 없음)
  python daily.py --webtoon-only    # 오늘 뉴스는 그대로 두고 웹툰만 다시 만들기
  python daily.py --webtoon-only --topic 3   # 오늘 3번 뉴스로 웹툰 다시 만들기
  python daily.py --build-only      # 저장된 데이터로 페이지만 다시 생성
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from newsbot import KST, llm, webtoon
from newsbot.build import build
from newsbot.curate import curate
from newsbot.fetch import balance, collect

PROJECT = Path(__file__).resolve().parent


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def make_news(config: dict, day: str, use_ai: bool) -> dict:
    settings = config["curation"]
    candidates, report = collect(config["feeds"], settings["window_hours"])
    if len(candidates) < settings["count"] * 3:
        print(f"[안내] 후보가 {len(candidates)}개뿐이라 {settings['fallback_window_hours']}시간으로 넓힙니다.")
        candidates, report = collect(config["feeds"], settings["fallback_window_hours"])
    pool = balance(candidates, settings["max_candidates"])
    print(f"후보 {len(candidates)}개 중 {len(pool)}개를 선별 대상으로 사용합니다.")
    for feed_id, info in report.items():
        if info["error"]:
            print(f"  [피드 오류] {feed_id}: {info['error']}")

    _save(PROJECT / "data" / "raw" / f"{day}.json", pool)
    result = curate(pool, settings["count"], settings["model"], use_ai=use_ai, effort=settings.get("reasoning_effort"))
    news = {
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
        "feeds": report,
    }
    _save(PROJECT / "data" / "news" / f"{day}.json", news)
    print(f"[{news['mode']}] {len(news['items'])}건 저장 → data/news/{day}.json")
    for item in news["items"]:
        print(f"  - {item['title']} ({item['source']})")
    return news


def make_webtoon(config: dict, day: str, news: dict, topic: int | None) -> None:
    if not config.get("webtoon", {}).get("enabled"):
        return
    if not llm.has_key():
        print("[안내] OPENAI_API_KEY가 없어 웹툰은 만들지 않습니다.")
        return
    print("오늘의 웹툰을 만듭니다.")
    try:
        status = webtoon.make(PROJECT, config, day, news, topic)
    except Exception as error:  # 웹툰이 실패해도 뉴스 발행은 계속한다
        print(f"[경고] 웹툰 생성 실패: {type(error).__name__}: {error}")
        status = {"ok": False, "problems": [f"{type(error).__name__}: {error}"],
                  "made_at": datetime.now(KST).isoformat(timespec="minutes")}
    news["webtoon_status"] = status
    _save(PROJECT / "data" / "news" / f"{day}.json", news)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="수달일보 하루치 생성")
    parser.add_argument("--date", help="발행일(YYYY-MM-DD). 기본값: 오늘(한국 시간)")
    parser.add_argument("--basic", action="store_true", help="GPT 없이 키워드 선별만 사용 (웹툰 없음)")
    parser.add_argument("--build-only", action="store_true", help="수집 없이 페이지만 다시 생성")
    parser.add_argument("--webtoon-only", action="store_true", help="오늘 뉴스는 두고 웹툰만 다시 만들기")
    parser.add_argument("--topic", type=int, help="웹툰 소재로 쓸 뉴스 번호(1부터)")
    parser.add_argument("--cast-sheet", action="store_true", help="조연 기준 시트를 새로 그리기 (가끔 한 번)")
    args = parser.parse_args(argv)

    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    day = args.date or datetime.now(KST).date().isoformat()
    if args.cast_sheet:
        if not llm.has_key():
            print("OPENAI_API_KEY가 없어 조연 기준 시트를 그릴 수 없습니다.")
            return 1
        webtoon.make_cast_sheet(PROJECT, config)
    elif args.webtoon_only:
        path = PROJECT / "data" / "news" / f"{day}.json"
        if not path.exists():
            print(f"{day} 뉴스가 없어 웹툰을 만들 수 없습니다. 먼저 python daily.py 를 실행하세요.")
            return 1
        make_webtoon(config, day, json.loads(path.read_text(encoding="utf-8")), args.topic)
    elif not args.build_only:
        news = make_news(config, day, use_ai=not args.basic)
        if not args.basic:
            make_webtoon(config, day, news, args.topic)
    out = build(PROJECT, config)
    print(f"페이지 생성 완료 → {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
