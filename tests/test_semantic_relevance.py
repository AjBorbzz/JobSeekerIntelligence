import pytest

from app.scoring.semantic_relevance import (
    cosine_similarity,
    similarity_to_score,
)


def test_identical_vectors():

    vector = [
        1.0,
        0.0,
        0.0,
    ]

    result = cosine_similarity(
        vector,
        vector,
    )

    assert result == pytest.approx(
        1.0
    )


def test_orthogonal_vectors():

    a = [
        1.0,
        0.0,
    ]

    b = [
        0.0,
        1.0,
    ]

    result = cosine_similarity(
        a,
        b,
    )

    assert result == pytest.approx(
        0.0
    )


def test_opposite_vectors():

    a = [
        1.0,
        0.0,
    ]

    b = [
        -1.0,
        0.0,
    ]

    result = cosine_similarity(
        a,
        b,
    )

    assert result == pytest.approx(
        -1.0
    )


def test_similarity_to_score():

    assert similarity_to_score(
        0.8754
    ) == 87.54


def test_negative_similarity_score():

    assert similarity_to_score(
        -0.50
    ) == 0.0


def test_dimension_mismatch():

    with pytest.raises(ValueError):

        cosine_similarity(
            [1.0, 2.0],
            [1.0, 2.0, 3.0],
        )