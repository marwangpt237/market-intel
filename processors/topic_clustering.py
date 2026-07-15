"""
Topic clustering — groups items by semantic similarity using deterministic TF-IDF.

No AI. Uses:
1. TF-IDF vectors built from item titles + bodies
2. Cosine similarity between vectors
3. Greedy agglomerative clustering (merge clusters if similarity > threshold)

Each item gets a "cluster_id" and "cluster_label" in its metadata.
Clusters are labeled with the most common keywords across member items.
"""
from __future__ import annotations

import re
import math
from collections import Counter, defaultdict
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


def tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, split into tokens."""
    import re
    text = text.lower().strip()
    tokens = re.findall(r"\b[a-z0-9]{2,}\b", text)
    return set(tokens)


STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "this", "that", "these",
    "those", "i", "you", "he", "she", "it", "we", "they", "what", "which",
    "who", "when", "where", "why", "how", "all", "each", "every", "some",
    "any", "no", "not", "as", "if", "than", "too", "very", "just", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "up", "down", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "your", "their", "its", "our",
    "has", "had", "having", "been", "being", "am", "is", "are", "was",
})


def build_tfidf_vectors(items: list[ProcessedItem]) -> list[dict[str, float]]:
    """Build TF-IDF vectors for all items."""
    # Tokenize all documents
    documents = []
    for item in items:
        text = f"{item.title} {item.body}"
        tokens = [t for t in tokenize(text) if t not in STOP_WORDS and len(t) >= 3]
        documents.append(tokens)

    # Document frequency
    df: dict[str, int] = defaultdict(int)
    for tokens in documents:
        for token in set(tokens):
            df[token] += 1

    n_docs = len(documents)
    if n_docs == 0:
        return []

    # IDF
    idf: dict[str, float] = {}
    for token, count in df.items():
        idf[token] = math.log((n_docs + 1) / (count + 1)) + 1

    # TF-IDF vectors
    vectors = []
    for tokens in documents:
        tf = Counter(tokens)
        vec = {token: (count / len(tokens)) * idf.get(token, 0) for token, count in tf.items()}
        vectors.append(vec)

    return vectors


def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors."""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in vec_a if k in vec_b)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class TopicClusteringProcessor(BaseProcessor):
    name = "topic_clustering"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._similarity_threshold: float = (config or {}).get("similarity_threshold", 0.25)
        self._min_cluster_size: int = (config or {}).get("min_cluster_size", 2)
        self._max_clusters: int = (config or {}).get("max_clusters", 20)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if len(items) < 2:
            for item in items:
                item.metadata["cluster_id"] = 0
                item.metadata["cluster_label"] = "uncategorized"
            return items

        # Build TF-IDF vectors
        vectors = build_tfidf_vectors(items)

        # Greedy agglomerative clustering
        clusters: list[list[int]] = [[i] for i in range(len(items))]

        changed = True
        while changed and len(clusters) > 1:
            changed = False
            best_sim = 0.0
            best_pair = (-1, -1)

            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    sim = self._cluster_similarity(vectors, clusters[i], clusters[j])
                    if sim > best_sim and sim >= self._similarity_threshold:
                        best_sim = sim
                        best_pair = (i, j)

            if best_pair[0] >= 0:
                i, j = best_pair
                clusters[i].extend(clusters[j])
                clusters.pop(j)
                changed = True

        # Assign cluster IDs and labels
        # Sort clusters by size (largest first)
        clusters.sort(key=len, reverse=True)

        # Only keep clusters with min_cluster_size items
        cluster_id = 0
        for cluster in clusters:
            if len(cluster) >= self._min_cluster_size and cluster_id < self._max_clusters:
                label = self._label_cluster(items, cluster)
                for idx in cluster:
                    items[idx].metadata["cluster_id"] = cluster_id
                    items[idx].metadata["cluster_label"] = label
                cluster_id += 1
            else:
                for idx in cluster:
                    items[idx].metadata["cluster_id"] = -1
                    items[idx].metadata["cluster_label"] = "uncategorized"

        self._logger.info(
            f"Topic clustering: {len(items)} items → {cluster_id} clusters",
            extra={"items": len(items), "clusters": cluster_id}
        )
        return items

    def _cluster_similarity(self, vectors: list[dict], cluster_a: list[int], cluster_b: list[int]) -> float:
        """Average pairwise similarity between two clusters."""
        total = 0.0
        count = 0
        for i in cluster_a:
            for j in cluster_b:
                total += cosine_similarity(vectors[i], vectors[j])
                count += 1
        return total / count if count > 0 else 0.0

    def _label_cluster(self, items: list[ProcessedItem], cluster: list[int]) -> str:
        """Generate a label for a cluster from its most common keywords."""
        all_keywords: list[str] = []
        for idx in cluster:
            all_keywords.extend(items[idx].keywords)

        if not all_keywords:
            # Fall back to common tokens in titles
            for idx in cluster:
                all_keywords.extend(t for t in tokenize(items[idx].title) if t not in STOP_WORDS)

        if not all_keywords:
            return "unknown"

        top = Counter(all_keywords).most_common(3)
        return " / ".join(kw for kw, _ in top)
