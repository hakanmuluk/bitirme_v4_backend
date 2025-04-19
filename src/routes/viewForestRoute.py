from fastapi import HTTPException, APIRouter, Query
from bson import ObjectId
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import asyncio
from typing import Dict, List            # ← populates os.environ from .env
from db.mongo import users_collection, notifications_collection, tree_collection, stats_collection
from notification.embeddings import getEmbedding

router = APIRouter()
def _build_subtree(
    node_id: ObjectId,
    max_depth: int,
    include_requests: bool,
    _depth: int = 1,
) -> dict:
    # existing implementation
    node = tree_collection.find_one({"_id": node_id})
    if not node:
        raise KeyError(f"Node {node_id} not found")

    view = {
        "id": str(node["_id"]),
        "summary": node.get("summary", ""),
        "created_at": node.get("created_at", datetime.min),
        "updated_at": node.get("updated_at", datetime.min),
        "num_requests": len(node.get("requests", [])),
        "is_leaf": not node.get("children"),
    }
    if include_requests and node.get("requests"):
        view["requests"] = [str(rid) for rid in node["requests"]]

    if node.get("children") and _depth < max_depth:
        view["children"] = [
            _build_subtree(cid, max_depth, include_requests, _depth + 1)
            for cid in node["children"]
        ]
    elif node.get("children"):
        view["children_truncated"] = len(node["children"])

    return view

@router.get("/view", response_model=dict)
async def view_forest(
    depth: int = Query(
        3,
        ge=1,
        le=10,
        description="How many levels below the root to include"
    ),
    include_requests: bool = Query(
        False,
        description="If True, include notification IDs in each leaf"
    ),
):
    """
    Returns the forest as nested JSON, excluding the root-stats document.
    """
    def _work() -> list[dict]:
        # Exclude the ROOT_STATS singleton from roots
        roots = list(tree_collection.find({
            "parent": None
        }))
        return [
            _build_subtree(root["_id"], depth, include_requests)
            for root in roots
        ]

    try:
        forest_view = await asyncio.to_thread(_work)
    except KeyError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "root_count": len(forest_view),
        "max_depth": depth,
        "forest": forest_view,
    }