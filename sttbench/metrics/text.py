"""Dependency-free Korean-friendly CER and whitespace WER."""

from __future__ import annotations

import re
import unicodedata

ANNOTATION = re.compile(r"\([^)]*\)|\[[^]]*\]|<[^>]*>")
NON_TEXT = re.compile(r"[^0-9a-zA-Z가-힣\s]")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = ANNOTATION.sub(" ", text)
    text = NON_TEXT.sub(" ", text)
    return " ".join(text.split())


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for index, ref_item in enumerate(reference, start=1):
        current = [index]
        for position, hyp_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[position] + 1,
                    previous[position - 1] + (ref_item != hyp_item),
                )
            )
        previous = current
    return previous[-1]


def compare(reference: str, hypothesis: str) -> dict[str, float | int | str]:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    ref_chars = list(ref.replace(" ", ""))
    hyp_chars = list(hyp.replace(" ", ""))
    ref_words = ref.split()
    hyp_words = hyp.split()
    char_errors = edit_distance(ref_chars, hyp_chars)
    word_errors = edit_distance(ref_words, hyp_words)
    return {
        "normalized_reference": ref,
        "normalized_hypothesis": hyp,
        "character_errors": char_errors,
        "reference_characters": len(ref_chars),
        "cer": char_errors / max(1, len(ref_chars)),
        "word_errors": word_errors,
        "reference_words": len(ref_words),
        "wer": word_errors / max(1, len(ref_words)),
    }

