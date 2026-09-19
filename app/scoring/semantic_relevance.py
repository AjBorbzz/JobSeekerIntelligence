import numpy as np 

def cosine_similarity(vector_a: list[float], vector_b: list[float],) -> float: 
    a = np.asarray(vector_a, dtype=np.float64,)
    b = np.asarray(vector_b, dtype=np.float64,)

    if a.shape != b.shape:
        raise ValueError("Embedding vectors must have the same dimensions.")

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        raise ValueError ("Embedding vectors cannot have zero magnitude.")

    similarity = np.dot(a, b) / (norm_a * norm_b)

    return float(np.clip(similarity, -1.0, 1.0))

def similarity_to_score(similarity: float,) -> float:
    bounded = max(0.0, min(1,0, similarity))
    return round(bounded * 100, 2)