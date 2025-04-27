from fastapi import APIRouter, Body
from typing import List, Optional

from rag.single_hop import GraphState, run_pipeline_and_get_answer

chat_router = APIRouter()

@chat_router.post("/")
async def chat_endpoint(
    user_query: str = Body(..., embed=True),
):
    """
    Expects JSON body:
    {
      "user_query": "...",
      "past_messages": ["...","..."]    # optional, default=[]
    }
    """


    initial_state: GraphState = {
        "userQuery": user_query,
        "rephrasedUserQuery": "",
        "englishUserQuery": "",
        "retrievedDocs": [],
        "relevantDocs": [],
        "pastMessages": [],
        "answerGenerated": "",
        "isAnswerSupported": False,
        "turkishAnswer": "",
        "isDecomposed": False,
        "decomposedQueries": [],
        "answerNotFound": False,
        "comeFrom": "",
        "finalAnswer": ""
    } """

    # 2) Run the pipeline and get back the finalAnswer
    answer = await run_pipeline_and_get_answer(initial_state)

    # 3) Return it just like any other JSON API
    return {"answer": answer}
