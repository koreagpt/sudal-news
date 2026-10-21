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


def merge_bubbles(script: dict) -> dict:
    """한 컷에서 같은 사람이 연달아 하는 말은 말풍선 하나에 줄을 바꿔 담는다 (읽는 순서가 꼬이지 않게)."""
    merged = {**script, "panels": []}
    for panel in script["panels"]:
        bubbles = []
        for bubble in panel["bubbles"]:
            if bubbles and bubbles[-1]["speaker"] == bubble["speaker"]:
                bubbles[-1] = {**bubbles[-1], "text": bubbles[-1]["text"] + "\n" + bubble["text"]}
            else:
                bubbles.append(dict(bubble))
        merged["panels"].append({**panel, "bubbles": bubbles})
    return merged


BUBBLE_SHAPES = [(0.27, 1.0), (0.21, 1.0), (0.34, 1.0), (0.21, 0.9), (0.16, 0.9)]  # (줄 너비 비율, 글자 크기 배율)


def bubble_size(text: str, page_width: int, wrap: float = 0.27, scale: float = 1.0) -> tuple[int, int, list[str]]:
    """말풍선 크기(px)와 줄바꿈 결과. 글자 크기는 페이지 폭에 비례. 줄바꿈 문자는 그대로 지킨다."""
    font = _font(round(page_width * 0.03 * scale))
    lines = [line for paragraph in text.split("\n") for line in _wrap(paragraph, font, page_width * wrap)]
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
    for panel_index, ((p_top, p_bottom), bubbles) in enumerate(zip(panels, layout)):
        p_top_page, p_bottom_page = p_top + offset, p_bottom + offset
        p_h = p_bottom_page - p_top_page
        script_bubbles = script["panels"][panel_index]["bubbles"]
        for bubble, spec in zip(script_bubbles, bubbles):
            wrap, scale = spec.get("wrap", 0.27), spec.get("scale", 1.0)
            w, h, lines = bubble_size(bubble["text"], width, wrap, scale)
            bubble_font = _font(round(width * 0.03 * scale) * S)
            line_h = bubble_font.size * 1.38
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


# ---------- 말풍선 자리 계산 ----------

def _overlap(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _match(name: str, heads: list[dict]):
    for head in heads:
        if head["name"] and (head["name"] in name or name in head["name"]):
            return head
    return None


def place_bubbles(width: int, panel_h: int, bubbles: list[tuple[str, str]], heads: list[dict],
                  keep_clear: list[tuple]) -> list[dict]:
    """얼굴 위치를 보고 말풍선 자리를 계산한다.

    heads: [{"name", "box": 머리 (x0, y0, x1, y1), "body": 몸 전체 상자(선택), "mouth": (x, y)}] — 컷 안의 픽셀 좌표.
    규칙: 어떤 얼굴도 가리지 않기 → 몸·중요한 소품도 되도록 피하고 빈 배경에 → 말하는 인물 가까이
          → 다른 인물보다 말하는 인물에 더 가깝게
          → 같은 컷의 말풍선끼리 겹치지 않고 읽는 순서(위→아래, 왼→오) 유지 → 위쪽 선호.
    bubbles: [(대사, 화자)]. 말풍선 모양(줄 너비·글자 크기)을 여러 가지로 시험해 가장 덜 가리는 자리를 고른다.
    돌려주는 값은 compose()가 쓰는 비율 좌표(cx·tail_x는 페이지 폭, cy·tail_y는 컷 높이 기준)와
    고른 모양(wrap, scale), 얼굴을 가린 비율(face_overlap: 말풍선 넓이 대비)이다.
    """
    margin_x, margin_y = width * 0.045, width * 0.034
    pad = width * 0.012
    grown = [(h["box"][0] - pad, h["box"][1] - pad, h["box"][2] + pad, h["box"][3] + pad) for h in heads]
    bodies = [tuple(h["body"]) for h in heads if h.get("body")]
    placed, layout = [], []
    for index, (text, speaker) in enumerate(bubbles):
        head = _match(speaker, heads)
        if head:
            hx, hy = (head["box"][0] + head["box"][2]) / 2, (head["box"][1] + head["box"][3]) / 2
            mouth = head["mouth"]
        else:  # 화면 속 목소리 등 얼굴이 없으면 컷 위쪽 가운데를 기준으로
            hx, hy, mouth = width / 2, panel_h * 0.55, (width / 2, panel_h * 0.6)
        best, best_cost = None, None
        for shape_index, (wrap, scale) in enumerate(BUBBLE_SHAPES):
          w, h, _ = bubble_size(text, width, wrap, scale)
          area = w * h
          steps_x = max(int((width - 2 * margin_x - w) / (width * 0.02)), 0)
          steps_y = max(int((panel_h - 2 * margin_y - h) / (panel_h * 0.03)), 0)
          for sx in range(steps_x + 1):
              cx = margin_x + w / 2 + sx * width * 0.02
              for sy in range(steps_y + 1):
                  cy = margin_y + h / 2 + sy * panel_h * 0.03
                  rect = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                  if any(_overlap(rect, (p[0] - 10, p[1] - 10, p[2] + 10, p[3] + 10)) for p in placed):
                      continue
                  cost = 60 * sum(_overlap(rect, g) for g in grown) / area
                  cost += 15 * sum(_overlap(rect, k) for k in keep_clear) / area
                  cost += 6 * sum(_overlap(rect, b) for b in bodies) / area
                  to_speaker = math.hypot(cx - hx, cy - hy)
                  cost += 3.0 * to_speaker / width
                  for other in heads:  # 다른 인물에 더 가까우면 꼬리가 헷갈린다
                      if other is head:
                          continue
                      ox, oy = (other["box"][0] + other["box"][2]) / 2, (other["box"][1] + other["box"][3]) / 2
                      if math.hypot(cx - ox, cy - oy) < to_speaker:
                          cost += 2.5
                  if placed:  # 읽는 순서: 다음 말풍선은 앞 말풍선의 오른쪽이나 아래에
                      prev = placed[-1]
                      prev_cx, prev_cy = (prev[0] + prev[2]) / 2, (prev[1] + prev[3]) / 2
                      clearly_below = rect[1] >= prev[3] - h * 0.25
                      if not clearly_below and cx < prev_cx:
                          cost += 4.0
                      if cy < prev_cy - h * 0.5:
                          cost += 2.0
                  cost += 1.2 * cy / panel_h
                  cost += 0.35 * shape_index  # 기본 모양을 우선
                  if best_cost is None or cost < best_cost:
                      face = sum(_overlap(rect, g) for g in grown) / area
                      best, best_cost = (cx, cy, rect, wrap, scale, face), cost
        if best is None:  # 둘 곳이 없으면 위쪽 가운데
            w, h, _ = bubble_size(text, width)
            cx, cy = width / 2, margin_y + h / 2
            best = (cx, cy, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 0.27, 1.0, 1.0)
        placed.append(best[2])
        layout.append({"cx": best[0] / width, "cy": best[1] / panel_h,
                       "tail_x": mouth[0] / width, "tail_y": mouth[1] / panel_h,
                       "wrap": best[3], "scale": best[4], "face_overlap": round(best[5], 3)})
    return layout
