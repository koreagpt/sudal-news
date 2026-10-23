"""하루씩 돌아가며 일보를 맡는 당번 사원 (data/hosts.json).

예: 달몽일보(달몽 사원) → 냐옹일보(냐옹 대리) → 뭉뭉일보(뭉뭉 인턴) → 다시 달몽일보.
"""
from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=None)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(project: Path = PROJECT) -> dict:
    return _load(str(project / "data" / "hosts.json"))


def all_hosts(project: Path = PROJECT) -> list[dict]:
    data = load(project)
    by_id = {host["id"]: host for host in data["hosts"]}
    return [by_id[host_id] for host_id in data["order"]]


def host_for(day: str, project: Path = PROJECT) -> dict:
    """그날의 당번. 시작일 전 날짜는 첫 번째 당번(달몽 사원)이 맡은 것으로 본다.

    HOST_TEST 환경변수(예: nyaong)가 있으면 그 당번으로 바꾼다 — 웹툰 시험(webtoontest)에서만 쓴다.
    """
    data, hosts = load(project), all_hosts(project)
    if os.environ.get("HOST_TEST"):
        return next(host for host in hosts if host["id"] == os.environ["HOST_TEST"])
    offset = (date.fromisoformat(day) - date.fromisoformat(data["start"])).days
    return hosts[offset % len(hosts)] if offset >= 0 else hosts[0]


def site_for(site: dict, day: str, project: Path = PROJECT) -> dict:
    """config의 site에 그날 당번의 이름·소개·색·얼굴을 얹은 사본 (사원증 3장용 전체 목록도 함께)."""
    host = host_for(day, project)
    return {
        **site,
        "name": host["paper"],
        "kicker": host["kicker"],
        "tagline": host["tagline"],
        "reporter": host["reporter"],
        "emoji": host["emoji"],
        "theme": host["theme"],
        "face": host["face"],
        "host": host,
        "hosts": all_hosts(project),
    }


def josa(word: str, pair: str) -> str:
    """받침에 맞는 조사를 붙인다. pair는 '이/가', '은/는', '을/를', '와/과' 처럼 받침 있을 때/없을 때."""
    with_batchim, without = pair.split("/")
    last = word[-1]
    has = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return word + (with_batchim if has else without)
