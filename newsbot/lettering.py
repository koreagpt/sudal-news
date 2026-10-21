"""식자(글자 넣기): 그림 AI는 글자 없는 4컷만 그리고, 제목·말풍선·마무리 문구는 진짜 글꼴로 넣는다.

애니메이션 작화 스킬과 표정·행동 스킬이 권하는 "글자는 그림과 분리" 원칙을 따른다.
글자를 이미지 모델이 그리지 않으므로 한글이 깨지거나 띄어쓰기가 어긋날 수 없다.
"""
from __future__ import annotations

import math
from pathlib import Path

from .og import INK, MARKER, MUTED, NAVY, PAPER, _font

BROWN = (107, 74, 47)
SOFT_INK = (74, 64, 56)
SCALE = 2  # 두 배로 그려 줄여서 가장자리를 매끄럽게


# ---------- 컷 찾기 ----------

def find_panels(image) -> list[tuple[int, int]]:
    """크림색 여백(가로줄 전체가 밝은 줄)을 기준으로 위에서부터 컷의 (위, 아래) 좌표를 찾는다."""
    width, height = image.size
    small_w = 200
    small = image.convert("RGB").resize((small_w, height))  # 세로는 줄이지 않아 얇은 여백도 남긴다
    pixels = small.load()
    rows = []
    for y in range(height):
        light = 0
        for x in range(small_w):
            r, g, b = pixels[x, y]
            if min(r, g, b) > 200 and max(r, g, b) - min(r, g, b) < 45:
                light += 1
        rows.append(light / small_w > 0.94)

    segments, start = [], None
    for y, gutter in enumerate(rows + [True]):
        if not gutter and start is None:
            start = y
        elif gutter and start is not None:
            if y - start >= height * 0.08:
                segments.append((start, y))
            start = None
    return segments


# ---------- 글자 배치 ----------

def _wrap(text: str, font, max_width: float) -> list[str]:
    """띄어쓰기 단위로 줄을 나누고, 한 단어가 너무 길면 글자 단위로 자른다."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if font.getlength(trial) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = ""
        for char in word:
            if font.getlength(current + char) > max_width and current:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return lines


def bubble_size(text: str, page_width: int) -> tuple[int, int, list[str]]:
    """말풍선 크기(px)와 줄바꿈 결과. 글자 크기는 페이지 폭에 비례."""
    font = _font(round(page_width * 0.03))
    lines = _wrap(text, font, page_width * 0.27)
    line_h = font.size * 1.38
    text_w = max(font.getlength(line) for line in lines)
    pad_x, pad_y = font.size * 1.1, font.size * 0.8
    return round(text_w + pad_x * 2), round(line_h * len(lines) + pad_y * 2), lines


def _draw_bubble(draw, box, tail, lines, font, line_h):
    """흰 말풍선 + 말하는 쪽을 가리키는 꼬리 + 가운데 정렬 글자."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w, half_h = (x1 - x0) / 2, (y1 - y0) / 2
    outline = round(2.6 * SCALE)
    radius = min(half_h, half_w, 34 * SCALE)
    tail_shapes = None
    if tail:
        dx, dy = tail[0] - cx, tail[1] - cy
        distance = math.hypot(dx, dy) or 1.0
        ux, uy = dx / distance, dy / distance
        edge = min(half_w / max(abs(ux), 1e-3), half_h / max(abs(uy), 1e-3))  # 중심에서 풍선 테두리까지
        length = min(max(distance - edge, 0) * 0.55, 46 * SCALE)
        if length > 6 * SCALE:
            base = min(half_w, half_h) * 0.45
            depth = edge - 10 * SCALE                       # 꼬리 밑동은 풍선 안쪽에서 시작
            bx, by, px, py = cx + ux * depth, cy + uy * depth, -uy, ux
            tip = (cx + ux * (edge + length), cy + uy * (edge + length))
            outer = [(bx + px * base / 2, by + py * base / 2), tip, (bx - px * base / 2, by - py * base / 2)]
            inner_tip = (cx + ux * (edge + length * 0.6), cy + uy * (edge + length * 0.6))
            inner = [(bx + px * base * 0.32, by + py * base * 0.32), inner_tip, (bx - px * base * 0.32, by - py * base * 0.32)]
            tail_shapes = (outer, inner)
            draw.polygon(outer, fill="white", outline=INK, width=outline)
    draw.rounded_rectangle(box, radius, fill="white", outline=INK, width=outline)
    if tail_shapes:  # 풍선 테두리가 꼬리를 가로지르는 부분만 흰색으로 덮는다
        draw.polygon(tail_shapes[1], fill="white")
    total = line_h * len(lines)
    for index, line in enumerate(lines):
        draw.text((cx, cy - total / 2 + line_h * (index + 0.5)), line, font=font, fill=INK, anchor="mm")


def compose(art_path: Path, out_path: Path, script: dict, layout: list[list[dict]], panels: list[tuple[int, int]],
            note: str, source_name: str) -> None:
    """글자 없는 4컷 그림에 머리글·말풍선·바닥글을 진짜 글꼴로 얹어 한 장의 세로 웹툰으로 만든다."""
    from PIL import Image, ImageDraw

    art = Image.open(art_path).convert("RGB")
    width = art.width
    top, bottom = panels[0][0], panels[-1][1]
    pad = round(width * 0.025)
    header_h, footer_h = round(width * 0.17), round(width * 0.23)
    art_area = art.crop((0, max(top - pad, 0), width, min(bottom + pad, art.height)))
    offset = header_h - (top - max(top - pad, 0))
    height = header_h + art_area.height + footer_h

    page = Image.new("RGB", (width, height), PAPER)
    page.paste(art_area, (0, header_h))
    layer = Image.new("RGBA", (width * SCALE, height * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    S = SCALE

    # 머리글: 제목(형광펜 밑줄) + 부제. 오른쪽 위는 협회 로고 자리로 비운다.
    title_size = round(width * 0.068)
    title_font = _font(title_size * S)
    while title_font.getlength(script["title"]) > width * 0.56 * S and title_size > 30:
        title_size -= 2
        title_font = _font(title_size * S)
    title_w = title_font.getlength(script["title"])
    title_y = round(width * 0.075) * S
    draw.rounded_rectangle((width * S / 2 - title_w / 2 - 14 * S, title_y - title_size * 0.34 * S,
                            width * S / 2 + title_w / 2 + 14 * S, title_y + title_size * 0.08 * S), 10 * S, fill=MARKER + (230,))
    draw.text((width * S / 2, title_y), script["title"], font=title_font, fill=INK, anchor="ms")
    draw.text((width * S / 2, title_y + round(width * 0.052) * S), script["subtitle"],
              font=_font(round(width * 0.03) * S), fill=SOFT_INK, anchor="ms")

    # 말풍선
    bubble_font = _font(round(width * 0.03) * S)
    line_h = bubble_font.size * 1.38
    for panel_index, ((p_top, p_bottom), bubbles) in enumerate(zip(panels, layout)):
        p_top_page, p_bottom_page = p_top + offset, p_bottom + offset
        p_h = p_bottom_page - p_top_page
        script_bubbles = script["panels"][panel_index]["bubbles"]
        for bubble, spec in zip(script_bubbles, bubbles):
            w, h, lines = bubble_size(bubble["text"], width)
            margin = round(width * 0.045)  # 컷 테두리에서 띄우는 간격
            cx = min(max(spec["cx"] * width, margin + w / 2), width - margin - w / 2)
            cy = min(max(p_top_page + spec["cy"] * p_h, p_top_page + margin * 0.75 + h / 2), p_bottom_page - margin * 0.75 - h / 2)
            box = ((cx - w / 2) * S, (cy - h / 2) * S, (cx + w / 2) * S, (cy + h / 2) * S)
            tail = (spec["tail_x"] * width * S, (p_top_page + spec["tail_y"] * p_h) * S)
            _draw_bubble(draw, box, tail, lines, bubble_font, line_h)

    # 바닥글: 마무리 두 줄 + 작은 안내·출처
    foot_top = header_h + art_area.height
    close_font = _font(round(width * 0.05) * S)
    y1 = (foot_top + round(width * 0.075)) * S
    y2 = y1 + round(width * 0.072) * S
    line2_w = close_font.getlength(script["closing_line2"])
    draw.rounded_rectangle((width * S / 2 - line2_w / 2 - 12 * S, y2 - close_font.size * 0.42,
                            width * S / 2 + line2_w / 2 + 12 * S, y2 + close_font.size * 0.08), 10 * S, fill=MARKER + (230,))
    draw.text((width * S / 2, y1), script["closing_line1"], font=close_font, fill=NAVY, anchor="ms")
    draw.text((width * S / 2, y2), script["closing_line2"], font=close_font, fill=BROWN, anchor="ms")
    small = _font(round(width * 0.016) * S)
    base_y = (height - round(width * 0.025)) * S
    draw.text((round(width * 0.035) * S, base_y), note, font=small, fill=MUTED, anchor="ls")
    draw.text(((width - round(width * 0.035)) * S, base_y), f"소재: {source_name}", font=small, fill=MUTED, anchor="rs")

    layer = layer.resize((width, height), Image.LANCZOS)
    page.paste(layer, (0, 0), layer)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.save(out_path, quality=90, optimize=True, progressive=True)
