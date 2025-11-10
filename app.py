import imaplib
import email
import smtplib
from flask import Flask, render_template, request, jsonify, redirect, url_for
from openai import OpenAI
from email.message import EmailMessage

from models import EmailLog,  SessionLocal
from config_manager import get_config, save_config, is_configured

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
AUTO_CONFIDENCE_THRESHOLD = 0.80
AUTO_CATEGORIES = ["Price Request", "Repair Inquiry", "Appointment Request"]

app = Flask(__name__)

# Variables globales pour la configuration
config = get_config()
EMAIL_ADDRESS = config.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = config.get("EMAIL_PASSWORD", "")
OPENAI_API_KEY = config.get("OPENAI_API_KEY", "")

# Initialiser le client OpenAI si la clé est disponible
client = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)


def classify_email_and_reply(email_body):
    """Use GPT to generate a polite customer support reply"""
    system = (
        f"""You are a helpful, professional customer support assistant for TechFix 
            IT Repairs. Your job is to reply to customer emails in a clear, polite, and 
            solution-oriented way. Always provide helpful details, reassure the customer, 
            and suggest next steps.
    
            Response Style Guidelines
            •	Always be polite, professional, and empathetic.
            •	Acknowledge the customer’s issue before suggesting solutions.
            •	Offer clear pricing ranges when possible.
            •	Suggest next steps: visiting the shop, booking an appointment, or calling.
            •	Sign off warmly with the business name.
            """ +
        "Possible categories: Repair Inquiry, Price Request, Appointment Request, Other. "
        "Return ONLY valid JSON with keys: category (one of the above), confidence (0.00-1.00), and reply (a suggested reply). "
        "If relevant, use the knowledge base below:"
        f"{app.knowledge_base}"
    )
    user = f"Customer email:\n\n{email_body}\n\nRespond with JSON only."

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=500
    )

    text = resp.choices[0].message.content.strip()
    # Try to extract JSON object from text
    import json, re
    match = re.search(r"(\{[\s\S]*\})", text)
    json_text = match.group(1) if match else text
    try:
        parsed = json.loads(json_text)
        category = parsed.get("category", "Other")
        confidence = float(parsed.get("confidence", 0.0))
        reply = parsed.get("reply", "").strip()
    except Exception:
        # Fallback if parsing fails: conservative values
        category = "Other"
        confidence = 0.0
        reply = "Thank you for contacting TechFix IT Repairs. We'll get back to you shortly."

    return {"category": category, "confidence": confidence, "reply": reply}


def classify_emails(emails):
    session = SessionLocal()
    unprocessed_emails = []
    classified_emails = []
    try:
        for em in emails:
            # Check DB to avoid re-processing same message id
            exists = session.query(EmailLog).filter_by(message_id=em["id"]).first()
            if exists:
                continue

            classification = classify_email_and_reply(em["body"])
            category = classification["category"]
            confidence = classification["confidence"]
            reply_text = classification["reply"]

            action = "skipped"
            # Apply rule: if category in AUTO_CATEGORIES and confidence >= threshold -> auto send
            if category in AUTO_CATEGORIES and confidence >= AUTO_CONFIDENCE_THRESHOLD:
                try:
                    send_email(
                        to_address=em["from"].split("<")[-1].replace(">", "").strip(),
                        subject=f"Re: {em['subject']}",
                        body=reply_text
                    )
                    action = "auto-sent"
                    classified_emails.append(em)
                except Exception as e:
                    action = "error_sending"
            else:
                em["reply_text"] = reply_text
                unprocessed_emails.append(em)

            # always log
            log = EmailLog(
                message_id=em["id"],
                sender=em["from"],
                subject=em["subject"],
                body=em["body"],
                category=category,
                confidence=confidence,
                reply_text=reply_text,
                action=action
            )
            session.add(log)
            session.commit()

    finally:
        session.close()

    return classified_emails, unprocessed_emails


def fetch_unread_emails():
    """Fetch unread emails from Gmail via IMAP"""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    mail.select("inbox")

    status, response = mail.search(None, '(UNSEEN)')
    unread_msg_nums = response[0].split()

    email_data = []
    for e_id in unread_msg_nums:
        _, msg_data = mail.fetch(e_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject = msg["subject"]
                from_ = msg["from"]

                # Extract body (simplified)
                if msg.is_multipart():
                    body = ""
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode()
                            break
                else:
                    body = msg.get_payload(decode=True).decode()

                email_data.append({
                    "id": e_id.decode(),
                    "from": from_,
                    "subject": subject,
                    "body": body,
                })

    mail.logout()
    return email_data


def send_email(to_address, subject, body):
    """Send an email via Gmail SMTP"""
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_address
        msg.set_content(body)
        server.send_message(msg)


def reload_config():
    """Recharge la configuration depuis le fichier"""
    global config, EMAIL_ADDRESS, EMAIL_PASSWORD, OPENAI_API_KEY, client
    config = get_config()
    EMAIL_ADDRESS = config.get("EMAIL_ADDRESS", "")
    EMAIL_PASSWORD = config.get("EMAIL_PASSWORD", "")
    OPENAI_API_KEY = config.get("OPENAI_API_KEY", "")
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """Page de configuration des clés API"""
    if request.method == "POST":
        openai_key = request.form.get("openai_key", "").strip()
        email_address = request.form.get("email_address", "").strip()
        email_password = request.form.get("email_password", "").strip()
        
        if openai_key and email_address and email_password:
            save_config(openai_key, email_address, email_password)
            reload_config()
            return render_template("setup.html", 
                                 config=get_config(), 
                                 message="Configuration enregistrée avec succès ! Vous pouvez maintenant utiliser l'application.")
        else:
            return render_template("setup.html", 
                                 config=get_config(), 
                                 error="Tous les champs sont requis.")
    
    return render_template("setup.html", config=get_config())


@app.route("/")
def landing():
    """Landing page for InboxIQ"""
    return render_template("landing.html")


@app.route("/app")
def index():
    """Main application page"""
    # Rediriger vers la page de configuration si non configuré
    if not is_configured():
        return redirect(url_for('setup'))
    
    emails = fetch_unread_emails()
    _, unprocessed_emails = classify_emails(emails)

    unprocessed_email_ids = [unprocessed_email['id'] for unprocessed_email in unprocessed_emails]
    session = SessionLocal()
    skipped_emails = (session.query(EmailLog).filter(EmailLog.action == 'skipped',
                                                     EmailLog.message_id.not_in(unprocessed_email_ids)).
                      order_by(EmailLog.timestamp.desc()).limit(50).all())
    skipped_emails = [skipped_email.to_dict() for skipped_email in skipped_emails]

    email_logs = session.query(EmailLog).order_by(EmailLog.timestamp.desc()).limit(50).all()
    session.close()
    return render_template("index.html",
                           emails=unprocessed_emails + skipped_emails, logs=email_logs)


@app.route("/dashboard")
def dashboard():
    """Dashboard with statistics"""
    if not is_configured():
        return redirect(url_for('setup'))
    
    session = SessionLocal()
    
    # Calculate statistics
    from datetime import datetime, timedelta
    from sqlalchemy import func
    
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    
    total_emails = session.query(EmailLog).count()
    today_emails = session.query(EmailLog).filter(
        func.date(EmailLog.timestamp) == today
    ).count()
    
    week_emails = session.query(EmailLog).filter(
        EmailLog.timestamp >= week_ago
    ).count()
    
    auto_sent = session.query(EmailLog).filter(EmailLog.action == 'auto-sent').count()
    manual_sent = session.query(EmailLog).filter(EmailLog.action == 'manual-sent').count()
    skipped = session.query(EmailLog).filter(EmailLog.action == 'skipped').count()
    
    automation_rate = (auto_sent / total_emails * 100) if total_emails > 0 else 0
    
    # Category breakdown
    categories = session.query(
        EmailLog.category,
        func.count(EmailLog.id).label('count')
    ).group_by(EmailLog.category).all()
    
    # Average confidence
    avg_confidence = session.query(func.avg(EmailLog.confidence)).scalar() or 0
    
    # Recent emails for timeline
    recent_emails = session.query(EmailLog).order_by(
        EmailLog.timestamp.desc()
    ).limit(10).all()
    
    session.close()
    
    stats = {
        'total_emails': total_emails,
        'today_emails': today_emails,
        'week_emails': week_emails,
        'auto_sent': auto_sent,
        'manual_sent': manual_sent,
        'skipped': skipped,
        'automation_rate': round(automation_rate, 1),
        'avg_confidence': round(avg_confidence * 100, 1) if avg_confidence else 0,
        'categories': categories,
        'recent_emails': recent_emails
    }
    
    return render_template("dashboard.html", stats=stats)


@app.route("/logs")
def logs():
    session = SessionLocal()
    email_logs = session.query(EmailLog).order_by(EmailLog.timestamp.desc()).limit(200).all()
    session.close()
    return render_template("logs.html", logs=email_logs)


@app.route("/send-email", methods=["POST"])
def send():
    data = request.json
    email_id = data["email_id"]
    session = SessionLocal()
    email_data = session.query(EmailLog).filter_by(message_id=email_id).first()

    if not email_data:
        return jsonify({"error": "Email not found"}), 404

    to_address = email_data.sender.split("<")[-1].replace(">", "").strip()
    subject = "Re: " + email_data.subject
    reply_body = email_data.reply_text

    send_email(to_address, subject, reply_body)
    email_data.action = "manual-sent"
    session.commit()
    session.close()
    return jsonify({"message": "Email sent successfully ✅"})


'''
Uncomment the code below
if you want the code to run every 5
minutes and check your inbox hands free
'''
# import time
# import threading
# CHECK_INTERVAL = 300
#
# def background_worker():
#     while True:
#         try:
#             emails = fetch_unread_emails()
#             classify_emails(emails)
#         except Exception as e:
#             print("Worker error:", e)
#         time.sleep(CHECK_INTERVAL)
#
# # start background worker thread
# worker_thread = threading.Thread(target=background_worker, daemon=True)
# worker_thread.start()


if __name__ == "__main__":
    with open('knowledge_base.txt', 'r') as f:
        knowledge_base = f.read()
    app.knowledge_base = knowledge_base

    app.run(debug=False)
