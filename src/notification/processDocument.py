import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import numpy as np
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI
from db.mongo import (
    tree_collection,
    notifications_collection
)
from notification.embeddings import (
    getEmbedding,          
    cosine_similarity,
)
from dotenv import load_dotenv
import os

load_dotenv()  # reads .env into os.environ

apiKey = os.getenv("OPENAI_API_KEY")
if not apiKey:
    raise RuntimeError("OPENAI_API_KEY not set")


client = OpenAI(api_key=apiKey)

def chunk_text(text: str, chunk_size: int, overlap_ratio: float = 0.25) -> List[str]:
    """
    Sliding‑window chunking with overlap to preserve context.
    Overlap = int(chunk_size * overlap_ratio)  words.
    """
    words = text.split()
    if not words:
        return []

    overlap = max(1, int(chunk_size * overlap_ratio))
    step = chunk_size - overlap
    chunks = [
        " ".join(words[i : i + chunk_size])
        for i in range(0, len(words), step)
    ]
    return chunks


def batch_text_embeddings(texts: List[str], batch: int = 32) -> List[np.ndarray]:
    """
    Simple batching wrapper around cached `get_text_embedding`.
    Breaks the list into <=batch chunks to avoid GPU under‑utilisation.
    """
    out: List[np.ndarray] = []
    for i in range(0, len(texts), batch):
        out.extend(np.asarray(getEmbedding(t)) for t in texts[i : i + batch])
    return out


def find_best_leaf_greedy(
    chunk_emb: np.ndarray,
    roots: List[Dict],
    threshold: float,
) -> Tuple[Optional[Dict], float]:
    best_leaf, best_sim = None, -1.0
    for root in roots:
        leaf, sim = greedy_descent_to_leaf(root, chunk_emb)
        if leaf.get("requests"):
            first_req = notifications_collection.find_one({"_id": leaf["requests"][0]})
            if first_req and "embedding" in first_req:
                sim = 0.5 * sim + 0.5 * cosine_similarity(chunk_emb, first_req["embedding"])
        if sim >= threshold and sim > best_sim:
            best_leaf, best_sim = leaf, sim
    return best_leaf, best_sim


def greedy_descent_to_leaf(node: Dict, chunk_emb: np.ndarray) -> Tuple[Dict, float]:
    current = node
    while current.get("children"):
        child_docs = [tree_collection.find_one({"_id": cid}) for cid in current["children"]]
        current = max(child_docs, key=lambda c: cosine_similarity(chunk_emb, c["summary_embedding"]))
    return current, cosine_similarity(chunk_emb, current["summary_embedding"])

def any_chunk_relevant_llm(chunks: List[str], leaf_summary: str) -> bool:
    joined = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(chunks))
    prompt = f"""
    At least one of the CHUNKS below should trigger the following notification
    request summary.  If yes, answer YES.  Otherwise answer NO.

    SUMMARY:
    {leaf_summary}

    CHUNKS:
    {joined}
    
    Should a notification be sent based on the CHUNKS?
    ONE‑WORD (YES / NO):
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.12
    )
    return response.choices[0].message.content.strip().upper() == "YES"

