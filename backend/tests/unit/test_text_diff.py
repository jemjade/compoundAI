"""상대 텍스트 유사도와 선택적 공백 정규화를 검증한다."""

import asyncio
import time

from app.utils import text_diff
from app.utils.text_diff import compare_text


def assert_reconstructs(result: dict, base: str, target: str) -> None:
    reconstructed_base = "".join(
        part["text"] for part in result["diff"] if part["type"] in {"equal", "removed"}
    )
    reconstructed_target = "".join(
        part["text"] for part in result["diff"] if part["type"] in {"equal", "added"}
    )

    assert reconstructed_base == base
    assert reconstructed_target == target


def test_compare_text_reports_relative_similarity_and_changes() -> None:
    result = compare_text("계약 당사자는 A", "계약 당사자는 에이")

    assert 0 < result["similarity_ratio"] < 1
    assert result["added_count"] == 2
    assert result["removed_count"] == 1
    assert {part["type"] for part in result["diff"]} == {"equal", "removed", "added"}


def test_compare_text_can_normalize_whitespace() -> None:
    result = compare_text("hello\n\nworld", "hello world", normalize_whitespace=True)

    assert result["similarity_ratio"] == 1
    assert result["added_count"] == 0
    assert result["removed_count"] == 0


def test_large_identical_repetitive_text_uses_fast_path() -> None:
    text = "동일한 반복 조항 " * 10_000

    started = time.monotonic()
    result = compare_text(text, text)

    assert time.monotonic() - started < 0.1
    assert result["similarity_ratio"] == 1
    assert_reconstructs(result, " ".join(text.split()), " ".join(text.split()))


def test_large_repetitive_text_diff_is_bounded_and_reconstructable() -> None:
    lines = [
        (
            f"제{index % 200}조 계약 당사자는 개인정보 처리 및 문서 보관 의무를 준수한다. "
            f"test{index % 500}@example.com"
        )
        for index in range(5_000)
    ]
    base = "\n".join(lines)
    target = "\n".join(f"{index + 1:03d} | {line}" for index, line in enumerate(lines))

    started = time.monotonic()
    result = compare_text(base, target)
    elapsed = time.monotonic() - started

    normalized_base = " ".join(base.split())
    normalized_target = " ".join(target.split())

    assert elapsed < 2.5
    assert_reconstructs(result, normalized_base, normalized_target)


def test_large_text_uses_rare_words_as_fast_alignment_anchors() -> None:
    lines = [
        f"고유조항-{index} 계약 당사자는 개인정보 처리와 문서 보관 의무를 준수한다."
        for index in range(800)
    ]
    base = "\n".join(lines)
    target = "\n".join(f"{index + 1:03d} | {line}" for index, line in enumerate(lines))

    started = time.monotonic()
    result = compare_text(base, target)
    elapsed = time.monotonic() - started

    normalized_base = " ".join(base.split())
    normalized_target = " ".join(target.split())
    assert elapsed < 1.0
    assert result["similarity_ratio"] > 0.5
    assert_reconstructs(result, normalized_base, normalized_target)


async def test_compare_text_async_does_not_block_event_loop(monkeypatch) -> None:
    expected = {
        "similarity_ratio": 1.0,
        "added_count": 0,
        "removed_count": 0,
        "diff": [{"type": "equal", "text": "same"}],
    }

    def slow_compare(*_: object) -> dict:
        time.sleep(0.2)
        return expected

    monkeypatch.setattr(text_diff, "compare_text", slow_compare)
    task = asyncio.create_task(text_diff.compare_text_async("same", "same"))

    await asyncio.sleep(0.02)

    assert task.done() is False
    assert await task == expected
