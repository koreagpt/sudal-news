"""한국GPT협회 일보(달몽·냐옹·뭉뭉 당번) 하루치 실행: 뉴스 수집 → 선별·요약 → 웹툰 → 저장 → 페이지 생성.

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

from newsbot import KST, ads, hosts, llm, webtoon
from newsbot.build import build
from newsbot.curate import curate
from newsbot.fetch import balance, collect

PROJECT = Path(__file__).resolve().parent
ROUNDS_PER_RUN = 3  # 한 번 실행에서 웹툰이 검수에 떨어지면 바로 다시 만드는 횟수 (그래도 안 되면 다음 예약 발행이 이어서)


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
    result = curate(pool, settings["count"], settings["model"], use_ai=use_ai, effort=settings.get("reasoning_effort"),
                    host=hosts.host_for(day, PROJECT))
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


def make_webtoon(config: dict, day: str, news: dict, topic: int | None, save: bool = True) -> None:
    if not config.get("webtoon", {}).get("enabled"):
        return
    if not llm.has_key():
        print("[안내] OPENAI_API_KEY가 없어 웹툰은 만들지 않습니다.")
        return
    for _ in range(ROUNDS_PER_RUN if save else 1):
        previous = news.get("webtoon_status")
        round_no = (previous.get("round", 1) + 1) if previous else 1
        print(f"오늘의 웹툰을 만듭니다 ({round_no}번째).")
        try:
            status = webtoon.make(PROJECT, config, day, news, topic, save)
        except Exception as error:  # 웹툰이 실패해도 뉴스는 저장하고, 웹툰은 다시 만든다
            print(f"[경고] 웹툰 생성 실패: {type(error).__name__}: {error}")
            status = {"ok": False, "problems": [f"{type(error).__name__}: {error}"],
                      "made_at": datetime.now(KST).isoformat(timespec="minutes")}
        if not save:
            print(json.dumps({k: v for k, v in status.items() if k != "script"}, ensure_ascii=False, indent=2))
            return
        news["webtoon_status"] = {**status, "round": round_no}
        _save(PROJECT / "data" / "news" / f"{day}.json", news)
        if status.get("ok"):
            return
        print("  웹툰이 검수를 통과하지 못해 바로 다시 만듭니다.")
    print("[안내] 이번 실행에서는 웹툰을 완성하지 못했습니다. 다음 예약 발행이 이어서 다시 만듭니다.")


def make_ad(config: dict, day: str, news: dict) -> None:
    """뉴스 사이에 끼울 협회 강의 카드 (매일 다른 강의)."""
    ad = ads.make(PROJECT, config, day, news, (news.get("webtoon_status") or {}).get("title", ""))
    if not ad:
        return
    news["ad"] = ad
    _save(PROJECT / "data" / "news" / f"{day}.json", news)
    print(f"강의 카드: {ad['title']} [{ad['style']}] {ad['hook']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="한국GPT협회 일보 하루치 생성")
    parser.add_argument("--date", help="발행일(YYYY-MM-DD). 기본값: 오늘(한국 시간)")
    parser.add_argument("--basic", action="store_true", help="GPT 없이 키워드 선별만 사용 (웹툰 없음)")
    parser.add_argument("--build-only", action="store_true", help="수집 없이 페이지만 다시 생성")
    parser.add_argument("--webtoon-only", action="store_true", help="오늘 뉴스는 두고 웹툰만 다시 만들기")
    parser.add_argument("--topic", type=int, help="웹툰 소재로 쓸 뉴스 번호(1부터)")
    parser.add_argument("--no-save", action="store_true", help="웹툰 시험 실행: 게시하지 않고 data/drafts/에만 남김")
    parser.add_argument("--ad-only", action="store_true", help="오늘 뉴스는 두고 강의 카드만 다시 고르기")
    parser.add_argument("--cast-sheet", action="store_true", help="조연 기준 시트를 새로 그리기 (가끔 한 번)")
    parser.add_argument("--if-missing", action="store_true", help="오늘 호가 이미 있으면 새로 만들지 않고 페이지만 생성 (예약 재시도용)")
    args = parser.parse_args(argv)

    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    day = args.date or datetime.now(KST).date().isoformat()
    if args.if_missing and (PROJECT / "data" / "news" / f"{day}.json").exists():
        status = json.loads((PROJECT / "data" / "news" / f"{day}.json").read_text(encoding="utf-8")).get("webtoon_status") or {}
        if not status.get("ok") and config.get("webtoon", {}).get("enabled") and llm.has_key():
            print(f"{day} 호는 있지만 웹툰이 아직 없어 웹툰만 다시 만듭니다.")
            args.webtoon_only = True
        else:
            print(f"{day} 호는 이미 발행됐습니다. 새로 만들지 않고 페이지만 생성합니다.")
            args.build_only = True
    if args.cast_sheet:
        if not llm.has_key():
            print("OPENAI_API_KEY가 없어 조연 기준 시트를 그릴 수 없습니다.")
            return 1
        webtoon.make_cast_sheet(PROJECT, config)
    elif args.ad_only:
        path = PROJECT / "data" / "news" / f"{day}.json"
        if not path.exists():
            print(f"{day} 뉴스가 없어 강의 카드를 만들 수 없습니다.")
            return 1
        make_ad(config, day, json.loads(path.read_text(encoding="utf-8")))
    elif args.webtoon_only:
        path = PROJECT / "data" / "news" / f"{day}.json"
        if not path.exists():
            print(f"{day} 뉴스가 없어 웹툰을 만들 수 없습니다. 먼저 python daily.py 를 실행하세요.")
            return 1
        make_webtoon(config, day, json.loads(path.read_text(encoding="utf-8")), args.topic, save=not args.no_save)
    elif not args.build_only:
        news = make_news(config, day, use_ai=not args.basic)
        if not args.basic:
            make_webtoon(config, day, news, args.topic)
        make_ad(config, day, news)
    out = build(PROJECT, config)
    print(f"페이지 생성 완료 → {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
