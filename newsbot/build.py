"""data/ 의 뉴스·웹툰 기록으로 정적 페이지(public/)를 만든다."""
from __future__ import annotations

import json
import os
import shutil
from datetime import date as Date, datetime
from html import escape
from pathlib import Path

from . import KST, og

WEEKDAYS = "월화수목금토일"


def _korean_date(day: str, long: bool = True) -> str:
    value = Date.fromisoformat(day)
    weekday = WEEKDAYS[value.weekday()]
    return f"{value.month}월 {value.day}일 {weekday}요일" if long else f"{value.month}.{value.day} ({weekday})"


def _time(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(KST).strftime("%m.%d %H:%M")


def _webtoon_for(day: str, webtoons: list[dict]):
    """그날 웹툰, 없으면 그 이전 가장 최근 웹툰."""
    past = [toon for toon in webtoons if toon["date"] <= day]
    if not past:
        return None, False
    toon = max(past, key=lambda toon: toon["date"])
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
<link rel="icon" href="{root}static/img/sudal-face.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jua&display=swap">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="{root}static/style.css">
</head>
<body>
<div class="page">"""


def _brand_name(site: dict) -> str:
    return f"{site['publisher']} {site['name']}"


def _masthead(site: dict, root: str, dateline: str, jump: str = "") -> str:
    publisher = escape(site["publisher"])
    kicker = escape(site.get("kicker", "")).replace(publisher, f"<strong>{publisher}</strong>", 1)
    reporter = site.get("reporter", {})
    return f"""
<header class="masthead">
  <p class="kicker">{kicker}</p>
  <a class="brand" href="{root}index.html" aria-label="{escape(_brand_name(site))} 첫 화면">
    <span class="badge" aria-hidden="true">
      <span class="badge-org">{publisher}</span>
      <img src="{root}static/img/sudal-face.png" alt="" width="56" height="56">
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
    contact = ""
    if site.get("publisher_url"):
        contact = (f'<a class="contact" href="{escape(site["publisher_url"])}" target="_blank" rel="noopener">'
                   f'{escape(site.get("contact_text", "문의하기"))} <span aria-hidden="true">↗</span></a>')
    return f"""
<footer class="footer">
  <a class="archive-link" href="{root}archive/index.html">지난 {escape(site["name"])} 보기</a>
  <section class="idcard" aria-label="기자 소개">
    <div class="idcard-top"><strong>{publisher}</strong><span>사원증</span></div>
    <div class="idcard-body">
      <img src="{root}static/img/sudal-face.png" alt="수달 사원" width="76" height="76">
      <dl>
        <div><dt>이름</dt><dd>{escape(reporter.get("name", ""))}</dd></div>
        <div><dt>담당</dt><dd>{escape(reporter.get("role", ""))}</dd></div>
        <div><dt>사번</dt><dd>{escape(reporter.get("employee_no", ""))}</dd></div>
      </dl>
    </div>
    <p class="idcard-intro">“{escape(reporter.get("intro", ""))}”</p>
  </section>
  <p class="org"><strong>{publisher}</strong> {escape(site["publisher_line"])}</p>{contact}
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
    label = "오늘의 수달 사원" if is_today else "수달 사원 웹툰"
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


def _news_section(news: dict | None, root: str) -> str:
    items = (news or {}).get("items", [])
    if not items:
        return """
<section class="news"><div class="empty">
  <p>오늘의 뉴스는 아직 정리 중이에요.</p><p>수달 사원이 커피 한 잔 마시고 곧 가져올게요.</p>
</div></section>"""
    cards = []
    for number, item in enumerate(items, 1):
        summary = f'<p class="summary">{escape(item["summary"])}</p>' if item.get("summary") else ""
        comment = ""
        if item.get("comment"):
            comment = f"""
    <div class="comment">
      <img src="{root}static/img/sudal-face.png" alt="수달 사원" width="34" height="34">
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
    return f"""
<section class="news" id="news" aria-label="오늘의 AI 뉴스">
  <div class="section-head">
    <h2><mark>오늘의 AI 뉴스</mark></h2>
    <span class="count">{len(items)}건</span>
  </div>
  <ol class="cards">{"".join(cards)}
  </ol>
</section>"""


def _description(news: dict | None) -> str:
    titles = [item["title"] for item in (news or {}).get("items", [])[:3]]
    return " / ".join(titles) if titles else "한국GPT협회에 다니는 수달 사원이 매일 아침 골라오는 AI 뉴스"


def render_day(site, day, news, webtoons, issue_no, root, url, og_image) -> str:
    toon, is_today = _webtoon_for(day, webtoons)
    title = f"{_brand_name(site)} · {_korean_date(day, long=False)} AI 뉴스"
    dateline = f'<time datetime="{day}">{_korean_date(day)}</time> · 제{issue_no}호'
    count = len((news or {}).get("items", []))
    jump = ""
    if count and toon:  # 웹툰이 길어서 뉴스로 바로 내려가는 버튼을 둔다
        jump = f'\n  <a class="jump" href="#news">오늘의 AI 뉴스 {count}건 바로 보기 <span aria-hidden="true">↓</span></a>'
    return (
        _head(site, title, _description(news), root, og_image, url)
        + _masthead(site, root, dateline, jump)
        + "\n<main>"
        + _webtoon_section(toon, is_today, root)
        + _news_section(news, root)
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
    """오픈채팅방에 그대로 붙여 넣을 게시글."""
    base = site.get("base_url", "").rstrip("/")
    url = f"{base}/d/{day}/" if base else f"(배포 주소 설정 전) d/{day}/"
    items = news.get("items", [])
    lines = [f"🦦 {_brand_name(site)} | {_korean_date(day, long=False)}", f"오늘의 AI 뉴스 {len(items)}건", ""]
    lines += [f"{number}. {item['title']}" for number, item in enumerate(items, 1)]
    lines += ["", "👉 4컷 웹툰과 뉴스 요약 보기" if any(item.get("summary") for item in items) else "👉 4컷 웹툰과 뉴스 보기", url]
    return "\n".join(lines)


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
      navigator.clipboard.writeText(area.value).then(done);
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


def build(project: Path, config: dict) -> Path:
    site = dict(config["site"])
    site["base_url"] = os.environ.get("SITE_BASE_URL") or site.get("base_url", "")
    out = project / "public"
    news_dir = project / "data" / "news"
    webtoons = json.loads((project / "data" / "webtoons.json").read_text(encoding="utf-8"))
    newses = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(news_dir.glob("*.json"))}
    days = sorted(newses)

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(project / "static", out / "static")
    (out / "webtoons").mkdir(parents=True)
    for toon in webtoons:
        shutil.copy2(project / "data" / "webtoons" / toon["image"], out / "webtoons" / toon["image"])

    thumbnails = og.available()
    if not thumbnails:
        print("[안내] Pillow나 한글 글꼴이 없어 카톡 썸네일 대신 웹툰 원본을 미리보기로 씁니다.")

    def og_image(day: str):
        toon, _ = _webtoon_for(day, webtoons)
        if not thumbnails:
            return f"webtoons/{toon['image']}" if toon else None
        target = f"og/{day}.jpg"
        og.make(
            out / target,
            project / "data" / "webtoons" / toon["image"] if toon else None,
            toon.get("og_crop") if toon else None,
            site["publisher"], site["name"], _korean_date(day), len(newses.get(day, {}).get("items", [])),
        )
        return target

    for issue_no, day in enumerate(days, 1):
        page = out / "d" / day / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            render_day(site, day, newses[day], webtoons, issue_no, "../../", f"d/{day}/", og_image(day)),
            encoding="utf-8",
        )

    today = days[-1] if days else datetime.now(KST).date().isoformat()
    (out / "index.html").write_text(
        render_day(site, today, newses.get(today), webtoons, len(days) or 1, "", "", og_image(today)),
        encoding="utf-8",
    )
    for name, html in (("archive", render_archive(site, days, newses)), ("share", render_share(site, days, newses, webtoons))):
        (out / name).mkdir(exist_ok=True)
        (out / name / "index.html").write_text(html, encoding="utf-8")
    return out
