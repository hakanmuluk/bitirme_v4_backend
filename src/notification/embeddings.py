from typing import List
import numpy as np  
import requests
from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()  # reads .env into os.environ

apiKey = os.getenv("OPENAI_API_KEY")
if not apiKey:
    raise RuntimeError("OPENAI_API_KEY not set")


client = OpenAI(api_key=apiKey)


def getEmbedding(text):
    url = 'https://api.jina.ai/v1/embeddings'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer jina_533ccea1ab01464e8a9176ebffc40348O2fcbLzn83ixt0nHl5NFoh_1ICAK'
    }
    data = {
        "model": "jina-embeddings-v3",
        "task": "retrieval.query",
        "input": [
            f"{text}",

        ]
    }

    response = requests.post(url, headers=headers, json=data)
    res_json = response.json()
    embedding_array = res_json["data"][0]["embedding"]

    return embedding_array

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Computes the cosine similarity between two vectors.
    """
    v1 = np.array(vec1)
    v2 = np.array(vec2)
    dot_product = np.dot(v1, v2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)

def extract_triplet(text: str) -> str:
    """
    Extracts the main (subject, relation, object) or (entity, action, entity)
    triplet from the user's request using OpenAI's GPT model.
    """    
    prompt = f"""
    Extract the core (subject, relation, object) or (entity, action, entity) triplet from the given notification request.

    Instructions:
    - IGNORE phrases such as 'notify me', 'tell me', 'let me know', 'inform me', or similar instruction-like expressions.
    - OMIT generic or irrelevant words, keeping only essential information.
    - The output *MUST* strictly follow this format: subject relation object


    Examples:
        Input: \"Notify me when Koç Holding increases investment\"
        Output: Koç Holding increases investment

        Input: \"Tell me when Turkcell increases number of base stations\"
        Output: Turkcell increases number of base stations

        Input: \"Let me know if Koç Holding and Sabancı work together\"
        Output: Koç Holding works together with Sabancı

        Input: \"Tell me when Fenerbahçe wins a match\"
        Output: Fenerbahçe wins match

        Input: \"Notify me if Apple releases a new iPhone model\"
        Output: Apple releases new iPhone model

        Input: \"Let me know when Türkiye Merkez Bankası raises interest rates\"
        Output: Türkiye Merkez Bankası raises interest rates

    Now extract the main triplet (core idea) from this request:
    \"{text}\"
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0
    )
    return response.choices[0].message.content.strip()

def getTextTripletEmbedding(input_text: str, alpha: float = 0.5) -> List[float]:
    """
    1) Extract the triplet from 'input_text'.
    2) Embed the full 'input_text' and the 'triplet'.
    3) Combine them (weighted average) into a final vector.
    """
    extract_meaning = extract_triplet(input_text)
    text_emb = getEmbedding(input_text) if input_text else [0] * 1024
    triplet_emb = getEmbedding(extract_meaning) if extract_meaning else [0] * 1024

    v_text = np.array(text_emb)
    v_extract = np.array(triplet_emb)
    final_vec = alpha * v_text + (1 - alpha) * v_extract

    # Normalize final vector for consistency
    norm = np.linalg.norm(final_vec)
    if norm == 0:
        return final_vec.tolist()
    return (final_vec / norm).tolist()
