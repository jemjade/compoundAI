"""시간 제한이 있는 문자 단위 상대 텍스트 비교."""

import asyncio
from collections import Counter
from difflib import SequenceMatcher
from typing import Literal

from diff_match_patch import diff_match_patch

DIFF_TIMEOUT_SECONDS = 1.0
LARGE_TEXT_MIN_CHARACTERS = 20_000
MAX_WORD_DIFF_WORDS = 25_000
MAX_MATCHABLE_WORD_OCCURRENCES = 8
MAX_CONCURRENT_TEXT_DIFFS = 2
DiffPartType = Literal["equal", "removed", "added"]
_diff_slots = asyncio.Semaphore(MAX_CONCURRENT_TEXT_DIFFS)


def _append_part(
    parts: list[dict[str, str]],
    part_type: DiffPartType,
    text: str,
) -> None:
    """인접한 같은 유형을 합쳐 응답과 Frontend 렌더링 비용을 줄인다."""
    if not text:
        return
    if parts and parts[-1]["type"] == part_type:
        parts[-1]["text"] += text
        return
    parts.append({"type": part_type, "text": text})


def _summarize(parts: list[dict[str, str]], base_length: int, target_length: int) -> dict:
    equal_count = sum(len(part["text"]) for part in parts if part["type"] == "equal")
    added_count = sum(len(part["text"]) for part in parts if part["type"] == "added")
    removed_count = sum(len(part["text"]) for part in parts if part["type"] == "removed")
    total_length = base_length + target_length
    similarity_ratio = 1.0 if total_length == 0 else (2 * equal_count) / total_length
    return {
        "similarity_ratio": round(similarity_ratio, 4),
        "added_count": added_count,
        "removed_count": removed_count,
        "diff": parts,
    }


def _append_word(
    parts: list[dict[str, str]],
    part_type: DiffPartType,
    word: str,
    has_previous_word: bool,
) -> None:
    _append_part(parts, part_type, f"{' ' if has_previous_word else ''}{word}")


def _compare_large_normalized_text(base: str, target: str) -> dict | None:
    """희소 단어를 Anchor로 사용해 관리 가능한 대용량 Text를 빠르게 정렬한다."""
    base_words = base.split()
    target_words = target.split()
    if len(base_words) + len(target_words) > MAX_WORD_DIFF_WORDS:
        return None

    frequencies = Counter(base_words)
    frequencies.update(target_words)
    matcher = SequenceMatcher(
        lambda word: frequencies[word] > MAX_MATCHABLE_WORD_OCCURRENCES,
        base_words,
        target_words,
        autojunk=False,
    )
    parts: list[dict[str, str]] = []
    base_has_word = False
    target_has_word = False

    for operation, base_start, base_end, target_start, target_end in matcher.get_opcodes():
        if operation == "equal":
            for base_word in base_words[base_start:base_end]:
                if base_has_word and target_has_word:
                    _append_part(parts, "equal", " ")
                elif base_has_word:
                    _append_part(parts, "removed", " ")
                elif target_has_word:
                    _append_part(parts, "added", " ")
                _append_part(parts, "equal", base_word)
                base_has_word = True
                target_has_word = True
        if operation in {"delete", "replace"}:
            for word in base_words[base_start:base_end]:
                _append_word(parts, "removed", word, base_has_word)
                base_has_word = True
        if operation in {"insert", "replace"}:
            for word in target_words[target_start:target_end]:
                _append_word(parts, "added", word, target_has_word)
                target_has_word = True

    return _summarize(parts, len(base), len(target))


def _compare_with_deadline(base: str, target: str) -> dict:
    """대용량·반복 입력에서도 제한시간 뒤 유효한 최선의 Diff를 반환한다."""
    differ = diff_match_patch()
    differ.Diff_Timeout = DIFF_TIMEOUT_SECONDS
    operations = differ.diff_main(base, target, checklines=True)

    parts: list[dict[str, str]] = []
    operation_types: dict[int, DiffPartType] = {
        differ.DIFF_EQUAL: "equal",
        differ.DIFF_DELETE: "removed",
        differ.DIFF_INSERT: "added",
    }
    for operation, text in operations:
        _append_part(parts, operation_types[operation], text)
    return _summarize(parts, len(base), len(target))


def compare_text(base: str, target: str, normalize_whitespace: bool = True) -> dict:
    """제한 시간 안에서 문자 단위 상대 유사도와 변경 사항을 반환한다.

    정규화한 대용량 Text는 희소 단어 Anchor로 먼저 비교한다. 단어 수도 큰 입력은
    제한시간이 지나면 계산된 최선의 유효한 Diff를 반환해 Worker 장기 점유를 막는다.
    """
    if normalize_whitespace:
        base = " ".join(base.split())
        target = " ".join(target.split())
    if base == target:
        parts = [{"type": "equal", "text": base}] if base else []
        return _summarize(parts, len(base), len(target))

    if normalize_whitespace and len(base) + len(target) >= LARGE_TEXT_MIN_CHARACTERS:
        word_diff = _compare_large_normalized_text(base, target)
        if word_diff is not None:
            return word_diff
    return _compare_with_deadline(base, target)


async def compare_text_async(
    base: str,
    target: str,
    normalize_whitespace: bool = True,
) -> dict:
    """CPU 중심 Diff를 ASGI 이벤트 루프 밖에서 계산한다."""
    async with _diff_slots:
        return await asyncio.to_thread(compare_text, base, target, normalize_whitespace)
