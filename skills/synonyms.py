"""
AI/ML skill synonym map. Intentionally small.
Canonical form → list of variants.
"""

from __future__ import annotations

SKILL_SYNONYMS: dict[str, list[str]] = {
    "llm": ["large language model", "large language models", "llms"],
    "nlp": ["natural language processing"],
    "computer vision": ["cv", "image recognition"],
    "reinforcement learning": ["rl"],
    "deep learning": ["dl", "neural networks", "neural network"],
    "mlops": ["ml operations", "ml ops", "machine learning operations", "ml infra"],
    "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    "generative ai": ["genai", "gen ai"],
    "pytorch": ["torch"],
    "tensorflow": ["tf"],
    "transformers": ["transformer architecture", "attention mechanism"],
    "fine-tuning": ["fine tuning", "finetuning", "model fine-tuning"],
    "langchain": ["lang chain"],
    "hugging face": ["huggingface", "hf"],
    "vector database": [
        "vector db",
        "vector store",
        "pinecone",
        "weaviate",
        "chromadb",
        "qdrant",
    ],
}


def normalise_skill(skill: str) -> str:
    """Return the canonical skill name for a raw token."""
    cleaned = skill.lower().strip()
    for canonical, variants in SKILL_SYNONYMS.items():
        if cleaned == canonical or cleaned in variants:
            return canonical
    return cleaned
