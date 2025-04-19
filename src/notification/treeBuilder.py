from __future__ import annotations

import os
import statistics as stats
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, List, Optional, Tuple, TypedDict

from bson import ObjectId
from dotenv import load_dotenv
from openai import OpenAI
from pymongo.client_session import ClientSession
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from notification.embeddings import (
    cosine_similarity,
    getEmbedding,
)
from db.mongo import tree_collection, notifications_collection
from dotenv import load_dotenv

load_dotenv()  # reads .env into os.environ

apiKey = os.getenv("OPENAI_API_KEY")
if not apiKey:
    raise RuntimeError("OPENAI_API_KEY not set")


client = OpenAI(api_key=apiKey)

ROOT_STATS_ID = "root_similarity_stats"         

class NodeDoc(TypedDict, total=False):
    _id: ObjectId
    summary: str
    summary_embedding: List[float]
    parent: Optional[ObjectId]
    children: List[ObjectId]
    requests: List[ObjectId]
    subtree_size: int          # leaf‑count under this node
    created_at: datetime
    updated_at: datetime
    dirty: bool                # for summary refresh


def embed(text: str):
    return getEmbedding(text)


def cosine(a: List[float], b: List[float]):
    return cosine_similarity(a, b)


def summarise(texts: List[str]):

    prompt = (
        "Summarise the following content into ONE concise, self‑contained summary. **OMIT** and **IGNORE** any expression that might corrupt the meaning of the summary such as: 'Notify me', 'Please notify me', 'Tell me', 'Let me know' or similar.\n\n"
        "Output ONLY the summary:\n\n" + "\n".join(texts[:50])  # safety‑clip
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    summary = resp.choices[0].message.content.strip()
    return summary, embed(summary)


# ──────────────────────────────────────────────────────────── Mongo helpers

def load_node(
    nid: ObjectId,
    *,
    col: Collection = tree_collection,
    session: ClientSession | None = None
) -> NodeDoc:
    doc = col.find_one({"_id": nid}, session=session)
    if not doc:
        raise KeyError(f"Node {nid} disappeared")
    return NodeDoc(doc)  # type: ignore[arg-type]


def save_node(doc: NodeDoc, *, col: Collection = tree_collection, session=None):
    col.replace_one({"_id": doc["_id"]}, doc, session=session)


def dirty_upwards(start: ObjectId, *, col: Collection = tree_collection, session=None):
    """Mark start .. root as dirty."""
    nid = start
    while nid:
        col.update_one({"_id": nid}, {"$set": {"dirty": True}}, session=session)
        nid = col.find_one({"_id": nid}, {"parent": 1}, session=session)["parent"]


def refresh_dirty_nodes(*, col: Collection = tree_collection):
    """Re‑summarise every node whose dirty flag is True, bottom‑up."""
    dirty_nodes = list(col.find({"dirty": True}))
    # Sort by depth (deepest first) so children are refreshed before parents.
    dirty_nodes.sort(key=lambda d: d.get("parent") is None)  # leaves first
    for doc in dirty_nodes:
        if doc["children"]:
            children = [load_node(cid, col=col) for cid in doc["children"]]
            texts = [c["summary"] for c in children]
            summary, emb = summarise(texts)
            col.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "summary": summary,
                        "summary_embedding": emb,
                        "updated_at": datetime.now(timezone.utc),
                        "dirty": False,
                    }
                },
            )
        else:
            col.update_one({"_id": doc["_id"]}, {"$set": {"dirty": False}})


# ──────────────────────────────────────────────────────────── core algorithm
def centroid_shift(child: NodeDoc, new_emb: List[float]) -> float:
    """Approximate Δ when adding one leaf to child's subtree centroid."""
    n = child.get("subtree_size", 1)
    curr = child["summary_embedding"]
    new_centroid = [(n * c + e) / (n + 1) for c, e in zip(curr, new_emb)]
    return cosine(curr, new_centroid)

def create_leaf(
    request_id: ObjectId,
    text: str,
    emb: List[float],
    parent: Optional[ObjectId],
    *,
    session: ClientSession,
) -> ObjectId:
    summary, summary_emb = summarise([text])
    leaf: NodeDoc = {
        "summary": summary,
        "summary_embedding": summary_emb,
        "parent": parent,
        "children": [],
        "requests": [request_id],
        "subtree_size": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "dirty": False,
    }
    return tree_collection.insert_one(leaf, session=session).inserted_id


def increment_subtree_sizes(
    start_node_id: ObjectId,
    *,
    col: Collection = tree_collection,
    session: ClientSession,
) -> None:
    """
    Walk up from start_node_id, incrementing subtree_size by 1 at each ancestor.
    """
    nid = start_node_id
    while nid is not None:
        col.update_one({"_id": nid}, {"$inc": {"subtree_size": 1}}, session=session)
        parent_doc = col.find_one({"_id": nid}, {"parent": 1}, session=session)
        nid = parent_doc.get("parent") if parent_doc else None

def descend_and_insert(
    node: NodeDoc,
    request_id: ObjectId,
    text: str,
    emb: List[float],
    *,
    internal_thr: float,
    leaf_merge_thr: float,
    k: int,
    session: ClientSession,
):
    col = tree_collection

    # ───────────────────────────── leaf ─────────────────────────────
    if not node["children"]:
        sim = cosine(emb, node["summary_embedding"])
        print(f"Leaf in descending {node['summary']}, sim: {sim}")
        if sim >= leaf_merge_thr:
            # merge into existing leaf (no subtree_size change)
            col.update_one(
                {"_id": node["_id"]},
                {
                    "$push": {"requests": request_id},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
                session=session,
            )
            new_sum, new_emb = summarise([node["summary"], text])
            col.update_one(
                {"_id": node["_id"]},
                {
                    "$set": {
                        "summary": new_sum,
                        "summary_embedding": new_emb,
                        "dirty": True,
                    }
                },
                session=session,
            )
            dirty_upwards(node["_id"], col=col, session=session)
            return

        # split leaf → internal + 2 leaves
        parent_id = node["parent"]
        new_leaf_id = create_leaf(
            request_id, text, emb, parent=None, session=session
        )
        # load both summaries inside the same txn
        old_sum = node["summary"]
        new_sum_text = load_node(new_leaf_id, col=col, session=session)["summary"]

        internal_sum, internal_emb = summarise([old_sum, new_sum_text])
        internal_id = col.insert_one(
            {
                "summary": internal_sum,
                "summary_embedding": internal_emb,
                "parent": parent_id,
                "children": [node["_id"], new_leaf_id],
                "requests": [],
                "subtree_size": 2,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "dirty": False,
            },
            session=session,
        ).inserted_id

        # re‑wire
        col.update_one(
            {"_id": node["_id"]},
            {"$set": {"parent": internal_id}},
            session=session,
        )
        col.update_one(
            {"_id": new_leaf_id},
            {"$set": {"parent": internal_id}},
            session=session,
        )

        if parent_id is not None:
            col.update_one(
                {"_id": parent_id},
                {"$pull": {"children": node["_id"]}},
                session=session,
            )
            col.update_one(
                {"_id": parent_id},
                {"$push": {"children": internal_id}},
                session=session,
            )
            increment_subtree_sizes(parent_id, col=col, session=session)

        dirty_upwards(internal_id, col=col, session=session)
        return

    # ─────────────────────────── internal ───────────────────────────
    children = [load_node(cid, col=col, session=session) for cid in node["children"]]
    sims = [cosine(emb, c["summary_embedding"]) for c in children]
    best_child = children[sims.index(max(sims))]
    best_sim = max(sims)
    print(f"Best child while descending: {best_child['summary']}, sim: {best_sim}")
    if best_sim >= internal_thr:
        descend_and_insert(
            best_child,
            request_id,
            text,
            emb,
            internal_thr=internal_thr,
            leaf_merge_thr=leaf_merge_thr,
            k=k,
            session=session,
        )
        return

    # no child similar enough & room for new leaf
    if len(node["children"]) < k:
        new_leaf_id = create_leaf(
            request_id, text, emb, parent=node["_id"], session=session
        )
        col.update_one(
            {"_id": node["_id"]},
            {"$push": {"children": new_leaf_id}},
            session=session,
        )
        increment_subtree_sizes(node["_id"], col=col, session=session)
        dirty_upwards(new_leaf_id, col=col, session=session)
        return

    # else: split worst child under this internal
    worst_child = min(children, key=lambda c: centroid_shift(c, emb))
    new_leaf_id = create_leaf(request_id, text, emb, parent=None, session=session)
    wc_sum = worst_child["summary"]
    new_sum_text = load_node(new_leaf_id, col=col, session=session)["summary"]

    inter_sum, inter_emb = summarise([wc_sum, new_sum_text])
    inter_id = col.insert_one(
        {
            "summary": inter_sum,
            "summary_embedding": inter_emb,
            "parent": node["_id"],
            "children": [worst_child["_id"], new_leaf_id],
            "requests": [],
            "subtree_size": worst_child["subtree_size"] + 1,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "dirty": False,
        },
        session=session,
    ).inserted_id

    # re‑wire
    col.update_one(
        {"_id": worst_child["_id"]},
        {"$set": {"parent": inter_id}},
        session=session,
    )
    col.update_one(
        {"_id": new_leaf_id},
        {"$set": {"parent": inter_id}},
        session=session,
    )
    # 1) remove the worst child
    col.update_one(
        {"_id": node["_id"]},
        {"$pull": {"children": worst_child["_id"]}},
        session=session,
    )

    # 2) add the new internal node
    col.update_one(
        {"_id": node["_id"]},
        {"$push": {"children": inter_id}},
        session=session,
    )
    increment_subtree_sizes(node["_id"], col=col, session=session)
    dirty_upwards(inter_id, col=col, session=session)


def insert_notification_into_forest(
    request_id: ObjectId,
    text: str,
    *,
    internal_threshold_base: float = 0.59,
    k: int = 2,
    max_trees: int = 5,
) -> ObjectId:
    """
    Atomically insert `request_id` with `text` into the forest.
    Returns the _id of the leaf that now stores the request.
    """
    emb = embed(text)

    with tree_collection.database.client.start_session() as sess:
        with sess.start_transaction():

            roots = list(tree_collection.find({"parent": None, "summary_embedding": {"$exists": True}}, session=sess))

            # 0. empty forest → create first tree
            if not roots:
                leaf_id = create_leaf(request_id, text, emb,
                                      parent=None, session=sess)
                sess.commit_transaction()
                return leaf_id

            # 1. choose best root
            root_sims = [cosine(emb, r["summary_embedding"]) for r in roots]
            best_sim  = max(root_sims)
            best_root = roots[root_sims.index(best_sim)]
            print(f"Best root: {best_root['_id']}, sim: {best_sim}")
           

            root_thr, leaf_merge_thr = 0.52, 0.73
            internal_thr = internal_threshold_base

            # 1‑a. descend/merge inside best_root
            if best_sim >= root_thr:
                descend_and_insert(best_root, request_id, text, emb,
                                    internal_thr=internal_thr,
                                    leaf_merge_thr=leaf_merge_thr,
                                    k=k,
                                    session=sess)
        
                leaf_doc = tree_collection.find_one(
                    {"requests": request_id}, session=sess, projection={"_id": 1}
                )
                leaf_id: ObjectId = leaf_doc["_id"] if leaf_doc else best_root["_id"]
                sess.commit_transaction()

            # 1‑b. forest has room → new root‑level leaf
            elif len(roots) < max_trees:
                leaf_id = create_leaf(request_id, text, emb,
                                      parent=None, session=sess)
                sess.commit_transaction()

            # 1‑c. forest full & no good root → wrap best_root + new_leaf
            else:
                new_leaf_id = create_leaf(request_id, text, emb,
                                          parent=None, session=sess)

                combo_sum, combo_emb = summarise(
                    [best_root["summary"],
                     load_node(new_leaf_id, session=sess)["summary"]]
                )
                new_root_id = tree_collection.insert_one(
                    {
                        "summary":           combo_sum,
                        "summary_embedding": combo_emb,
                        "parent":            None,
                        "children":          [best_root["_id"], new_leaf_id],
                        "requests":          [],
                        "subtree_size":      best_root["subtree_size"] + 1,
                        "created_at":        datetime.now(timezone.utc),
                        "updated_at":        datetime.now(timezone.utc),
                        "dirty":             False,
                    },
                    session=sess,
                ).inserted_id

                tree_collection.update_one(
                    {"_id": best_root["_id"]},
                    {"$set": {"parent": new_root_id}},
                    session=sess,
                )
                tree_collection.update_one(
                    {"_id": new_leaf_id},
                    {"$set": {"parent": new_root_id}},
                    session=sess,
                )
                dirty_upwards(new_root_id, col=tree_collection, session=sess)

                leaf_id = new_leaf_id
                sess.commit_transaction()

    # 2. refresh dirty summaries outside the transaction
    refresh_dirty_nodes()
    return leaf_id

def decrement_subtree_sizes(
    start_node_id: ObjectId,
    *,
    col: Collection = tree_collection,
    session: Optional[ClientSession] = None
) -> None:
    """
    Walk up from start_node_id, decrementing subtree_size by 1 at each ancestor.
    """
    nid = start_node_id
    while nid is not None:
        col.update_one(
            {"_id": nid},
            {"$inc": {"subtree_size": -1}},
            session=session,
        )
        parent = col.find_one(
            {"_id": nid},
            {"parent": 1},
            session=session,
        )
        nid = parent.get("parent") if parent else None

def remove_leaf(
    leaf_id: ObjectId,
    *,
    col: Collection = tree_collection,
    session: Optional[ClientSession] = None
) -> None:
    # 1. Load the leaf + its subscriptions
    leaf = col.find_one({"_id": leaf_id}, session=session)
    if not leaf or leaf.get("children"):
        return

    # 1.b: grab the list of request‐IDs so we can delete them too
    req_ids = leaf.get("requests", [])

    # 2. First delete the notifications themselves:
    if req_ids:
        notifications_collection.delete_many(
            {"_id": {"$in": req_ids}},
            session=session,
        )

    # 3. Now delete the tree leaf node
    col.delete_one({"_id": leaf_id}, session=session)

    # 4. If it had a parent, unlink and rebalance
    parent_id = leaf.get("parent")
    if parent_id:
        decrement_subtree_sizes(parent_id, col=col, session=session)
        col.update_one(
            {"_id": parent_id},
            {"$pull": {"children": leaf_id}},
            session=session,
        )

        parent = load_node(parent_id, col=col, session=session)
        children = parent.get("children", [])
        if len(children) == 1:
            sole, grand = children[0], parent.get("parent")
            # reparent sole to grand…
            col.update_one({"_id": sole}, {"$set": {"parent": grand}}, session=session)
            if grand is not None:
                col.update_one({"_id": grand}, {"$pull": {"children": parent_id}}, session=session)
                col.update_one({"_id": grand}, {"$push": {"children": sole}}, session=session)
            # remove the empty internal
            col.delete_one({"_id": parent_id}, session=session)
            dirty_upwards(sole, col=col, session=session)
        else:
            dirty_upwards(parent_id, col=col, session=session)

    # 5. Finally, refresh any summaries that got flagged dirty
    refresh_dirty_nodes()


