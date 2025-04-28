import chainlit as cl
import logging
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs
from rag.single_hop import run_pipeline_step_by_step, GraphState
import asyncio
from notification.helpers import classify, post_notification 
from chainlit.input_widget import Switch
import httpx
import socket

import asyncio, requests, json

async def call_report_sync(user_query: str, user_email: str) -> str:
    """Runs requests.post() in a background thread → returns file_id."""
    def _call():
        r = requests.post(
            "https://investmenthelper-ai-report-service.up.railway.app/generate-report",
            json={
                "reportGenerationQuery": user_query,
                "username": user_email,
            },
            timeout=3000,     # seconds
        )
        r.raise_for_status()
        return r.json()["file_id"]

    return await asyncio.to_thread(_call)
    
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
    settings = await cl.ChatSettings(
        [
            Switch(id="ReportGeneration", label="Report Generation", initial=False),
        ]
    ).send()
    report_mode = settings["ReportGeneration"]
    cl.user_session.set("report_mode", report_mode)
    
    user = cl.user_session.get("user")
    user_email = user.identifier if user else "Guest"
    cl.user_session.set("user_email", user_email)
    return

@cl.on_chat_resume
async def on_chat_resume():
    settings = await cl.ChatSettings(
        [
            Switch(
                id="ReportGeneration",
                label="Report Generation",
                # pre-populate with whatever they had before (default False)
                initial=False
            ),
        ]
    ).send()

    # 2) Persist their choice
    report_mode = settings["ReportGeneration"]
    cl.user_session.set("report_mode", report_mode)
    logger.info(f"Resumed session → report_mode={report_mode}")

@cl.on_settings_update
async def handle_settings_update(settings):
    """
    Called whenever the user changes any ChatSettings widget.
    Persist the latest ReportGeneration value in the session.
    """
    # Extract the switch value by its id
    report_mode = settings.get("ReportGeneration", False)
    # Store it for later retrieval
    cl.user_session.set("report_mode", report_mode)
    # (Optional) Log or notify
    logger.info(f"Settings updated → report_mode={report_mode}")

@cl.on_message
async def on_message(message : cl.Message):
    """
    Handles incoming chat messages by streaming each pipeline step
    while offloading processing to a thread pool.
    """
    logger.info("🚀 New user message: %s", message.content)

    logger.info("🚀 New user message: %s", message.content)
    report_mode = cl.user_session.get("report_mode", False)
    user_email = cl.user_session.get("user_email", "guest@example.com")

    if report_mode:
        logger.info("📝 Running in REPORT GENERATION mode")

        # 1) Call your FastAPI report-generation endpoint
        print("SENDING REPORT")

        async with cl.Step(name="Rapor hazırlanıyor…"):
            file_id = await call_report_sync(message.content, user_email)
            cl.Step(name = "Raporunuz hazırlandı:")
        if not file_id:
            await cl.Message(
                content="❌ Üzgünüm, rapor oluşturulamadı (file_id eksik)."
            ).send()
            return

        """pdf_url = f"https://investmenthelper-ai-backend.up.railway.app/api/report/public/preview/{file_id}"
        pdf = cl.Pdf(
            name="Your Financial Report",
            url=pdf_url,
            display="inline"
        )"""
        print("REPORT WAS SENT")
        pdf_url = f"https://investmenthelper-ai-backend.up.railway.app/api/report/public/preview/{file_id}"
        async with httpx.AsyncClient(http2=False, verify=False) as client:
            pdf_resp = await client.get(pdf_url, timeout=120.0)
        pdf_resp.raise_for_status()
        pdf_bytes = pdf_resp.content          # raw bytes of the PDF
        
        pdf_element = cl.Pdf(
            name="Finansal Raporunuz",
            content=pdf_bytes,               #  ▼ use `content`, not `url`
            display="inline"
        )


        await cl.Message(
            content="📄 İşte raporunuz:", 
            elements=[pdf]
        ).send()

        return

    # 1) Build the initial graph state
    state: GraphState = {
        "userQuery": message.content,
        "rephrasedUserQuery": "",
        "englishUserQuery": "",
        "questionType": "single",
        "retrievedDocs": [],
        "relevantDocs": [],
        "pastMessages": cl.chat_context.to_openai()[-5:],
        "answerGenerated": "",
        "isAnswerSupported": False,
        "turkishAnswer": "",
        "isDecomposed": False,
        "decomposedQueries": [],
        "bridgeTemplate": None,
        "bridgeResolved": False,
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
                elif node_name == "classifyDecomposeQuestion":
                    step.input = f"User query: {updated_state['englishUserQuery']}"
                    step.output = f"Decomposed Queries: {updated_state['decomposedQueries']}"
                elif node_name == "retrieval":
                    inp = "Retrieved Documents:\n\n"
                    for i, doc in enumerate(updated_state['retrievedDocs']):
                        inp += f"Document {i+1})\n{doc}\n\n"
                    step.input = inp
                    step.output = "Retrieval is done."
                elif node_name == "resolveBridge":
                    step.input = f"Bridge Template: {updated_state['bridgeTemplate']}"
                    step.output = f"Retrieved Docs: {updated_state['retrievedDocs']}"
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

