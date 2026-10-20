"""수달일보 하루치 실행: 뉴스 수집 → 선별·요약 → 저장 → 페이지 생성.

사용 예
  python daily.py                 # 오늘 뉴스 만들고 페이지 생성
  python daily.py --basic         # Claude 없이 키워드 선별만
  python daily.py --build-only    # 저장된 데이터로 페이지만 다시 생성
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from newsbot import KST
from newsbot.build import build
from newsbot.curate import curate
from newsbot.fetch import balance, collect

PROJECT = Path(__file__).resolve().parent


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def make_news(config: dict, day: str, use_claude: bool) -> dict:
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
    result = curate(pool, settings["count"], settings["model"], use_claude=use_claude)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="수달일보 하루치 생성")
    parser.add_argument("--date", help="발행일(YYYY-MM-DD). 기본값: 오늘(한국 시간)")
    parser.add_argument("--basic", action="store_true", help="Claude 없이 키워드 선별만 사용")
    parser.add_argument("--build-only", action="store_true", help="수집 없이 페이지만 다시 생성")
    args = parser.parse_args(argv)

    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    day = args.date or datetime.now(KST).date().isoformat()
    if not args.build_only:
        make_news(config, day, use_claude=not args.basic)
    out = build(PROJECT, config)
    print(f"페이지 생성 완료 → {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
