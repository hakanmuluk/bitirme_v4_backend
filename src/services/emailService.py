import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import aiosmtplib
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587 
EMAIL_USER = "noreply.investchatbot@gmail.com"
EMAIL_PASSWORD = "kneusqggrtsjiovg"

async def send_email_notification(recipient_email: str, subject: str, body: str):
    message = MIMEMultipart()
    message["From"] = EMAIL_USER
    message["To"] = recipient_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        # aiosmtplib.send is a one‐shot helper
        await aiosmtplib.send(
            message,
            hostname=EMAIL_HOST,
            port=EMAIL_PORT,
            start_tls=True,
            username=EMAIL_USER,
            password=EMAIL_PASSWORD,
        )
        print(f"Email sent to {recipient_email}")
    except Exception as e:
        print(f"Error sending email to {recipient_email}: {e}")