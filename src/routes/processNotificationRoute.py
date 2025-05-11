from fastapi import APIRouter
import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import numpy as np
from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field 
from db.mongo import tree_collection, notifications_collection
from notification.treeBuilder import remove_leaf
from services.emailService import send_email_notification
from notification.processDocument import chunk_text, batch_text_embeddings, find_best_leaf_greedy, any_chunk_relevant_llm

router = APIRouter()

class NotificationRequestModel(BaseModel):
    text: str
    similarity_threshold: float
    chunk_size: int

HIGH_SIM_AUTO_RELEVANT = 0.76
MAX_CHUNKS_FOR_LLM = 5

@router.post("/process", response_model=dict)
async def process_document_for_notifications(request: NotificationRequestModel):
    # 1. Load text & chunk
    full_text = request.text
    chunks = chunk_text(full_text, request.chunk_size)
    print(f"Chunks: {chunks}")
    if not chunks:
        return {"matches_found": 0, "emails_sent": 0}

    # 2. Embed
    chunk_embs = batch_text_embeddings(chunks)

    # 3. Fetch roots
    roots = list(tree_collection.find(
        {"parent": None, "summary_embedding": {"$exists": True}},
        {"_id": 1, "summary_embedding": 1, "children": 1}
    ))
    if not roots:
        return {"matches_found": 0, "emails_sent": 0}

    # 4. Match each chunk → best leaf
    raw_matches: List[Dict] = []
    for chunk, emb in zip(chunks, chunk_embs):
        leaf, sim = find_best_leaf_greedy(emb, roots, request.similarity_threshold)
        if leaf:
            raw_matches.append({
                "leaf_id": leaf["_id"], 
                "chunk": chunk,
                "similarity": sim,
            })

    # 5. Group by leaf
    leaf_to_matches: Dict[ObjectId, List[Dict]] = defaultdict(list)
    for m in raw_matches:
        leaf_to_matches[m["leaf_id"]].append(m)
    print(f"Leaf to matches: {leaf_to_matches}")
    emails_sent = 0

    # 6. Process matches
    for leaf_id, matches in leaf_to_matches.items():
        matches.sort(key=lambda x: x["similarity"], reverse=True)
        top_matches = matches[:MAX_CHUNKS_FOR_LLM]

        leaf_doc = tree_collection.find_one({"_id": leaf_id}, {"summary": 1, "requests": 1})
        if not leaf_doc:
            continue

        summary = leaf_doc["summary"]
        best_sim = top_matches[0]["similarity"]

        if best_sim >= HIGH_SIM_AUTO_RELEVANT:
            relevant = True
        elif best_sim >= request.similarity_threshold:
            context_chunks = [m["chunk"] for m in top_matches]
            relevant = any_chunk_relevant_llm(context_chunks, summary)
        else:
            relevant = False

        if not relevant:
            continue

        detail_lines = "\n".join(
            f"- {m['similarity']:.3f} | ...{m['chunk']}..." for m in top_matches
        )

        for req_id in leaf_doc.get("requests", []):
            notif = notifications_collection.find_one({"_id": req_id})
            if not notif or not (email := notif.get("email")):
                continue

            subject = f"Notification Update – match for request {req_id}"
            body = (
                f"Hello,\n\n"
                f"Leaf summary:\n{summary}\n\n"
                f"Best text matches:\n{detail_lines}\n\n"
                f"Original request:\n{notif.get('message','')}\n\n"
                f"Timestamp: {datetime.utcnow().isoformat()}Z\n\n"
                "Regards,\nNotification Team"
            )

            asyncio.create_task(send_email_notification(email, subject, body))          
            print(f"Sending email to {email}:\n{body}\n")
            emails_sent += 1

        #remove_leaf(leaf_id)

    return {
        "matches_found": len(leaf_to_matches),
        "emails_sent": emails_sent,
    }

