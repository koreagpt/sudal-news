"""카카오톡 링크 미리보기용 썸네일(1200×630)을 만든다. Pillow가 없으면 건너뛴다."""
from __future__ import annotations

from pathlib import Path

WIDTH, HEIGHT = 1200, 630
PAPER, INK, MUTED = (251, 246, 236), (42, 36, 32), (138, 125, 113)
NAVY, MARKER, FUR_LIGHT = (44, 53, 83), (247, 220, 134), (232, 218, 198)

# (경로, ttc 안의 글꼴 번호) — 로컬 Windows와 GitHub Actions(Ubuntu) 순서로 찾는다
FONT_CANDIDATES = [
    ("C:/Windows/Fonts/NotoSansKR-VF.ttf", 0),
    ("C:/Windows/Fonts/malgunbd.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1),
    ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", 0),
]


def _font(size: int):
    from PIL import ImageFont

    for path, index in FONT_CANDIDATES:
        if Path(path).exists():
            font = ImageFont.truetype(path, size, index=index)
            try:
                font.set_variation_by_name("Bold")  # 가변 글꼴일 때만 적용됨
            except (OSError, ValueError):
                pass
            return font
    raise RuntimeError("한글 글꼴을 찾지 못했습니다. FONT_CANDIDATES를 확인하세요.")


def available() -> bool:
    try:
        import PIL  # noqa: F401
        _font(10)
        return True
    except Exception:
        return False


def make(out: Path, webtoon: Path | None, crop, publisher: str, name: str, date_label: str, news_count: int) -> None:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(canvas)

    # 오른쪽: 웹툰 일부를 둥근 액자에
    if webtoon and webtoon.exists():
        art = Image.open(webtoon).convert("RGB")
        if crop:
            art = art.crop(tuple(crop))
        box_w, box_h = 520, 570
        scale = max(box_w / art.width, box_h / art.height)
        art = art.resize((round(art.width * scale), round(art.height * scale)), Image.LANCZOS)
        left, top = (art.width - box_w) // 2, 0
        art = art.crop((left, top, left + box_w, top + box_h))
        x, y = WIDTH - box_w - 50, (HEIGHT - box_h) // 2
        draw.rounded_rectangle((x + 10, y + 10, x + box_w + 10, y + box_h + 10), 26, fill=FUR_LIGHT)
        mask = Image.new("L", (box_w, box_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, box_w - 1, box_h - 1), 24, fill=255)
        canvas.paste(art, (x, y), mask)
        draw.rounded_rectangle((x, y, x + box_w, y + box_h), 24, outline=INK, width=5)

    # 왼쪽: 협회 키커, 제호, 날짜, 오늘 구성
    x = 64
    chip_font, kicker_font = _font(30), _font(30)
    chip_w = draw.textlength(publisher, font=chip_font)
    draw.rounded_rectangle((x, 112, x + chip_w + 28, 162), 10, fill=NAVY)
    draw.text((x + 14, 137), publisher, font=chip_font, fill="white", anchor="lm")
    draw.text((x + chip_w + 42, 137), "수달 사원의", font=kicker_font, fill=INK, anchor="lm")

    title_font = _font(118)
    title_w = draw.textlength(name, font=title_font)
    draw.rectangle((x - 6, 268, x + title_w + 8, 312), fill=MARKER)
    draw.text((x, 300), name, font=title_font, fill=INK, anchor="ls")

    draw.text((x, 372), date_label, font=_font(36), fill=MUTED, anchor="ls")
    summary = f"오늘의 AI 뉴스 {news_count}건 · 4컷 웹툰" if news_count else "오늘의 4컷 웹툰"
    draw.text((x, 440), summary, font=_font(36), fill=INK, anchor="ls")
    draw.text((x, 540), "매일 아침 업데이트", font=_font(26), fill=MUTED, anchor="ls")

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=88, optimize=True)
