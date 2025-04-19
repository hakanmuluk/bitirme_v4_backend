from openai import OpenAI
import httpx
import os
from dotenv import load_dotenv
from fastapi import Request 

import os

load_dotenv()  # reads .env into os.environ

apiKey = os.getenv("OPENAI_API_KEY")
if not apiKey:
    raise RuntimeError("OPENAI_API_KEY not set")


client = OpenAI(api_key=apiKey)

def classify(message_text: str) -> str:
    """
    Classifies a message as either a notification request or normal message.
    No longer requires context as the message should already be rephrased.
    """
    prompt = f"""
    Determine if this message is a notification request or a normal question/conversation. A notification request is a message that asks to **monitor** or **notify** about something in the **future, 
    while a normal message is a general conversation or question.
    Message: {message_text}
    
    If it's a notification request (asking to monitor or notify about something), return NOTIFICATION
    If it's a normal conversation or question, return NORMAL
    
    Return only one word: either NOTIFICATION or NORMAL
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.12
    )
    return response.choices[0].message.content.strip().upper()

API_BASE_URL = "investmenthelper-ai-backend.up.railway.app" # Replace with your actual API base URL
async def post_notification(text: str, user_email: str):
    url      = f"{API_BASE_URL}/api/notification/save"
    payload  = {"text": text}
    headers  = {"x-user-id": user_email}
    timeout  = httpx.Timeout(30.0)  
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
