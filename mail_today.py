"""오늘 수달일보 게시글(날짜 주소 포함)을 운영자 메일로 보낸다. 표준 라이브러리만 사용.

환경변수
  MAIL_USERNAME  보내는 메일 계정 (예: Gmail 주소)
  MAIL_PASSWORD  그 계정의 앱 비밀번호
  MAIL_TO        받는 주소 (쉼표로 여러 개 가능)
  MAIL_SERVER    선택. 기본 smtp.gmail.com (465 포트, SSL)

사용 예
  python mail_today.py             # 오늘 게시글 메일 보내기
  python mail_today.py --dry-run   # 보내지 않고 내용만 출력
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path

from newsbot import KST
from newsbot.build import _korean_date, _webtoon_for, share_text

PROJECT = Path(__file__).resolve().parent


def compose(day: str) -> EmailMessage:
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    site = config["site"]
    base = site["base_url"].rstrip("/")
    share_url, page_url = f"{base}/share/", f"{base}/d/{day}/"
    news_path = PROJECT / "data" / "news" / f"{day}.json"

    message = EmailMessage()
    if not news_path.exists():  # 아침 발행이 실패했거나 늦어진 날
        message["Subject"] = f"[수달일보] {_korean_date(day, long=False)} 발행이 아직 안 됐어요"
        actions = f"https://github.com/{site['repo']}/actions/workflows/daily.yml"
        message.set_content(f"오늘 아침 자동 발행 기록이 없어요.\n실행 화면에서 확인하거나 Run workflow(full)로 다시 실행해 주세요.\n{actions}")
        return message

    news = json.loads(news_path.read_text(encoding="utf-8"))
    webtoons = json.loads((PROJECT / "data" / "webtoons.json").read_text(encoding="utf-8"))
    toon, is_today = _webtoon_for(day, webtoons)
    text = share_text(site, day, news)
    status = news.get("webtoon_status") or {}
    if is_today and toon:
        toon_line = f"오늘 웹툰: 「{toon['title']}」"
    else:
        toon_line = "오늘 웹툰은 만들지 못해서 이전 웹툰이 나가요. 운영자 화면에서 다시 만들 수 있어요."
        if status.get("problems"):
            toon_line += f" (이유: {' / '.join(status['problems'][:2])})"

    message["Subject"] = f"🦦 수달일보 {_korean_date(day, long=False)} 게시글 준비 완료"
    message.set_content(
        f"{toon_line}\n\n아래 글을 그대로 복사해서 오픈채팅방에 붙여 넣으세요.\n"
        f"----------------------------------------\n{text}\n----------------------------------------\n\n"
        f"운영자 화면(웹툰 확인·복사 버튼): {share_url}\n"
    )
    thumbnail = f"{base}/og/{day}.jpg"
    message.add_alternative(f"""<!doctype html>
<html lang="ko"><body style="margin:0;padding:24px 12px;background:#fbf6ec;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#2a2420;">
<div style="max-width:560px;margin:0 auto;">
  <p style="margin:0 0 6px;font-size:13px;color:#8a7d71;">{escape(site['publisher'])} 수달일보 · {escape(_korean_date(day))}</p>
  <h1 style="margin:0 0 14px;font-size:22px;">오늘 게시글이 준비됐어요</h1>
  <a href="{page_url}"><img src="{thumbnail}" alt="오늘 카톡 미리보기 썸네일" width="560" style="width:100%;max-width:560px;border:2px solid #2a2420;border-radius:12px;display:block;"></a>
  <p style="margin:12px 0 18px;font-size:14px;">{escape(toon_line)}</p>
  <p style="margin:0 0 6px;font-size:14px;font-weight:700;">오픈채팅방에 붙여 넣을 글</p>
  <div style="white-space:pre-wrap;background:#fff;border:2px solid #2a2420;border-radius:12px;padding:14px;font-size:14px;line-height:1.6;">{escape(text)}</div>
  <p style="margin:10px 0 22px;font-size:12.5px;color:#8a7d71;">위 글을 길게 눌러 복사하거나, 아래 운영자 화면의 복사 버튼을 쓰세요.</p>
  <a href="{share_url}" style="display:block;text-align:center;background:#2c3553;color:#fff;text-decoration:none;font-weight:700;padding:14px;border-radius:12px;">운영자 화면 열기 (웹툰 확인 · 복사 버튼)</a>
</div>
</body></html>""", subtype="html")
    return message


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="오늘 수달일보 게시글을 메일로 보내기")
    parser.add_argument("--date", help="YYYY-MM-DD. 기본값: 오늘(한국 시간)")
    parser.add_argument("--dry-run", action="store_true", help="보내지 않고 내용만 출력")
    parser.add_argument("--once", action="store_true",
                        help="예약 재시도용: 오늘 이미 보냈으면 건너뛰고, 오늘 호가 아직 없으면 10:15 전까지는 다음 시도를 기다림")
    args = parser.parse_args(argv)

    now = datetime.now(KST)
    day = args.date or now.date().isoformat()
    marker = PROJECT / "data" / "mailed" / f"{day}.txt"
    if args.once:
        if marker.exists():
            print(f"{day} 메일은 이미 보냈습니다.")
            return 0
        if not (PROJECT / "data" / "news" / f"{day}.json").exists() and (now.hour, now.minute) < (10, 15):
            print("오늘 호가 아직 없어 다음 예약 시도에서 보냅니다.")
            return 0
    message = compose(day)
    recipients = [address.strip() for address in os.environ.get("MAIL_TO", "").split(",") if address.strip()]
    if args.dry_run:
        print("제목:", message["Subject"])
        print(message.get_body(("plain",)).get_content())
        return 0

    username, password = os.environ.get("MAIL_USERNAME"), os.environ.get("MAIL_PASSWORD")
    if not (username and password and recipients):
        print("[안내] MAIL_USERNAME / MAIL_PASSWORD / MAIL_TO 가 설정되지 않아 메일을 보내지 않습니다.")
        return 0  # 설정 전에는 실패로 처리하지 않는다
    message["From"] = f"수달일보 <{username}>"
    message["To"] = ", ".join(recipients)
    with smtplib.SMTP_SSL(os.environ.get("MAIL_SERVER") or "smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)
    print(f"메일 보냄 → {len(recipients)}명 ({message['Subject']})")
    if (PROJECT / "data" / "news" / f"{day}.json").exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{now.isoformat(timespec='minutes')} {message['Subject']}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
