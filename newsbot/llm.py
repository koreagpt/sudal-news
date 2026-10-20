"""OpenAI API 호출 모음: 구조화된 JSON 응답, 이미지 입력, 이미지 생성."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path


def has_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _client():
    from openai import OpenAI  # 기본 모드만 쓸 때는 SDK 없이도 동작하도록 여기서 불러온다

    return OpenAI()


def ask_json(model: str, instructions: str, content, schema: dict, name: str, effort: str | None = None) -> dict:
    """content(글 또는 입력 항목 목록)를 보내고 schema에 맞는 JSON을 dict로 받는다."""
    extra = {"reasoning": {"effort": effort}} if effort else {}
    response = _client().responses.create(
        model=model,
        instructions=instructions,
        input=content,
        text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
        **extra,
    )
    if response.status == "incomplete":
        raise RuntimeError(f"응답이 중간에 끊겼습니다: {response.incomplete_details}")
    if not response.output_text:
        raise RuntimeError("응답에 내용이 없습니다 (요청이 거절됐을 수 있음).")
    return json.loads(response.output_text)


def image_part(path: Path) -> dict:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "input_image", "image_url": f"data:{mime};base64,{data}"}


def draw(model: str, prompt: str, references: list[Path], size: str, quality: str) -> bytes:
    """참고 이미지를 넣어 새 그림을 만들고 JPEG 바이트로 돌려준다."""
    files = [path.open("rb") for path in references]
    try:
        result = _client().images.edit(
            model=model,
            image=files,
            prompt=prompt,
            size=size,
            quality=quality,
            output_format="jpeg",
            output_compression=88,
        )
    finally:
        for file in files:
            file.close()
    return base64.b64decode(result.data[0].b64_json)
