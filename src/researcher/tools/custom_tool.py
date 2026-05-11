# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp",
# ]
# ///

import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field


class GradeScore(BaseModel):
    score: float = Field(..., description="Overall score between 0 to 10")


class Criteria(BaseModel):
    skill: float = Field(..., description="Skill score between 0 to 10")
    yof: float = Field(..., description="Years of experience normalized between 0 to 10")
    role_alignment: float = Field(..., description="Alignment score between 0 to 10")


class EmailResult(BaseModel):
    success: bool = Field(..., description="Whether the email was sent successfully")
    message: str = Field(..., description="Status message or error details")
    to: str = Field(..., description="Recipient email address")


app = FastMCP(name="Demo Server")


# ---------- Tools (actions the LLM can take) ----------

@app.tool
def grader(skill: float, yof: float, role_alignment: float) -> str:
    """Calculates a final score between 1 to 10.

    Inputs are expected on a 1-10 scale. Weights:
      - role_alignment: 5
      - skill:          3
      - yof:            2
    Weights sum to 10, so the weighted sum is divided by 10 to keep the
    final score on the same 1-10 scale as the inputs.
    """
    sc = (5 * role_alignment + 3 * skill + 2 * yof) / 10
    result = GradeScore(score=sc)
    return result.model_dump_json()


@app.tool
def send_email(
    to: str,
    subject: str,
    body: str,
    sender_name: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html: bool = False,
) -> str:
    """Send an email via Gmail SMTP.

    Requires the following environment variables:
      - GMAIL_USER: your Gmail address (e.g. you@gmail.com)
      - GMAIL_APP_PASSWORD: a Google App Password (NOT your normal password).
        Generate at https://myaccount.google.com/apppasswords (requires 2-Step Verification).

    Honors the DRY_RUN env var: when DRY_RUN=1, the tool logs what it would have
    sent and returns success without actually contacting Gmail. Useful for testing.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body content.
        sender_name: Optional display name for the sender.
        cc: Optional comma-separated CC recipients.
        bcc: Optional comma-separated BCC recipients.
        html: If True, send body as HTML; otherwise plain text.
    """
    # Dry-run short-circuit: don't touch SMTP.
    if os.environ.get("DRY_RUN") == "1":
        result = EmailResult(
            success=True,
            message=(
                f"[DRY RUN] Would have sent email to {to} "
                f"with subject {subject!r}. SMTP call skipped."
            ),
            to=to,
        )
        return result.model_dump_json()

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        result = EmailResult(
            success=False,
            message=(
                "Missing GMAIL_USER or GMAIL_APP_PASSWORD environment variables. "
                "Generate an App Password at https://myaccount.google.com/apppasswords"
            ),
            to=to,
        )
        return result.model_dump_json()

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((sender_name, gmail_user)) if sender_name else gmail_user
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        if html:
            msg.set_content("This email requires an HTML-capable client.")
            msg.add_alternative(body, subtype="html")
        else:
            msg.set_content(body)

        # Build full recipient list (To + Cc + Bcc).
        recipients = [to]
        if cc:
            recipients += [addr.strip() for addr in cc.split(",") if addr.strip()]
        if bcc:
            recipients += [addr.strip() for addr in bcc.split(",") if addr.strip()]

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg, from_addr=gmail_user, to_addrs=recipients)

        result = EmailResult(
            success=True,
            message=f"Email sent successfully to {to}",
            to=to,
        )
        return result.model_dump_json()

    except smtplib.SMTPAuthenticationError as e:
        result = EmailResult(
            success=False,
            message=(
                f"Gmail authentication failed: {e}. "
                "Make sure you're using a Google App Password, not your account password."
            ),
            to=to,
        )
        return result.model_dump_json()
    except Exception as e:
        result = EmailResult(
            success=False,
            message=f"Failed to send email: {type(e).__name__}: {e}",
            to=to,
        )
        return result.model_dump_json()


# ---------- Resources (read-only data the LLM can access) ----------

@app.resource("config://server")
def server_config() -> dict:
    """Static information about this server."""
    return {
        "name": "Demo Server",
        "version": "1.0.0",
        "description": "A small example server with grader and send_email tools.",
    }


@app.resource("file://readme")
def readme() -> str:
    """Return contents of README.md from the working directory, if it exists."""
    path = Path("README.md")
    if not path.exists():
        return "No README.md found in working directory."
    return path.read_text(encoding="utf-8")


# ---------- Prompts (reusable prompt templates) ----------

@app.prompt
def summarize(text: str, style: str = "concise") -> str:
    """Generate a prompt that asks for a summary in the given style."""
    return f"Please summarize the following text in a {style} style:\n\n{text}"


# ---------- Run the server ----------

if __name__ == "__main__":
    app.run()