"""Tests for domain-agnostic exam RAG helpers."""
from utils.exam_rag import question_grounding_score, tokenize


def test_question_grounding_score_high_when_supported():
    excerpt = (
        "Python uses indentation to define code blocks. "
        "Functions are defined with the def keyword."
    )
    q = "What keyword is used to define a function in Python?"
    choices = ["class", "def", "function", "lambda"]
    score = question_grounding_score(q, choices, "B", excerpt)
    assert score >= 0.15


def test_question_grounding_score_low_when_hallucinated():
    excerpt = "Photosynthesis converts light energy into chemical energy in plants."
    q = "What is the capital of France?"
    choices = ["London", "Paris", "Berlin", "Madrid"]
    score = question_grounding_score(q, choices, "B", excerpt)
    assert score < 0.1


def test_tokenize_keeps_words_longer_than_two_chars():
    tokens = tokenize("The quick brown fox")
    assert "quick" in tokens
    assert "fox" in tokens
    assert "an" not in tokens  # len <= 2 filtered
