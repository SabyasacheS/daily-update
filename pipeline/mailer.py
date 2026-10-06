"""Sends the morning email through Gmail (free) to your work Outlook address.

Secrets used: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, EMAIL_TO (one address, or several separated by commas).
"""
import os
import smtplib
from datetime import date
from email.message import EmailMessage

from .config import fmt_pct


def subject(report):
    s = report["settings"].get("site_title", "Daily Update")
    day = date.fromisoformat(report["today"]).strftime("%d %b")
    bits = []
    for h in report["holdings"]:
        if h.get("largest") and h["q"]:
            bits.append(f"{h['name']} {fmt_pct(h['q']['change_pct'], 1)}")
    for t in report["briefing"]["top3"]:
        if t["label"] != "Markets" and len(bits) < 2:
            bits.append(t["title"][:60].rstrip())
    return f"{s} {day} \u00b7 " + ", ".join(bits) if bits else f"{s} {day}"


def send(report, wl, html, pdf):
    user = os.environ.get("GMAIL_ADDRESS")
    pwd = os.environ.get("GMAIL_APP_PASSWORD")
    to = [e.strip() for e in os.environ.get("EMAIL_TO", "").split(",") if "@" in e]
    if not (user and pwd and to):
        print("Email skipped: set GMAIL_ADDRESS, GMAIL_APP_PASSWORD and EMAIL_TO as repository secrets")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject(report)
    msg["From"] = f"{wl['settings'].get('site_title', 'Daily Update')} <{user}>"
    msg["To"] = ", ".join(to)
    msg.set_content("Today's Daily Update is best viewed as HTML. Full report: "
                    + wl["settings"].get("site_url", ""))
    msg.add_alternative(html, subtype="html")
    if pdf:
        msg.add_attachment(pdf, maintype="application", subtype="pdf",
                           filename=f"Daily-Update-{report['today']}.pdf")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
        smtp.login(user, pwd)
        smtp.send_message(msg)
    print(f"Email sent to {', '.join(to)}")
    return True
