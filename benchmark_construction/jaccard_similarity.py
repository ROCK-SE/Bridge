import re

def ngrams(text: str, n: int) -> set:
    """
    Generate a set of n-grams from the given text.

    Args:
        text: Input string.
        n: Size of the n-gram.

    Returns:
        A set of n-grams.
    """
    # Normalize text: collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # If text shorter than n, return empty set
    if len(text) < n:
        return set()
    # Generate n-grams
    return {text[i:i+n] for i in range(len(text) - n + 1)}

def original_jaccard_similarity(text1: str, text2: str, n: int) -> float:
    """
    Compute the Jaccard similarity between two texts based on n-grams.

    Args:
        text1: First text string.
        text2: Second text string.
        n: n-gram length (must be provided explicitly).

    Returns:
        Jaccard similarity (float between 0 and 1).
    """
    # Generate sets of n-grams
    grams1 = ngrams(text1, n)
    grams2 = ngrams(text2, n)

    # Compute intersection and union
    intersection = grams1.intersection(grams2)
    union = grams1.union(grams2)

    # Handle empty union
    return len(intersection) / len(union) if union else 0.0

def update_jaccard_similarity(text1: str, text2: str, n: int) -> float:
    """
    Compute the similarity between two texts based on n-grams,
    using intersection over the minimum of the two gram set sizes.

    Args:
        text1: First text string.
        text2: Second text string.
        n: n-gram length (must be provided explicitly).

    Returns:
        Similarity score (float between 0 and 1).
    """
    grams1 = ngrams(text1, n)
    grams2 = ngrams(text2, n)

    intersection_size = len(grams1.intersection(grams2))
    min_size = min(len(grams1), len(grams2))

    # Avoid division by zero
    return intersection_size / min_size if min_size > 0 else 0.0

    
