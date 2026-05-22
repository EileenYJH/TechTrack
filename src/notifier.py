"""
Email digest notifier. Sends an HTML summary of newly added events after each run.
Configure via the 'email' section in config.yaml.

Example config.yaml section:
  email:
    enabled: true
    smtp_host: smtp.gmail.com
    smtp_port: 587
    username: you@gmail.com
    password: your_app_password   # Gmail: use an App Password, not your main password
    to: you@gmail.com
"""
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_digest(new_events: list[dict], cfg: dict) -> bool:
    """Send an HTML digest email. Returns True on success, False on failure/disabled."""
    email_cfg = cfg.get("email", {})
    if not email_cfg.get("enabled", False):
        return False
    if not new_events:
        return False

    host     = email_cfg.get("smtp_host", "smtp.gmail.com")
    port     = int(email_cfg.get("smtp_port", 587))
    username = email_cfg.get("username", "")
    password = email_cfg.get("password", "")
    to_addr  = email_cfg.get("to", username)

    if not username or not password:
        print("[Notifier] Email credentials not set — skipping digest")
        return False

    subject = f"[Event Tracker] {len(new_events)} new event(s) — {datetime.now().strftime('%d %b %Y')}"
    html    = _build_html(new_events)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = username
    msg["To"]      = to_addr
    msg.attach(MIMEText(html, "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(username, password)
            server.sendmail(username, to_addr, msg.as_string())
        print(f"[Notifier] Digest sent to {to_addr} ({len(new_events)} events)")
        return True
    except Exception as e:
        print(f"[Notifier] Failed to send email: {e}")
        return False


def _build_html(events: list[dict]) -> str:
    rows = ""
    for ev in events:
        title    = ev.get("title", "Untitled")
        url      = ev.get("event_url", "#")
        cat      = ev.get("category", "Other")
        country  = ev.get("country", "")
        source   = ev.get("source_name", "")
        start    = ev.get("start_date", "")
        deadline = ev.get("deadline", "")

        date_str = _fmt_date(start) if start else "Date TBA"
        dead_str = f"  •  Deadline: {_fmt_date(deadline)}" if deadline else ""

        rows += f"""
        <tr>
          <td style="padding:8px 4px;border-bottom:1px solid #eee">
            <a href="{url}" style="font-weight:bold;color:#1a73e8;text-decoration:none">{title}</a><br>
            <span style="color:#666;font-size:12px">{cat}  •  {date_str}{dead_str}  •  {source}  •  {country}</span>
          </td>
        </tr>"""

    return f"""
    <html><body style="font-family:sans-serif;color:#333;max-width:700px;margin:auto">
      <h2 style="color:#1a73e8">EE &amp; CS Event Tracker — Daily Digest</h2>
      <p>{len(events)} new event(s) found on {datetime.now().strftime('%d %b %Y')}:</p>
      <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">
        {rows}
      </table>
      <p style="font-size:11px;color:#999;margin-top:24px">
        Open the dashboard: <code>streamlit run dashboard/app.py</code>
      </p>
    </body></html>"""


def _fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y")
    except Exception:
        return str(iso)
