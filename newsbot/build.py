"""data/ 의 뉴스·웹툰 기록으로 정적 페이지(public/)를 만든다."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import date as Date, datetime
from html import escape
from pathlib import Path

from . import KST, hosts, og

WEEKDAYS = "월화수목금토일"
# 디자인(style.css)이 바뀌면 주소 꼬리표도 바뀌어 브라우저가 옛 디자인을 쓰지 않는다
_STYLE_VERSION = hashlib.md5((Path(__file__).resolve().parent.parent / "static" / "style.css").read_bytes()).hexdigest()[:8]


def _korean_date(day: str, long: bool = True) -> str:
    value = Date.fromisoformat(day)
    weekday = WEEKDAYS[value.weekday()]
    return f"{value.month}월 {value.day}일 {weekday}요일" if long else f"{value.month}.{value.day} ({weekday})"


def _time(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(KST).strftime("%m.%d %H:%M")


def _webtoon_for(day: str, webtoons: list[dict]):
    """그날 웹툰, 없으면 그 이전 가장 최근 웹툰."""
    past = [(toon["date"], order, toon) for order, toon in enumerate(webtoons) if toon["date"] <= day]
    if not past:
        return None, False
    toon = max(past, key=lambda entry: entry[:2])[2]  # 같은 날이면 나중에 추가된 웹툰
    return toon, toon["date"] == day


def _head(site: dict, title: str, description: str, root: str, og_image: str | None, url: str) -> str:
    base = site.get("base_url", "").rstrip("/")
    og = [
        f'<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{escape(_brand_name(site))}">',
        f'<meta property="og:title" content="{escape(title)}">',
        f'<meta property="og:description" content="{escape(description)}">',
    ]
    if base:  # 카카오 미리보기는 절대 주소가 필요하다
        og.append(f'<meta property="og:url" content="{escape(base + "/" + url)}">')
        if og_image:
            og.append(f'<meta property="og:image" content="{escape(base + "/" + og_image)}">')
            og.append('<meta name="twitter:card" content="summary_large_image">')
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
{chr(10).join(og)}
<link rel="icon" href="{root}{site.get("face", "static/img/dalmong-face.png")}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jua&display=swap">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="{root}static/style.css?v={_STYLE_VERSION}">{_theme(site)}{_analytics(site, url)}
</head>
<body>
<div class="page">"""


OPERATOR_PAGES = ("share/", "kakao/", "send/")  # 운영자 화면은 방문 통계에서 뺀다


def _analytics(site: dict, url: str) -> str:
    """구글 애널리틱스 (방문 수, 협회·강의·블로그로 나가는 클릭은 '향상된 측정'이 자동으로 센다)."""
    tag = site.get("analytics_id")
    if not tag or url.startswith(OPERATOR_PAGES):
        return ""
    return f"""
<script async src="https://www.googletagmanager.com/gtag/js?id={escape(tag)}"></script>
<script>window.dataLayer = window.dataLayer || []; function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date()); gtag('config', '{escape(tag)}');</script>"""


def _utm(url: str, medium: str) -> str:
    """협회 사이트·블로그 쪽 통계에서 '일보에서 들어온 방문'이 보이게 꼬리표를 붙인다."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({"utm_source": "sudal_news", "utm_medium": medium, "utm_campaign": "daily_news"})
    return urlunsplit(parts._replace(query=urlencode(query)))


def _theme(site: dict) -> str:
    """그날 당번의 테마 색 (기본 틀은 그대로, 강조색·형광펜 색만 바꾼다)."""
    theme = site.get("theme")
    if not theme:
        return ""
    return f"\n<style>:root {{ --navy: {theme['accent']}; --marker: {theme['marker']}; }}</style>"


def _crew(site: dict, root: str) -> str:
    """하루씩 돌아가며 일보를 맡는 당번 사원 3명의 사원증 (오늘 당번 강조)."""
    crew = site.get("hosts") or []
    if len(crew) < 2:
        return ""
    today = site.get("host", {}).get("id")
    cards = []
    for host in crew:
        on = host["id"] == today
        cards.append(
            f'<li class="crew-card{" on" if on else ""}" style="--crew: {host["theme"]["accent"]}">'
            f'<span class="crew-top">{escape(host["paper"])}</span>'
            f'<img src="{root}{host["face"]}" alt="" width="56" height="56">'
            f'<strong>{escape(host["name"])}</strong><span class="crew-role">{escape(host["reporter"]["role"])}</span>'
            + ('<span class="crew-today">오늘 당번</span>' if on else "") + "</li>"
        )
    return f"""
  <section class="crew" aria-label="일보 당번 사원">
    <h2 class="crew-title">하루씩 돌아가며 맡아요</h2>
    <ol class="crew-cards">{"".join(cards)}</ol>
  </section>"""


def _brand_name(site: dict) -> str:
    return f"{site['publisher']} {site['name']}"


def _week_of(day: str) -> tuple[int, int, int, str]:
    """(연, 월, 주차, 기간) — 1주차는 1~7일, 2주차는 8~14일처럼 날짜로 나눈다."""
    d = Date.fromisoformat(day)
    week = (d.day - 1) // 7 + 1
    first = (week - 1) * 7 + 1
    last_day = ((Date(d.year + (d.month == 12), d.month % 12 + 1, 1)) - Date(d.year, d.month, 1)).days
    return d.year, d.month, week, f"{d.month}.{first}~{d.month}.{min(first + 6, last_day)}"


def _drawer(site: dict, root: str) -> str:
    """왼쪽 위 ☰ 메뉴: 지난 일보를 월 → 주차 → 날짜로 모아 보여 준다."""
    days = site.get("nav_days") or []
    if not days:
        return ""
    current = site.get("current_day") or days[0]["day"]
    open_week = _week_of(current)[:3]
    months: dict = {}
    for item in days:  # 최신순
        year, month, week, span = _week_of(item["day"])
        months.setdefault((year, month), {}).setdefault((week, span), []).append(item)
    blocks = []
    for (year, month), weeks in months.items():
        rows = []
        for (week, span), items in weeks.items():
            links = "".join(
                f'<li><a href="{root}d/{item["day"]}/index.html"{' aria-current="page"' if item["day"] == current else ""}>'
                f'<span class="d-date">{_korean_date(item["day"], long=False)}</span>'
                f'<span class="d-paper">{escape(item["emoji"])} {escape(item["paper"])}</span>'
                f'<span class="d-title">{escape(item["title"])}</span></a></li>'
                for item in items
            )
            is_open = " open" if (year, month, week) == open_week else ""
            rows.append(f'<details{is_open}><summary>{week}주차 <span>{span}</span></summary><ul>{links}</ul></details>')
        blocks.append(f'<section class="drawer-month"><h3>{year}년 {month}월</h3>{"".join(rows)}</section>')
    org = "".join(  # 맨 위: 하단과 같은 협회 바로가기 버튼
        f'<a class="org-link" href="{escape(_utm(link["url"], "menu"))}" target="_blank" rel="noopener">{escape(link["label"])} <span aria-hidden="true">↗</span></a>'
        for link in site.get("links", [])
    )
    org = f'\n  <nav class="drawer-org" aria-label="{escape(site["publisher"])} 바로가기">{org}</nav>' if org else ""
    return f"""
<button type="button" class="menu-btn" aria-label="지난 일보 목록 열기" aria-controls="drawer" aria-expanded="false">
  <span></span><span></span><span></span>
</button>
<div class="drawer-backdrop" hidden></div>
<nav class="drawer" id="drawer" aria-label="지난 일보" hidden>
  <div class="drawer-head"><strong>{escape(site["publisher"])}</strong><button type="button" class="drawer-close" aria-label="닫기">✕</button></div>{org}
  <h2 class="drawer-title">지난 일보</h2>
  {"".join(blocks)}
  <a class="drawer-all" href="{root}archive/index.html">전체 목록 보기</a>
</nav>
<script>
(function () {{
  var button = document.querySelector('.menu-btn'), drawer = document.getElementById('drawer'),
      backdrop = document.querySelector('.drawer-backdrop');
  var toggle = function (open) {{
    drawer.hidden = backdrop.hidden = !open;
    button.setAttribute('aria-expanded', open);
    document.body.classList.toggle('drawer-open', open);
    if (open) drawer.querySelector('.drawer-close').focus();
  }};
  button.addEventListener('click', function () {{ toggle(true); }});
  backdrop.addEventListener('click', function () {{ toggle(false); }});
  drawer.querySelector('.drawer-close').addEventListener('click', function () {{ toggle(false); button.focus(); }});
  document.addEventListener('keydown', function (event) {{ if (event.key === 'Escape' && !drawer.hidden) toggle(false); }});
}})();
</script>"""


def _masthead(site: dict, root: str, dateline: str, jump: str = "") -> str:
    publisher = escape(site["publisher"])
    kicker = escape(site.get("kicker", "")).replace(publisher, f"<strong>{publisher}</strong>", 1)
    reporter = site.get("reporter", {})
    return _drawer(site, root) + f"""
<header class="masthead">
  <p class="kicker">{kicker}</p>
  <a class="brand" href="{root}index.html" aria-label="{escape(_brand_name(site))} 첫 화면">
    <span class="badge" aria-hidden="true">
      <span class="badge-org">{publisher}</span>
      <img src="{root}{site.get("face", "static/img/dalmong-face.png")}" alt="" width="56" height="56">
      <span class="badge-name">{escape(reporter.get("name", ""))}</span>
    </span>
    <span class="wordmark">{escape(site["name"])}</span>
  </a>
  <p class="tagline">{escape(site["tagline"])}</p>
  <p class="dateline">{dateline}</p>{jump}
</header>"""


def _footer(site: dict, root: str) -> str:
    publisher = escape(site["publisher"])
    reporter = site.get("reporter", {})
    links = "".join(
        f'<a class="org-link" href="{escape(_utm(link["url"], "footer"))}" target="_blank" rel="noopener">'
        f'{escape(link["label"])} <span aria-hidden="true">↗</span></a>'
        for link in site.get("links", [])
    )
    contact = f'\n  <nav class="org-links" aria-label="{publisher} 교육 안내">{links}</nav>' if links else ""
    return f"""
<footer class="footer">
  <a class="archive-link" href="{root}archive/index.html">지난 일보 보기</a>
  <section class="idcard" aria-label="기자 소개">
    <div class="idcard-top"><strong>{publisher}</strong><span>사원증</span></div>
    <div class="idcard-body">
      <img src="{root}{site.get("face", "static/img/dalmong-face.png")}" alt="{escape(reporter.get("name", ""))}" width="76" height="76">
      <dl>
        <div><dt>이름</dt><dd>{escape(reporter.get("name", ""))}</dd></div>
        <div><dt>담당</dt><dd>{escape(reporter.get("role", ""))}</dd></div>
        <div><dt>사번</dt><dd>{escape(reporter.get("employee_no", ""))}</dd></div>
      </dl>
    </div>
    <p class="idcard-intro">“{escape(reporter.get("intro", ""))}”</p>
  </section>{_crew(site, root)}
  <p class="org"><strong>{publisher}</strong>에서 AI를 배워 보세요</p>{contact}
  <p class="fine">{escape(_brand_name(site))}는 {publisher}가 매일 아침 전하는 AI 뉴스 브리핑입니다.
  기사의 저작권은 각 언론사에 있으며, 요약은 AI가 작성해 원문과 다를 수 있습니다.</p>
</footer>
</div>
</body>
</html>
"""


def _webtoon_section(toon: dict | None, is_today: bool, root: str) -> str:
    if not toon:
        return ""
    name = hosts.host_for(toon["date"])["name"]
    label = f"오늘의 {name}" if is_today else f"{name} 웹툰"
    image = f"{root}webtoons/{escape(toon['image'])}"
    source = ""
    if toon.get("source_url"):
        source = f' · 소재 <a href="{escape(toon["source_url"])}" target="_blank" rel="noopener">{escape(toon["source_name"])}</a>'
    return f"""
<section class="toon" aria-label="{label}">
  <div class="section-head">
    <h2><mark>{label}</mark></h2>
    <span class="toon-name">{escape(toon["title"])}</span>
  </div>
  <a class="toon-frame" href="{image}" target="_blank" rel="noopener">
    <img src="{image}" alt="{escape(toon['alt'])}" width="1024" height="1536" loading="eager">
  </a>
  <p class="toon-note">{escape(toon.get("note", ""))}{source}</p>
</section>"""


def _ad_card(ad: dict, root: str, site: dict) -> str:
    """뉴스 3번 다음에 끼우는 협회 강의 카드 (광고임을 분명히 표시)."""
    return f"""
  <li class="card ad-card">
    <div class="card-meta"><span class="ad-label">협회 강의</span><span class="ad-format">{escape(ad.get("format", ""))}</span></div>
    <p class="ad-hook">{escape(ad["hook"])}</p>
    <h3><a href="{escape(_utm(ad["url"], "course_card"))}" target="_blank" rel="noopener">{escape(ad["title"])}</a></h3>
    <p class="summary">{escape(ad["pitch"])}</p>
    <div class="comment">
      <img src="{root}{site.get("face", "static/img/dalmong-face.png")}" alt="{escape(site.get("reporter", {}).get("name", ""))}" width="34" height="34">
      <p>{escape(ad["comment"])}</p>
    </div>
    <p class="source">한국GPT협회 온라인교육
      <a class="ad-go" href="{escape(_utm(ad["url"], "course_card"))}" target="_blank" rel="noopener">강의 보러 가기 <span aria-hidden="true">↗</span></a></p>
  </li>"""


def _news_section(news: dict | None, root: str, site: dict) -> str:
    items = (news or {}).get("items", [])
    if not items:
        return f"""
<section class="news"><div class="empty">
  <p>오늘의 뉴스는 아직 정리 중이에요.</p><p>{escape(hosts.josa(site.get("reporter", {}).get("name", "당번 사원"), "이/가"))} 곧 가져올게요.</p>
</div></section>"""
    cards = []
    for number, item in enumerate(items, 1):
        summary = f'<p class="summary">{escape(item["summary"])}</p>' if item.get("summary") else ""
        comment = ""
        if item.get("comment"):
            comment = f"""
    <div class="comment">
      <img src="{root}{site.get("face", "static/img/dalmong-face.png")}" alt="{escape(site.get("reporter", {}).get("name", ""))}" width="34" height="34">
      <p>{escape(item["comment"])}</p>
    </div>"""
        cards.append(f"""
  <li class="card">
    <div class="card-meta"><span class="num">{number:02d}</span><span class="cat">{escape(item["category"])}</span></div>
    <h3><a href="{escape(item["link"])}" target="_blank" rel="noopener">{escape(item["title"])}</a></h3>
    {summary}{comment}
    <p class="source">{escape(item["source"])} · {_time(item["published"])}
      <a href="{escape(item["link"])}" target="_blank" rel="noopener">원문 보기 <span aria-hidden="true">↗</span></a></p>
  </li>""")
        if number == min(3, len(items)) and (news or {}).get("ad"):
            cards.append(_ad_card(news["ad"], root, site))
    return f"""
<section class="news" id="news" aria-label="오늘의 AI 뉴스">
  <div class="section-head">
    <h2><mark>오늘의 AI 뉴스</mark></h2>
    <span class="count">{len(items)}건</span>
  </div>
  <ol class="cards">{"".join(cards)}
  </ol>
</section>"""


def _blog_banner(site: dict) -> str:
    """뉴스 6건 아래 가로 배너: 협회 블로그 글 하나 (기사 중간 강의 카드와는 다른 모양)."""
    banner = site.get("blog_banner")
    if not banner or not banner.get("url"):
        return ""
    return f"""
<a class="blog-banner" href="{escape(_utm(banner["url"], "blog_banner"))}" target="_blank" rel="noopener">
  <span class="blog-banner-icon" aria-hidden="true">{escape(banner.get("icon", "📝"))}</span>
  <span class="blog-banner-text"><span class="blog-banner-label">{escape(banner.get("label", "AI 정보 블로그"))}</span>
    <span class="blog-banner-title">{escape(banner["title"])}</span></span>
  <span class="blog-banner-go">보러 가기 <span aria-hidden="true">↗</span></span>
</a>"""


def _description(news: dict | None, site: dict) -> str:
    titles = [item["title"] for item in (news or {}).get("items", [])[:3]]
    return " / ".join(titles) if titles else site["tagline"]


def render_day(site, day, news, webtoons, issue_no, root, url, og_image) -> str:
    site = {**site, "current_day": day}
    toon, is_today = _webtoon_for(day, webtoons)
    # 카톡 링크 미리보기에서 한 줄로 보이게 짧게: "한국GPT협회 뭉뭉일보 · 10.25"
    title = f"{_brand_name(site)} · {_korean_date(day, long=False).split(' ')[0]}"
    dateline = f'<time datetime="{day}">{_korean_date(day)}</time> · 제{issue_no}호'
    count = len((news or {}).get("items", []))
    jump = ""
    if count and toon:  # 웹툰이 길어서 뉴스로 바로 내려가는 버튼을 둔다
        jump = f'\n  <a class="jump" href="#news">오늘의 AI 뉴스 {count}건 바로 보기 <span aria-hidden="true">↓</span></a>'
    return (
        _head(site, title, _description(news, site), root, og_image, url)
        + _masthead(site, root, dateline, jump)
        + "\n<main>"
        + _webtoon_section(toon, is_today, root)
        + _news_section(news, root, site)
        + _blog_banner(site)
        + "\n</main>"
        + _footer(site, root)
    )


def render_archive(site, days, newses, root="../") -> str:
    rows = []
    for issue_no, day in sorted(enumerate(days, 1), key=lambda pair: pair[1], reverse=True):
        items = newses[day].get("items", [])
        headline = escape(items[0]["title"]) if items else "뉴스 없음"
        rows.append(
            f'<li><a href="{root}d/{day}/index.html"><span class="a-date">{_korean_date(day, long=False)} · 제{issue_no}호</span>'
            f'<span class="a-head">{headline}</span></a></li>'
        )
    return (
        _head(site, f"지난 {_brand_name(site)}", f"{_brand_name(site)} 지난 호 모음", root, None, "archive/")
        + _masthead(site, root, "지난 호 모아보기")
        + f'\n<main><section class="archive"><ol>{"".join(rows)}</ol></section></main>'
        + _footer(site, root)
    )


def share_text(site: dict, day: str, news: dict) -> str:
    """오픈채팅방에 그대로 붙여 넣을 게시글 (그날 당번의 일보 이름으로)."""
    site = hosts.site_for(site, day)
    base = site.get("base_url", "").rstrip("/")
    # 오픈채팅방에서 몇 명이 들어왔는지 방문 통계에서 따로 보이게 꼬리표 (링크 미리보기는 그대로 뜬다)
    url = f"{base}/d/{day}/?utm_source=openchat" if base else f"(배포 주소 설정 전) d/{day}/"
    items = news.get("items", [])
    lines = [f"{site['emoji']} {_brand_name(site)} | {_korean_date(day, long=False)}", f"오늘의 AI 뉴스 {len(items)}건", ""]
    lines += [f"{number}. {item['title']}" for number, item in enumerate(items, 1)]
    lines += ["", "👉 4컷 웹툰과 뉴스 요약 보기" if any(item.get("summary") for item in items) else "👉 4컷 웹툰과 뉴스 보기", url]
    return "\n".join(lines).strip()  # 끝에 빈 줄·공백이 붙지 않게


def _webtoon_panel(site, day, news, webtoons, root) -> str:
    """운영자용: 오늘 웹툰 상태와 다시 만들기 안내."""
    toon, is_today = _webtoon_for(day, webtoons)
    status = news.get("webtoon_status")
    if is_today and toon:
        head = f'<p class="toon-state ok">오늘 웹툰 완성: <strong>{escape(toon["title"])}</strong></p>'
        preview = (f'<a class="toon-thumb" href="{root}webtoons/{escape(toon["image"])}" target="_blank" rel="noopener">'
                   f'<img src="{root}webtoons/{escape(toon["image"])}" alt="{escape(toon["alt"])}" loading="lazy"></a>')
    else:
        reason = ""
        if status and status.get("problems"):
            reason = "<br>이유: " + escape(" / ".join(status["problems"][:3]))
        elif not status:
            reason = "<br>이유: 웹툰 자동 생성이 아직 실행되지 않았어요 (OpenAI 키 확인)."
        shown = f'지금 페이지에는 {_korean_date(toon["date"], long=False)} 웹툰이 나와요.' if toon else ""
        head = f'<p class="toon-state warn">오늘 웹툰을 만들지 못했어요. {shown}{reason}</p>'
        preview = ""
    redo = ""
    if site.get("repo"):
        url = f"https://github.com/{site['repo']}/actions/workflows/daily.yml"
        redo = f"""
  <details class="redo">
    <summary>웹툰 다시 만들기</summary>
    <ol>
      <li><a href="{url}" target="_blank" rel="noopener">GitHub 실행 화면</a>을 엽니다 (GitHub 앱에서도 돼요).</li>
      <li><strong>Run workflow</strong> → mode에서 <strong>webtoon</strong>을 고릅니다.</li>
      <li>다른 뉴스로 만들려면 topic에 뉴스 번호(1~6)를 적습니다.</li>
      <li><strong>Run workflow</strong>를 누르고 3~5분 뒤 이 페이지를 새로고침합니다.</li>
    </ol>
  </details>"""
    return f'\n<section class="toon-admin">{head}{preview}{redo}\n</section>'


def render_share(site, days, newses, webtoons, root="../") -> str:
    blocks = []
    if days:
        blocks.append(_webtoon_panel(site, max(days), newses[max(days)], webtoons, root))
    for day in sorted(days, reverse=True)[:7]:
        text = share_text(site, day, newses[day])
        blocks.append(f"""
<section class="share-day">
  <div class="section-head"><h2><mark>{_korean_date(day)}</mark></h2></div>
  <textarea readonly rows="{text.count(chr(10)) + 2}">{escape(text)}</textarea>
  <button type="button" class="copy">게시글 복사하기</button>
</section>""")
    body = "".join(blocks) or '<div class="empty"><p>아직 발행한 호가 없어요.</p></div>'
    script = """
<script>
document.querySelectorAll('.copy').forEach(function (button) {
  button.addEventListener('click', function () {
    var area = button.previousElementSibling;
    var done = function () { button.textContent = '복사했어요! 오픈채팅방에 붙여 넣으세요'; setTimeout(function () { button.textContent = '게시글 복사하기'; }, 2500); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(area.value.trim()).then(done);
    } else { area.select(); document.execCommand('copy'); done(); }
  });
});
</script>"""
    page = (
        _head(site, f"{_brand_name(site)} 게시글 복사", "오픈채팅방 게시용", root, None, "share/")
        + _masthead(site, root, "오픈채팅방 게시글 복사 · 운영자용")
        + f'\n<main><p class="share-help">링크는 날짜별 주소예요. 카카오톡에 붙이면 그날 썸네일이 미리보기로 떠요.</p>{body}</main>'
        + _footer(site, root)
    )
    return page.replace("</body>", script + "\n</body>").replace("<head>", '<head>\n<meta name="robots" content="noindex">', 1)


def render_send(site, day, news, og_image, root="../../") -> str:
    """운영자용: 아침 메일의 '카톡으로 공유하기' 버튼이 여는 페이지.

    휴대폰 공유 창(Web Share)으로 게시글을 그대로 보내서, 오픈채팅방에 직접 쓴 글처럼 올라가고 링크 미리보기도 뜬다.
    """
    text = share_text(site, day, news)
    thumb = f'<img class="send-thumb" src="{root}{og_image}" alt="오늘 카톡 미리보기 썸네일">' if og_image else ""
    body = f"""
<section class="send">
  {thumb}
  <button type="button" class="send-kakao" id="share">카카오톡으로 공유하기</button>
  <button type="button" class="send-kakao send-test" id="share-b">공유하기 (시험 B: 끝 빈칸 없애기)</button>
  <p class="send-help">누르고 <strong>카카오톡</strong> → 오픈채팅방을 고르면 직접 쓴 글처럼 올라가요.</p>
  <button type="button" class="copy" id="copy">글만 복사하기</button>
  <details class="send-text"><summary>올라갈 글 보기</summary><pre id="text">{escape(text)}</pre></details>
</section>"""
    script = """
<script>
(function () {
  var text = document.getElementById('text').textContent.trim();
  var copyButton = document.getElementById('copy');
  var copy = function (after) {
    var done = function () { copyButton.textContent = '복사했어요! 오픈채팅방에 붙여 넣으세요'; if (after) after(); };
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(done, function () { fallback(); done(); }); }
    else { fallback(); done(); }
  };
  var fallback = function () {
    var area = document.createElement('textarea'); area.value = text; document.body.appendChild(area);
    area.select(); document.execCommand('copy'); document.body.removeChild(area);
  };
  document.getElementById('share').addEventListener('click', function () {
    if (navigator.share) {
      navigator.share({ text: text }).catch(function (error) { if (error && error.name !== 'AbortError') copy(); });
    } else {  // 공유 창이 없는 앱 안 브라우저 등: 복사로 대신
      copy(function () { alert('이 화면에서는 공유 창을 열 수 없어 글을 복사했어요.\\n카카오톡 오픈채팅방에 붙여 넣어 주세요.'); });
    }
  });
  // 시험 B: 본문과 주소를 나눠서 넘긴다 (공유 창이 끝에 줄바꿈을 붙이는지 비교용)
  document.getElementById('share-b').addEventListener('click', function () {
    var lines = text.split('\\n'), url = lines.pop().trim();
    if (navigator.share) {
      navigator.share({ text: lines.join('\\n').trim(), url: url }).catch(function (error) { if (error && error.name !== 'AbortError') copy(); });
    } else { copy(); }
  });
  copyButton.addEventListener('click', function () { copy(); });
})();
</script>"""
    page = (
        _head(site, f"{_brand_name(site)} 카톡 공유", "운영자용", root, None, f"send/{day}/")
        + _masthead(site, root, f"{_korean_date(day)} · 오픈채팅방 공유")
        + f"\n<main>{body}</main>"
        + "\n</div>\n</body>\n</html>"
    )
    return page.replace("</body>", script + "\n</body>").replace("<head>", '<head>\n<meta name="robots" content="noindex">', 1)


def render_kakao(site, root="../") -> str:
    """운영자용: 카카오톡 '나에게 보내기' 연결 페이지 (카카오 로그인 Redirect URI).

    REST API 키는 공개 저장소에 두지 않으려고, 연결할 때 이 화면에 직접 붙여 넣게 한다 (브라우저 밖으로 안 나감).
    """
    actions = f"https://github.com/{site['repo']}/actions/workflows/kakao.yml" if site.get("repo") else "#"
    body = f"""
<section class="toon-admin" id="start">
  <p class="toon-state"><strong>1. 카카오 연결하기</strong></p>
  <p class="share-help">카카오 개발자 화면 → 앱 → 플랫폼 키의 <strong>REST API 키</strong>를 붙여 넣고 버튼을 누르세요.
  키는 이 브라우저에서 카카오 로그인 주소를 만드는 데만 쓰여요.</p>
  <div class="share-day"><textarea id="rest" rows="1" placeholder="REST API 키 붙여 넣기" autocomplete="off" spellcheck="false"></textarea>
  <button type="button" class="copy" id="go">카카오로 연결하기</button></div>
</section>
<section class="toon-admin" id="done" hidden>
  <p class="toon-state ok"><strong>2. 인증 코드가 나왔어요</strong> (10분 안에 써 주세요)</p>
  <div class="share-day"><textarea id="code" readonly rows="3"></textarea>
  <button type="button" class="copy" id="copy">인증 코드 복사하기</button></div>
  <ol class="share-help">
    <li><a href="{actions}" target="_blank" rel="noopener">GitHub 카카오 연결 화면</a>을 엽니다.</li>
    <li><strong>Run workflow</strong> → code 칸에 복사한 코드를 붙여 넣고 실행합니다.</li>
    <li>1분쯤 뒤 카카오톡 <strong>나와의 채팅</strong>에 시험 메시지가 오면 끝이에요.</li>
  </ol>
</section>
<section class="toon-admin" id="fail" hidden>
  <p class="toon-state warn" id="failtext"></p>
</section>"""
    script = """
<script>
(function () {
  var params = new URLSearchParams(location.search);
  var show = function (id) { ['start', 'done', 'fail'].forEach(function (s) { document.getElementById(s).hidden = s !== id; }); };
  if (params.get('code')) {
    show('done');
    document.getElementById('code').value = params.get('code');
    history.replaceState(null, '', location.pathname);  // 주소창·기록에 코드가 남지 않게
  } else if (params.get('error')) {
    show('fail');
    document.getElementById('failtext').textContent = '연결하지 못했어요: ' + (params.get('error_description') || params.get('error')) + ' — 처음부터 다시 해 주세요.';
  }
  document.getElementById('go').addEventListener('click', function () {
    var key = document.getElementById('rest').value.trim();
    if (!key) { alert('REST API 키를 먼저 붙여 넣어 주세요.'); return; }
    var redirect = location.origin + location.pathname;
    location.href = 'https://kauth.kakao.com/oauth/authorize?response_type=code&scope=talk_message'
      + '&client_id=' + encodeURIComponent(key) + '&redirect_uri=' + encodeURIComponent(redirect);
  });
  document.getElementById('copy').addEventListener('click', function () {
    var area = document.getElementById('code'), button = this;
    var done = function () { button.textContent = '복사했어요!'; };
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(area.value.trim()).then(done); }
    else { area.select(); document.execCommand('copy'); done(); }
  });
})();
</script>"""
    page = (
        _head(site, f"{_brand_name(site)} 카카오톡 연결", "운영자용", root, None, "kakao/")
        + _masthead(site, root, "카카오톡 나에게 보내기 연결 · 운영자용")
        + f"\n<main>{body}</main>"
        + _footer(site, root)
    )
    return page.replace("</body>", script + "\n</body>").replace("<head>", '<head>\n<meta name="robots" content="noindex">', 1)


def build(project: Path, config: dict) -> Path:
    site = dict(config["site"])
    site["base_url"] = os.environ.get("SITE_BASE_URL") or site.get("base_url", "")
    out = project / "public"
    news_dir = project / "data" / "news"
    webtoons = json.loads((project / "data" / "webtoons.json").read_text(encoding="utf-8"))
    newses = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(news_dir.glob("*.json"))}
    days = sorted(newses)
    nav = []  # ☰ 메뉴의 지난 일보 목록 (최신순)
    for day in reversed(days):
        toon, is_today = _webtoon_for(day, webtoons)
        items = newses[day].get("items", [])
        host = hosts.host_for(day, project)
        nav.append({"day": day, "paper": host["paper"], "emoji": host["emoji"],
                    "title": toon["title"] if (toon and is_today) else (items[0]["title"] if items else "")})
    site["nav_days"] = nav

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(project / "static", out / "static")
    (out / "webtoons").mkdir(parents=True)
    thumbnails = og.available()
    for toon in webtoons:  # 게시용 웹툰에만 협회 로고를 얹는다 (data/의 원본은 그대로)
        source, target = project / "data" / "webtoons" / toon["image"], out / "webtoons" / toon["image"]
        if thumbnails:
            og.stamp_badge(source, target, site["publisher"])
        else:
            shutil.copy2(source, target)

    if not thumbnails:
        print("[안내] Pillow나 한글 글꼴이 없어 카톡 썸네일 대신 웹툰 원본을 미리보기로 씁니다.")

    def og_image(day: str):
        toon, _ = _webtoon_for(day, webtoons)
        if not thumbnails:
            return f"webtoons/{toon['image']}" if toon else None
        target = f"og/{day}.jpg"
        host_site = hosts.site_for(site, day, project)
        og.make(
            out / target,
            project / "data" / "webtoons" / toon["image"] if toon else None,
            toon.get("og_crop") if toon else None,
            site["publisher"], host_site["name"], _korean_date(day), len(newses.get(day, {}).get("items", [])),
            kicker=host_site["reporter"]["name"] + "의", marker=host_site["theme"]["marker"],
        )
        return target

    for issue_no, day in enumerate(days, 1):
        day_site = hosts.site_for(site, day, project)
        page = out / "d" / day / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        thumbnail = og_image(day)
        page.write_text(
            render_day(day_site, day, newses[day], webtoons, issue_no, "../../", f"d/{day}/", thumbnail),
            encoding="utf-8",
        )
        send = out / "send" / day / "index.html"  # 아침 메일의 '카톡으로 공유하기' 버튼
        send.parent.mkdir(parents=True, exist_ok=True)
        send.write_text(render_send(day_site, day, newses[day], thumbnail), encoding="utf-8")

    today = days[-1] if days else datetime.now(KST).date().isoformat()
    site = hosts.site_for(site, today, project)
    (out / "index.html").write_text(
        render_day(site, today, newses.get(today), webtoons, len(days) or 1, "", "", og_image(today)),
        encoding="utf-8",
    )
    pages = (("archive", render_archive(site, days, newses)), ("share", render_share(site, days, newses, webtoons)),
             ("kakao", render_kakao(site)))
    for name, html in pages:
        (out / name).mkdir(exist_ok=True)
        (out / name / "index.html").write_text(html, encoding="utf-8")
    return out
