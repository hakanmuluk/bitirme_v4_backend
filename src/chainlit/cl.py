import chainlit as cl
import logging
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs
from rag.single_hop import run_pipeline_step_by_step, GraphState
import asyncio
from notification.helpers import classify, post_notification 
# Logger for header auth
logger = logging.getLogger("header_auth")
logger.setLevel(logging.INFO)

@cl.header_auth_callback
def header_auth_callback(headers: Dict) -> Optional[cl.User]:
    logger.info("HEADER_AUTH_CALLBACK triggered!")
    logger.info(f"Headers received: {headers}")
    
    # Check for the header "x-user-id".
    user_mail = headers.get("x-user-id")
    
    if not user_mail:
        # Fallback: try to extract from cookie.
        cookies = headers.get("cookie", "")
        for cookie in cookies.split(";"):
            if "x-user-id=" in cookie:
                user_mail = cookie.split("=", 1)[1].strip()
                break
    
    if not user_mail:
        logger.info("No user_mail found in headers or cookies.")
        return None
    
    user_mail = user_mail.strip('"')
    logger.info(f"Authenticated user_id: {user_mail}")
    return cl.User(identifier=user_mail, metadata={"provider": "header"})

@cl.on_chat_start
async def on_chat_start():
    user = cl.user_session.get("user")
    user_email = user.identifier if user else "Guest"
    cl.user_session.set("user_email", user_email)
    return

@cl.on_chat_resume
async def on_chat_resume():
    return

""" @cl.on_message
async def on_message(message):
    
    logger.info("🚀 New user message: %s", message.content)

    # 1) Build the initial graph state
    state: GraphState = {
        "userQuery": message.content,
        "rephrasedUserQuery": "",
        "englishUserQuery": "",
        "retrievedDocs": [],
        "relevantDocs": [],
        "pastMessages": cl.chat_context.to_openai()[-5:],
        "answerGenerated": "",
        "isAnswerSupported": False,
        "turkishAnswer": "",
        "isDecomposed": False,
        "decomposedQueries": [],
        "answerNotFound": False,
        "comeFrom": "",
        "finalAnswer": ""
    }

    try:
        # 2) Stream each pipeline node as a Chainlit Step
        async for node_name, updated_state in run_pipeline_step_by_step(state):
            async with cl.Step(name=node_name) as step:
               
            
                if node_name == "rephraseForFollowup":
                    step.input = f"User query: {updated_state['userQuery']}"
                    step.output = f"Rephrased user query: {updated_state['rephrasedUserQuery']}"

                elif node_name == "translateToEnglish":
                    step.input = f"Before translation: {updated_state['rephrasedUserQuery']}"
                    step.output = f"After translation: {updated_state['englishUserQuery']}"
                elif node_name == "retrieval":
                    inp = "Retrieved Documents:\n\n"
                    for i, doc in enumerate(updated_state['retrievedDocs']):
                        inp += f"Document {i+1})\n{doc}\n\n"
                    step.input = inp
                   
                    step.output = "Retrieval is done."
                elif node_name == "relevancyCheck":
                    inp = "Relevant Documents:\n\n"
                    for i, doc in enumerate(updated_state['relevantDocs']):
                        inp += f"Document {i+1})\n{doc}\n\n"
                    step.input = inp
                    step.output = "Relevancy check is done."
                elif node_name == "generateAnswer":
                    step.output = f"Generated answer: {updated_state['answerGenerated']}"
                elif node_name == "supportednessCheck":
                    step.output = f"Answer supported: {updated_state['isAnswerSupported']}"
                elif node_name == "translateToTurkish":
                    step.input = f"Answer before translation: {updated_state['answerGenerated']}"
                    step.output = f"Translated answer: {updated_state['turkishAnswer']}"
                elif node_name == "decompose":
                    inp = "Generated subqueries:\n\n"
                    for i, q in enumerate(updated_state['decomposedQueries']):
                        inp += f"Query {i+1})\n{q}\n\n"
                    step.input = inp
                    step.output = "Query is decomposed into subqueries"
                elif node_name == "end":
                    step.output = f"Final answer is: {updated_state['finalAnswer']}"

        # 3) Send the final answer
        final = updated_state.get('finalAnswer', 'Üzgünüm, bir cevap üretilmedi.')
        await cl.Message(content=final, author="Assistant").send()

    except Exception as e:
        logger.exception("Pipeline error")
        await cl.Message(content=f"🚨 An error occurred: {e}", author="System").send()  """

@cl.on_message
async def on_message(message):
    """
    Handles incoming chat messages by streaming each pipeline step
    while offloading processing to a thread pool.
    """
    logger.info("🚀 New user message: %s", message.content)

    # 1) Build the initial graph state
    state: GraphState = {
        "userQuery": message.content,
        "rephrasedUserQuery": "",
        "englishUserQuery": "",
        "retrievedDocs": [],
        "relevantDocs": [],
        "pastMessages": cl.chat_context.to_openai()[-5:],
        "answerGenerated": "",
        "isAnswerSupported": False,
        "turkishAnswer": "",
        "isDecomposed": False,
        "decomposedQueries": [],
        "answerNotFound": False,
        "comeFrom": "",
        "finalAnswer": ""
    }

    try:
        send_as_notification = False
        # 2) Stream each pipeline node as a Chainlit Step
        async for node_name, updated_state in run_pipeline_step_by_step(state):
            async with cl.Step(name=node_name) as step:
                if node_name == "rephraseForFollowup":
                    
                    step.input = f"User query: {updated_state['userQuery']}"
                    step.output = f"Rephrased user query: {updated_state['rephrasedUserQuery']}"
                elif node_name == "translateToEnglish":
                    step.input = f"Before translation: {updated_state['rephrasedUserQuery']}"
                    step.output = f"After translation: {updated_state['englishUserQuery']}"

                    loop = asyncio.get_running_loop()
                    label = await loop.run_in_executor(None, classify, updated_state["englishUserQuery"])
                    if label == "NOTIFICATION":
                        
                        send_as_notification = True
                        user_email = cl.user_session.get("user_email")
                        
                        queryToSave = updated_state["englishUserQuery"]
                        print(f"chainlit side, email: {user_email}")
                        res = await post_notification(queryToSave, user_email)
                        
                        await cl.Message(
                            "Bildirim isteğinizi aldım! İlgili gelişmeleri takip edip size haber vereceğim."
                        ).send()
                        break
                elif node_name == "retrieval":
                    inp = "Retrieved Documents:\n\n"
                    for i, doc in enumerate(updated_state['retrievedDocs']):
                        inp += f"Document {i+1})\n{doc}\n\n"
                    step.input = inp
                    step.output = "Retrieval is done."
                elif node_name == "relevancyCheck":
                    inp = "Relevant Documents:\n\n"
                    for i, doc in enumerate(updated_state['relevantDocs']):
                        inp += f"Document {i+1})\n{doc}\n\n"
                    step.input = inp
                    step.output = "Relevancy check is done."
                elif node_name == "generateAnswer":
                    step.output = f"Generated answer: {updated_state['answerGenerated']}"
                elif node_name == "supportednessCheck":
                    step.output = f"Answer supported: {updated_state['isAnswerSupported']}"
                elif node_name == "translateToTurkish":
                    step.input = f"Answer before translation: {updated_state['answerGenerated']}"
                    step.output = f"Translated answer: {updated_state['turkishAnswer']}"
                elif node_name == "decompose":
                    inp = "Generated subqueries:\n\n"
                    for i, q in enumerate(updated_state['decomposedQueries']):
                        inp += f"Query {i+1})\n{q}\n\n"
                    step.input = inp
                    step.output = "Query is decomposed into subqueries"
                elif node_name == "end":
                    step.output = f"Final answer is: {updated_state['finalAnswer']}"

        if not send_as_notification:
            final = updated_state.get('finalAnswer', 'Üzgünüm, bir cevap üretilmedi.')
            await cl.Message(content=final, author="Assistant").send()

    except Exception as e:
        logger.exception("Pipeline error")
        await cl.Message(content=f"🚨 An error occurred: {e}", author="System").send()

