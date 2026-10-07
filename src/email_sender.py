"""Email digest rendering and delivery.

Renders both an HTML and a plain-text digest. In dry-run it prints the
plain-text digest and sends nothing. Credentials come only from config and are
never logged.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from config import Config
from src.models import Job

log = logging.getLogger("email_sender")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def _posted_relative(job: Job) -> str:
    if job.posted_at is None:
        return "recently"
    delta = datetime.now(timezone.utc) - job.posted_at
    hours = int(delta.total_seconds() // 3600)
    if hours < 1:
        return "just now"
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _subject(count: int) -> str:
    return f"\U0001F680 AI Job Radar | {count} New Opportunities"


def render_text(jobs: list[Job]) -> str:
    lines = ["NEW JOB OPPORTUNITIES", ""]
    for i, job in enumerate(jobs, 1):
        lines.append(f"{i}. {job.title}")
        lines.append(f"   Company: {job.company}")
        lines.append(f"   Location: {job.location}")
        lines.append(f"   Work Mode: {job.work_mode.capitalize()}")
        lines.append(f"   Posted: {_posted_relative(job)}")
        lines.append(f"   Resume Match: {job.match_score:.0f}%")
        if job.matched_resume:
            lines.append(f"   Best-fit resume: {job.matched_resume}")
        if job.matching_skills:
            lines.append("   Why you match:")
            for skill in job.matching_skills[:8]:
                lines.append(f"     • {skill}")
        if job.missing_skills:
            lines.append("   Missing:")
            for skill in job.missing_skills[:6]:
                lines.append(f"     • {skill}")
        if job.reason:
            lines.append(f"   Note: {job.reason}")
        lines.append(f"   Recommendation: {job.recommendation}")
        lines.append(f"   Apply: {job.url}")
        lines.append("")
    return "\n".join(lines)


def render_html(jobs: list[Job]) -> str:
    """Render HTML. All job-derived content is HTML-escaped (untrusted JD text)."""
    blocks = [
        "<h2>\U0001F680 NEW JOB OPPORTUNITIES</h2>",
    ]
    for i, job in enumerate(jobs, 1):
        match_pairs = "".join(f"<li>{escape(s)}</li>" for s in job.matching_skills[:8])
        miss_pairs = "".join(f"<li>{escape(s)}</li>" for s in job.missing_skills[:6])
        why = f"<p><strong>Why you match:</strong></p><ul>{match_pairs}</ul>" if match_pairs else ""
        miss = f"<p><strong>Missing:</strong></p><ul>{miss_pairs}</ul>" if miss_pairs else ""
        note = f"<p><em>{escape(job.reason)}</em></p>" if job.reason else ""
        resume_line = (
            f'<p style="margin:2px 0;"><strong>Best-fit resume:</strong> {escape(job.matched_resume)}</p>'
            if job.matched_resume else ""
        )
        blocks.append(
            f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0;font-family:Arial,sans-serif;">
              <h3 style="margin:0 0 8px;">{i}. {escape(job.title)}</h3>
              <p style="margin:2px 0;"><strong>Company:</strong> {escape(job.company)}</p>
              <p style="margin:2px 0;"><strong>Location:</strong> {escape(job.location)}</p>
              <p style="margin:2px 0;"><strong>Work Mode:</strong> {escape(job.work_mode.capitalize())}</p>
              <p style="margin:2px 0;"><strong>Posted:</strong> {escape(_posted_relative(job))}</p>
              <p style="margin:2px 0;"><strong>Resume Match:</strong> {job.match_score:.0f}%</p>
              {resume_line}
              {why}
              {miss}
              {note}
              <p style="margin:6px 0;"><strong>Recommendation:</strong>
                 <span style="font-weight:bold;">{escape(job.recommendation)}</span></p>
              <p style="margin:6px 0;"><a href="{escape(job.url)}">Apply →</a></p>
            </div>
            """
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


def send_digest(jobs: list[Job], config: Config, dry_run: bool = False) -> bool:
    """Render and (unless dry-run) send the digest. Returns True on success."""
    if not jobs:
        print("No new matching jobs to report.")
        return True

    text_body = render_text(jobs)
    subject = _subject(len(jobs))

    if dry_run:
        print("=" * 60)
        print(f"[DRY RUN] Subject: {subject}")
        print("=" * 60)
        print(text_body)
        print("[DRY RUN] No email sent.")
        return True

    if not config.has_email:
        log.error("Email credentials not configured; cannot send. Use --dry-run to preview.")
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.email_address
    message["To"] = config.recipient_email
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(render_html(jobs), "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(config.email_address, config.email_password)
            server.sendmail(config.email_address, [config.recipient_email], message.as_string())
        log.info("Digest emailed to %s (%d jobs).", config.recipient_email, len(jobs))
        return True
    except Exception as exc:
        log.error("Failed to send email: %s", exc)
        return False
