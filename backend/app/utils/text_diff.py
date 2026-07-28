"""SequenceMatcher 기반 문자 단위 상대 텍스트 비교."""

from difflib import SequenceMatcher


def compare_text(base: str, target: str, normalize_whitespace: bool = True) -> dict:
    """정확도가 아닌 문자 단위의 상대 유사도와 변경 사항을 반환한다."""
    if normalize_whitespace:
        base = " ".join(base.split())
        target = " ".join(target.split())
    matcher = SequenceMatcher(None, base, target, autojunk=False)
    parts: list[dict[str, str]] = []
    added_count = 0
    removed_count = 0
    for operation, base_start, base_end, target_start, target_end in matcher.get_opcodes():
        if operation in {"equal", "delete", "replace"} and base_start != base_end:
            part_type = "equal" if operation == "equal" else "removed"
            text = base[base_start:base_end]
            parts.append({"type": part_type, "text": text})
            if part_type == "removed":
                removed_count += len(text)
        if operation in {"insert", "replace"} and target_start != target_end:
            text = target[target_start:target_end]
            parts.append({"type": "added", "text": text})
            added_count += len(text)
    return {
        "similarity_ratio": round(matcher.ratio(), 4),
        "added_count": added_count,
        "removed_count": removed_count,
        "diff": parts,
    }
