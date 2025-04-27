from typing import Optional, Callable
from typing_extensions import TypedDict
from langgraph.graph import StateGraph
from concurrent.futures import ThreadPoolExecutor
from neo4j import GraphDatabase
import asyncio
from .prompts import (
    rephrase_For_Followup,
    translateEnglish,
    translateTurkish,
    relevancy_Check,
    generate_answer,
    checkSupported,
    decomposeToSubqueries,
    simpleDecompose
)
from .retrieval import (
    retrieveForSingleHop,
    retrieveForSingleHopWithoutFilter
)
import os
from dotenv import load_dotenv

load_dotenv()  # reads .env into os.environ

uri      = os.getenv("NEO4J_URI")
username = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")

if not uri or not username or not password:
    raise RuntimeError("One of NEO4J_URI, NEO4J_USER or NEO4J_PASSWORD is not set")

driver = GraphDatabase.driver(uri, auth=(username, password))


class GraphState(TypedDict):
    userQuery: str
    rephrasedUserQuery: str
    englishUserQuery: str
    questionType: str
    retrievedDocs: list[str]
    relevantDocs: list[str]
    pastMessages: list[str]
    answerGenerated: str
    isAnswerSupported: bool
    turkishAnswer: str
    isDecomposed: bool
    decomposedQueries: list[str]
    bridgeTemplate: Optional[str]
    bridgeResolved: bool
    answerNotFound: bool
    comeFrom: str
    finalAnswer: str

# ---------------- Node Functions ----------------
def rephraseForFollowup(state: GraphState) -> GraphState:
    if len(state["pastMessages"]) > 0:
        state["rephrasedUserQuery"] = rephrase_For_Followup(
            state["userQuery"], state["pastMessages"]
        )
    else:
        state["rephrasedUserQuery"] = state["userQuery"]
    return state

def translateToEnglish(state: GraphState) -> GraphState:
    state["englishUserQuery"] = translateEnglish(state["rephrasedUserQuery"])
    return state

def retrieval(state: GraphState) -> GraphState:
    if not state["isDecomposed"]:
        docs = retrieveForSingleHop(state["englishUserQuery"], driver)
        if len(docs) == 0:
            docs = retrieveForSingleHopWithoutFilter(state["englishUserQuery"], driver)
        state["retrievedDocs"] = docs
    else:
        for query in state["decomposedQueries"]:
            docs = retrieveForSingleHop(query, driver)
            ####
            if len(docs) == 0:
                docs = retrieveForSingleHopWithoutFilter(query, driver) 
            ###
            for d in docs:
                if d not in state["retrievedDocs"]:
                    state["retrievedDocs"].append(d)

    state["comeFrom"] = "retrieval"
    return state

def relevancyCheck(state: GraphState) -> GraphState:
    docs = state["retrievedDocs"]
    query = state["englishUserQuery"]
    valid = []
    with ThreadPoolExecutor() as exe:
        futures = {exe.submit(relevancy_Check, d, state["decomposedQueries"], state["englishUserQuery"], state["isDecomposed"]): d for d in docs}
        for fut in futures:
            d = futures[fut]
            try:
                if fut.result(): valid.append(d)
            except:
                pass
    state["relevantDocs"] = valid
    state["comeFrom"] = "relCheck"
    return state

def generateAnswer(state: GraphState) -> GraphState:
    state["answerGenerated"] = generate_answer(
        state["relevantDocs"], state["englishUserQuery"]
    )
    return state

def supportednessCheck(state: GraphState) -> GraphState:
    ok = checkSupported(
        state["relevantDocs"], state["englishUserQuery"], state["answerGenerated"]
    )
    state["isAnswerSupported"] = ok
    if not ok:
        new_ans = generate_answer(
            state["relevantDocs"], state["englishUserQuery"]
        )
        state["answerGenerated"] = new_ans
        state["isAnswerSupported"] = checkSupported(
            state["relevantDocs"], state["englishUserQuery"], new_ans
        )
    state["comeFrom"] = "supCheck"
    return state


def translateToTurkish(state: GraphState) -> GraphState:
    state["turkishAnswer"] = translateTurkish(state["answerGenerated"])
    return state

def resolveBridge(state: GraphState) -> GraphState:
    if state["bridgeResolved"] or state["questionType"] != "bridging":
        return state                              

    interim = generate_answer(
        state["retrievedDocs"], state["decomposedQueries"][0]
    )

    q2 = state["bridgeTemplate"].replace("{answer_to_q1}", interim)
    state["decomposedQueries"][1] = q2

    docs = retrieveForSingleHop(q2, driver) or \
           retrieveForSingleHopWithoutFilter(q2, driver)
    state.setdefault("retrievedDocs", []).extend(
        [d for d in docs if d not in state["retrievedDocs"]]
    )

    state["bridgeResolved"] = True
    state["comeFrom"] = "resolveBridge"
    return state


def decompose(state: GraphState) -> GraphState:
    subs = simpleDecompose(state["englishUserQuery"]) 
    state["decomposedQueries"] = subs
    state["isDecomposed"] = True
    return state


def classifyDecomposeQuestion(state: GraphState) -> GraphState:
    info = decomposeToSubqueries(state["englishUserQuery"])
    state["questionType"]      = info["type"]
    state["decomposedQueries"] = info["subquestions"]
    state["bridgeTemplate"]    = info["bridge_template"]
    state["isDecomposed"]      = info["type"] != "single"
    state["bridgeResolved"]    = False
    return state

def router(state: GraphState) -> list[str]:

    if state["questionType"] == "bridging" and not state["bridgeResolved"] and state["comeFrom"] == "retrieval":
        return ["resolveBridge"]

    if state["questionType"] != "bridging" and state["comeFrom"] == "retrieval":
        return ["relevancyCheck"]

    if state["isDecomposed"] and not state["relevantDocs"] and state["comeFrom"] == "relCheck":
        state["answerNotFound"] = True
        return ["end"]
    
    if state["isDecomposed"] and not state["isAnswerSupported"] and state["comeFrom"] == "supCheck":
        state["answerNotFound"] = True
        return ["end"]
    
    if not state["relevantDocs"] and state["comeFrom"] == "relCheck":
        return ["decompose"]
    
    if not state["isAnswerSupported"] and state["comeFrom"] == "supCheck":
        return ["decompose"]
    
    if state["comeFrom"] == "relCheck":
        return ["generateAnswer"]
    
    return ["translateToTurkish"]

def end(state: GraphState) -> GraphState:
    if state["answerNotFound"]:
        state["finalAnswer"] = "Bilmiyorum."
    else:
        state["finalAnswer"] = state["turkishAnswer"]
    return state

# Adjacency & runner setup
ADJACENCY = {
    "rephraseForFollowup": ["translateToEnglish"],
    "translateToEnglish":  ["classifyDecomposeQuestion"],
    "classifyDecomposeQuestion":    ["retrieval"],
    "retrieval":           router,
    "relevancyCheck":      router,
    "resolveBridge":       ["relevancyCheck"],
    "generateAnswer":      ["supportednessCheck"],
    "supportednessCheck":  router,
    "translateToTurkish":  ["end"],
    "decompose":           ["retrieval"],
    "end":                 []
}

NODE_FUNCTIONS = {
    k: globals()[k] for k in (
        "rephraseForFollowup", "translateToEnglish",
        "classifyDecomposeQuestion", "resolveBridge", "retrieval",
        "relevancyCheck", "generateAnswer", "supportednessCheck",
        "translateToTurkish", "decompose", "end"
    )
}
ENTRY_POINT = "rephraseForFollowup"
FINISH_NODE = "end"

def get_next_nodes(current_node: str, state: GraphState) -> list[str]:
    info = ADJACENCY[current_node]
    if callable(info):
        return info(state)
    return info

async def run_pipeline_step_by_step(state: GraphState):
    """
    Async generator: runs each node in a ThreadPool, yields (node_name, state).
    """
    current_node = ENTRY_POINT
    while True:

        func = NODE_FUNCTIONS[current_node]
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(None, func, state)
        yield current_node, state
        if current_node == FINISH_NODE:
            break
        nexts = get_next_nodes(current_node, state)
        current_node = nexts[0]
        
async def run_pipeline_and_get_answer(state: GraphState) -> str:
    """
    Runs the entire pipeline from ENTRY_POINT to FINISH_NODE,
    mutating `state` in-place, and returns state["finalAnswer"].
    """
    loop = asyncio.get_running_loop()
    current = ENTRY_POINT

    while True:
        func = NODE_FUNCTIONS[current]
        # run each node function in a thread so that blocking I/O
        # (Neo4j calls, HTTP, etc.) doesn’t block the event loop
        state = await loop.run_in_executor(None, func, state)

        if current == FINISH_NODE:
            return state["finalAnswer"]

        next_nodes = get_next_nodes(current, state)
        current = next_nodes[0]
