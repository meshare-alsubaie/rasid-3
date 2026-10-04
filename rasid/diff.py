"""المقارِن: يطلّع الكتل الجديدة فقط مقارنة بما رآه المحرّك سابقاً. بلا ذكاء ولا تكلفة."""
from __future__ import annotations

from rasid.fetch import Block, FetchResult


def new_blocks(prev_hashes: set[str], result: FetchResult) -> list[Block]:
    seen: set[str] = set()
    out: list[Block] = []
    for b in result.blocks:
        h = b.hash
        if h not in prev_hashes and h not in seen:
            out.append(b)
        seen.add(h)
    return out
