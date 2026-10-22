"""오늘 수달일보를 운영자 카카오톡 '나와의 채팅'으로 보낸다 (카카오톡 메시지 API, 나에게 보내기).

운영자는 받은 카드를 길게 눌러 오픈채팅방으로 '전달'만 하면 된다.

토큰 보관
  카카오 리프레시 토큰(약 2개월)은 data/kakao_token.enc 에 암호화해서 저장소에 둔다.
  암호 키는 GitHub 비밀값 KAKAO_TOKEN_KEY 에만 있다. 매일 보낼 때 토큰을 새로 받아 두므로
  하루 한 번이라도 돌면 연결이 끊기지 않는다 (만료 한 달 전부터 카카오가 새 리프레시 토큰을 준다).

환경변수
  KAKAO_REST_KEY       카카오 앱 REST API 키
  KAKAO_TOKEN_KEY      토큰 파일 암호 키 (아무 긴 문자열)
  KAKAO_CLIENT_SECRET  선택. 카카오 로그인 → 보안에서 Client Secret을 켠 경우에만

사용 예
  python kakao_send.py --setup 인증코드   # 처음 연결: 코드로 토큰 받고 시험 메시지 보내기
  python kakao_send.py                    # 오늘 게시글 보내기 (몇 번이든)
  python kakao_send.py --once             # 예약용: 오늘 이미 보냈으면 건너뜀
  python kakao_send.py --dry-run          # 보내지 않고 메시지 내용만 출력
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from newsbot import KST
from newsbot.build import _brand_name, _korean_date, _webtoon_for, share_text

PROJECT = Path(__file__).resolve().parent
TOKEN_FILE = PROJECT / "data" / "kakao_token.enc"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TEXT_LIMIT = 200  # 텍스트 템플릿 최대 글자 수


def _post(url: str, data: dict, token: str | None = None) -> dict:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:  # 카카오 오류 내용(토큰 값은 들어 있지 않음)을 그대로 보여 준다
        raise RuntimeError(f"카카오 응답 {error.code}: {error.read().decode(errors='replace')}") from None


def _mask(*values: str) -> None:
    if os.environ.get("GITHUB_ACTIONS"):  # 실행 기록에 토큰이 찍히지 않게
        for value in values:
            if value:
                print(f"::add-mask::{value}")


def _fernet():
    from cryptography.fernet import Fernet

    key = os.environ.get("KAKAO_TOKEN_KEY")
    if not key:
        raise SystemExit("[안내] KAKAO_TOKEN_KEY 비밀값이 없어요.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def _client() -> dict:
    rest = os.environ.get("KAKAO_REST_KEY", "").strip()
    if not rest:
        raise SystemExit("[안내] KAKAO_REST_KEY 비밀값이 없어요.")
    client = {"client_id": rest}
    if os.environ.get("KAKAO_CLIENT_SECRET"):
        client["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"].strip()
    return client


def _save(tokens: dict, previous: dict | None = None) -> None:
    """새 리프레시 토큰이 왔을 때만 파일을 바꾼다."""
    if not tokens.get("refresh_token"):
        return
    now = datetime.now(KST)
    stored = {
        "refresh_token": tokens["refresh_token"],
        "refresh_expires_at": (now + timedelta(seconds=int(tokens.get("refresh_token_expires_in", 0)))).isoformat(timespec="minutes"),
        "saved_at": now.isoformat(timespec="minutes"),
    }
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_bytes(_fernet().encrypt(json.dumps(stored).encode()))
    print(f"리프레시 토큰 저장 (만료 {stored['refresh_expires_at'][:10]})" + (" — 새로 갱신됨" if previous else ""))


def setup(code: str) -> str:
    """처음 연결: 인증 코드를 토큰으로 바꾼다."""
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    redirect = config["site"]["base_url"].rstrip("/") + "/kakao/"
    tokens = _post(TOKEN_URL, {"grant_type": "authorization_code", "redirect_uri": redirect, "code": code.strip(), **_client()})
    _mask(tokens.get("access_token"), tokens.get("refresh_token"))
    if "talk_message" not in tokens.get("scope", ""):
        print("[경고] '카카오톡 메시지 전송' 동의가 빠졌어요. 연결 페이지에서 다시 연결하며 동의에 체크해 주세요.")
    _save(tokens)
    return tokens["access_token"]


def access_token() -> str | None:
    if not TOKEN_FILE.exists():
        return None
    stored = json.loads(_fernet().decrypt(TOKEN_FILE.read_bytes()))
    _mask(stored["refresh_token"])
    tokens = _post(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": stored["refresh_token"], **_client()})
    _mask(tokens.get("access_token"), tokens.get("refresh_token"))
    _save(tokens, previous=stored)
    left = (datetime.fromisoformat(stored["refresh_expires_at"]) - datetime.now(KST)).days
    if not tokens.get("refresh_token"):
        print(f"리프레시 토큰 남은 기간: {left}일")
    return tokens["access_token"]


def _link(url: str) -> dict:
    return {"web_url": url, "mobile_web_url": url}


def messages(day: str) -> list[dict]:
    """오늘 보낼 메시지: 붙여 넣기용 글(텍스트) + 전달용 카드(썸네일)."""
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    site = config["site"]
    base = site["base_url"].rstrip("/")
    page, archive = f"{base}/d/{day}/", f"{base}/archive/"
    news_path = PROJECT / "data" / "news" / f"{day}.json"
    if not news_path.exists():
        actions = f"https://github.com/{site['repo']}/actions/workflows/daily.yml"
        return [{"object_type": "text", "link": _link(actions), "button_title": "실행 화면 열기",
                 "text": f"🦦 {_korean_date(day, long=False)} 수달일보 발행이 아직 안 됐어요.\nGitHub 실행 화면에서 Run workflow(full)로 다시 실행해 주세요."}]

    news = json.loads(news_path.read_text(encoding="utf-8"))
    webtoons = json.loads((PROJECT / "data" / "webtoons.json").read_text(encoding="utf-8"))
    toon, is_today = _webtoon_for(day, webtoons)
    titles = [item["title"] for item in news.get("items", [])]
    date_text = _korean_date(day, long=False)

    # 1) 텍스트: 오픈채팅방에 올리던 게시글 그대로. 카카오가 길다고 거절하면 200자 안으로 줄인 글로 보낸다
    head = f"🦦 {_brand_name(site)} | {date_text}"
    tail = ["", "👉 4컷 웹툰과 뉴스 요약 보기", page]
    shown = list(titles)
    while True:
        body = [f"{number}. {title}" for number, title in enumerate(shown, 1)]
        if len(shown) < len(titles):
            body.append(f"…외 {len(titles) - len(shown)}건")
        text = "\n".join([head, f"오늘의 AI 뉴스 {len(titles)}건", "", *body, *tail])
        if len(text) <= TEXT_LIMIT or not shown:
            break
        shown.pop()

    # 2) 카드: 제목+설명은 합쳐서 4줄까지 보인다
    toon_title = f"「{toon['title']}」" if (toon and is_today) else ""
    card_title = f"🦦 수달일보 {date_text}" + (f" {toon_title}" if toon_title else "")
    description = f"오늘의 AI 뉴스 {len(titles)}건 · {titles[0]}" + (f" 외 {len(titles) - 1}건" if len(titles) > 1 else "") if titles else ""
    feed = {
        "object_type": "feed",
        "content": {"title": card_title, "description": description, "image_url": f"{base}/og/{day}.jpg",
                    "image_width": 1200, "image_height": 630, "link": _link(page)},
        "buttons": [{"title": "웹툰·뉴스 보기", "link": _link(page)}, {"title": "지난 호 보기", "link": _link(archive)}],
    }
    full = {"object_type": "text", "text": share_text(site, day, news), "link": _link(page), "button_title": "웹툰·뉴스 보기"}
    if len(full["text"]) > TEXT_LIMIT:
        full["_shorter"] = {**full, "text": text}
    # config.json의 kakao.format: card = 썸네일 카드만, text = 게시글만, both = 둘 다
    form = config.get("kakao", {}).get("format", "card")
    return {"card": [feed], "text": [full]}.get(form, [full, feed])


def send(token: str, items: list[dict]) -> None:
    for item in items:
        shorter = item.pop("_shorter", None)
        try:
            result = _post(MEMO_URL, {"template_object": json.dumps(item, ensure_ascii=False)}, token)
        except RuntimeError as error:
            if not shorter:
                raise
            print(f"전체 게시글({len(item['text'])}자)은 카카오가 받지 않아 줄인 글로 보냅니다: {error}")
            result = _post(MEMO_URL, {"template_object": json.dumps(shorter, ensure_ascii=False)}, token)
        else:
            if shorter:
                print(f"전체 게시글 {len(item['text'])}자를 그대로 보냈습니다.")
        if result.get("result_code") != 0:
            raise RuntimeError(f"보내기 실패: {result}")
    print(f"카카오톡 나와의 채팅으로 {len(items)}개 보냄")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="오늘 수달일보를 카카오톡 나와의 채팅으로 보내기")
    parser.add_argument("--date", help="YYYY-MM-DD. 기본값: 오늘(한국 시간)")
    parser.add_argument("--setup", metavar="CODE", help="처음 연결: 연결 페이지에서 받은 인증 코드")
    parser.add_argument("--once", action="store_true", help="예약용: 오늘 이미 보냈으면 건너뛰고, 오늘 호가 없으면 10:15까지 기다림")
    parser.add_argument("--dry-run", action="store_true", help="보내지 않고 메시지 내용만 출력")
    args = parser.parse_args(argv)

    now = datetime.now(KST)
    day = args.date or now.date().isoformat()
    if args.dry_run:
        for item in messages(day):
            print(json.dumps(item, ensure_ascii=False, indent=2))
            if item["object_type"] == "text":
                print(f"(텍스트 {len(item['text'])}자 / 최대 {TEXT_LIMIT}자)")
        return 0

    marker = PROJECT / "data" / "kakaoed" / f"{day}.txt"
    if args.once:
        if marker.exists():
            print(f"{day} 카카오톡은 이미 보냈습니다.")
            return 0
        news_path = PROJECT / "data" / "news" / f"{day}.json"
        if not news_path.exists() and (now.hour, now.minute) < (10, 15):
            print("오늘 호가 아직 없어 다음 예약 시도에서 보냅니다.")
            return 0
        if news_path.exists() and not (json.loads(news_path.read_text(encoding="utf-8")).get("webtoon_status") or {}).get("ok"):
            print("오늘 웹툰을 다시 만드는 중이라, 완성되면 보냅니다.")  # 웹툰까지 한 묶음이 돼야 보낸다
            return 0

    if args.setup:
        token = setup(args.setup)
        intro = {"object_type": "text", "link": _link(json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))["site"]["base_url"]),
                 "text": "🦦 수달일보 카카오톡 연결 완료!\n매일 아침 이 채팅방으로 오늘 게시글이 와요.\n카드를 길게 눌러 오픈채팅방으로 전달하면 돼요."}
        send(token, [intro, *messages(day)])
        return 0

    if not os.environ.get("KAKAO_REST_KEY"):
        print("[안내] 카카오톡 연결 전이라 보내지 않습니다.")
        return 0  # 연결 전에는 실패로 처리하지 않는다
    token = access_token()
    if not token:
        print("[안내] 아직 카카오 연결(인증 코드 등록)을 하지 않아 보내지 않습니다.")
        return 0
    send(token, messages(day))
    if (PROJECT / "data" / "news" / f"{day}.json").exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{now.isoformat(timespec='minutes')}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
