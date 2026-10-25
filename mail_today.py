"""오늘 일보(그날 당번의 달몽·냐옹·뭉뭉일보) 게시글(날짜 주소 포함)을 운영자 메일로 보낸다. 표준 라이브러리만 사용.

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

from newsbot import KST, hosts
from newsbot.build import _korean_date, _webtoon_for, share_text

PROJECT = Path(__file__).resolve().parent


def compose(day: str) -> EmailMessage:
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    site = hosts.site_for(config["site"], day, PROJECT)
    base = site["base_url"].rstrip("/")
    send_url, page_url = f"{base}/send/{day}/", f"{base}/d/{day}/"
    news_path = PROJECT / "data" / "news" / f"{day}.json"

    message = EmailMessage()
    if not news_path.exists():  # 아침 발행이 실패했거나 늦어진 날
        message["Subject"] = f"[{site['name']}] {_korean_date(day, long=False)} 발행이 아직 안 됐어요"
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
        toon_line = "오늘 웹툰은 만들지 못해서 이전 웹툰이 나가요."
        if status.get("problems"):
            toon_line += f" (이유: {' / '.join(status['problems'][:2])})"

    message["Subject"] = f"{site['emoji']} {site['name']} {_korean_date(day, long=False)} 게시글 준비 완료 (당번 {site['reporter']['name']})"
    message.set_content(
        f"{toon_line}\n\n아래 글을 그대로 복사해서 오픈채팅방에 붙여 넣으세요.\n"
        f"----------------------------------------\n{text}\n----------------------------------------\n\n"
        f"카톡으로 공유하기(누르면 글이 복사되고 카톡이 열려요): {send_url}\n"
    )
    thumbnail = f"{base}/og/{day}.jpg"
    message.add_alternative(f"""<!doctype html>
<html lang="ko"><body style="margin:0;padding:24px 12px;background:#fbf6ec;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#2a2420;">
<div style="max-width:560px;margin:0 auto;">
  <p style="margin:0 0 6px;font-size:13px;color:#8a7d71;">{escape(site['publisher'])} {escape(site['name'])} · {escape(_korean_date(day))}</p>
  <h1 style="margin:0 0 14px;font-size:22px;">오늘 게시글이 준비됐어요</h1>
  <a href="{page_url}"><img src="{thumbnail}" alt="오늘 카톡 미리보기 썸네일" width="560" style="width:100%;max-width:560px;border:2px solid #2a2420;border-radius:12px;display:block;"></a>
  <p style="margin:12px 0 14px;font-size:14px;">{escape(toon_line)}</p>
  <a href="{send_url}" style="display:block;text-align:center;background:#fee500;color:#191600;text-decoration:none;font-weight:700;font-size:17px;padding:16px;border:2px solid #2a2420;border-radius:12px;">카카오톡으로 공유하기</a>
  <p style="margin:8px 0 22px;font-size:12.5px;color:#8a7d71;text-align:center;">누르면 열리는 화면에서 노란 버튼을 누르면 글이 복사되고 카톡이 열려요. 오픈채팅방에 붙여 넣으세요.</p>
  <p style="margin:0 0 6px;font-size:14px;font-weight:700;">오픈채팅방에 붙여 넣을 글</p>
  <div style="white-space:pre-wrap;background:#fff;border:2px solid #2a2420;border-radius:12px;padding:14px;font-size:14px;line-height:1.6;">{escape(text)}</div>
  <p style="margin:10px 0 0;font-size:12.5px;color:#8a7d71;">공유 버튼이 안 되면 위 글을 길게 눌러 복사해서 붙여 넣어도 돼요.</p>
</div>
</body></html>""", subtype="html")
    return message


def _warn_webtoon(day: str, warned: Path, dry_run: bool) -> int:
    """정오까지 웹툰이 안 되면 운영자에게만 알린다 (카톡·게시글은 웹툰이 완성될 때까지 보내지 않음)."""
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    status = json.loads((PROJECT / "data" / "news" / f"{day}.json").read_text(encoding="utf-8")).get("webtoon_status") or {}
    problems = " / ".join(status.get("problems", [])[:2])
    if "credit" in problems or "insufficient_quota" in problems:
        reason = "OpenAI 크레딧이 떨어졌어요. https://platform.openai.com/settings/organization/billing/ 에서 충전하면 다음 예약 발행이 이어서 만들어요."
    else:
        reason = f"마지막 문제: {problems}" if problems else ""
    message = EmailMessage()
    message["Subject"] = f"[{hosts.host_for(day, PROJECT)['paper']}] {_korean_date(day, long=False)} 웹툰을 아직 다시 만드는 중이에요"
    actions = f"https://github.com/{config['site']['repo']}/actions/workflows/daily.yml"
    message.set_content("오늘 웹툰이 아직 검수를 통과하지 못해 게시글과 카톡을 보내지 않고 기다리고 있어요.\n"
                        "예약 발행이 계속 다시 만들고, 완성되면 바로 보내요. 급하면 실행 화면에서 Run workflow(webtoon)를 눌러 주세요.\n"
                        f"{actions}" + (f"\n\n{reason}" if reason else ""))
    if dry_run:
        print("제목:", message["Subject"])
        return 0
    if _send(message):
        warned.parent.mkdir(parents=True, exist_ok=True)
        warned.write_text(datetime.now(KST).isoformat(timespec="minutes") + "\n", encoding="utf-8")
    return 0


def _send(message: EmailMessage) -> bool:
    recipients = [address.strip() for address in os.environ.get("MAIL_TO", "").split(",") if address.strip()]
    username, password = os.environ.get("MAIL_USERNAME"), os.environ.get("MAIL_PASSWORD")
    if not (username and password and recipients):
        print("[안내] MAIL_USERNAME / MAIL_PASSWORD / MAIL_TO 가 설정되지 않아 메일을 보내지 않습니다.")
        return False
    message["From"] = f"한국GPT협회 일보 <{username}>"
    message["To"] = ", ".join(recipients)
    with smtplib.SMTP_SSL(os.environ.get("MAIL_SERVER") or "smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)
    print(f"메일 보냄 → {len(recipients)}명 ({message['Subject']})")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="오늘 일보 게시글을 메일로 보내기")
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
        news_path = PROJECT / "data" / "news" / f"{day}.json"
        if not news_path.exists() and (now.hour, now.minute) < (10, 15):
            print("오늘 호가 아직 없어 다음 예약 시도에서 보냅니다.")
            return 0
        if news_path.exists() and not (json.loads(news_path.read_text(encoding="utf-8")).get("webtoon_status") or {}).get("ok"):
            # 웹툰까지 한 묶음이 돼야 보낸다. 웹툰을 다시 만드는 중이면 완성된 뒤(발행 직후) 보낸다
            warned = PROJECT / "data" / "mailed" / f"{day}-webtoon-wait.txt"
            if now.hour < 12 or warned.exists():
                print("오늘 웹툰을 다시 만드는 중이라, 완성되면 보냅니다.")
                return 0
            return _warn_webtoon(day, warned, args.dry_run)
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
    message["From"] = f"한국GPT협회 일보 <{username}>"
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
