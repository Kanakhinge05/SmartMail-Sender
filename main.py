import pandas as pd
import smtplib
import time
import os
import random
import re
import mimetypes
from pathlib import Path
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
from openai import OpenAI
from email_validator import validate_email, EmailNotValidError

# =============================================================================
# Environment and Constants
# =============================================================================

# Load environment variables
load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =============================================================================
# Helper Functions
# =============================================================================

def resolve_resume_path():
    env_path = os.getenv("RESUME_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if candidate.exists() and candidate.is_file():
            return candidate
        raise FileNotFoundError(f"RESUME_PATH points to missing file: {candidate}")

    candidates = [
        "resume.pdf",
        "Resume.pdf",
        "resume.docx",
        "Resume.docx",
        "cv.pdf",
        "CV.pdf",
        "cv.docx",
        "CV.docx",
    ]
    for name in candidates:
        candidate = Path.cwd() / name
        if candidate.exists() and candidate.is_file():
            return candidate

    return None

def generate_ai_line():
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": "Write one short professional sentence about why you want to work at a tech company"}
        ]
    )
    return response.choices[0].message.content.strip()

def send_email(to_email, subject, body, attachment_path: Path):
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = EMAIL
    msg["To"] = to_email

    msg.attach(MIMEText(body, "plain"))

    mime_type, _ = mimetypes.guess_type(str(attachment_path))
    if mime_type and "/" in mime_type:
        main_type, sub_type = mime_type.split("/", 1)
    else:
        main_type, sub_type = "application", "octet-stream"

    with open(attachment_path, "rb") as f:
        part = MIMEBase(main_type, sub_type)
        part.set_payload(f.read())

    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        "attachment",
        filename=attachment_path.name,
    )
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL, PASSWORD)
        server.send_message(msg)

def is_valid_email(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if not email:
        return False
    try:
        validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False

def get_recipient_name(row):
    for key in ["name", "Name", "full_name", "Full Name"]:
        if key in row.index:
            value = str(row[key]).strip()
            if value and value.lower() not in {"nan", "none"}:
                return value
    return "Hiring Manager"


def is_wrong_mail_error(message: str) -> bool:
    if not message:
        return False
    message = message.lower()
    return any(
        phrase in message
        for phrase in [
            "address not found",
            "delivery has failed",
            "recipient's domain",
            "not listed in the domain's directory",
            "recipient address rejected",
            "recipient refused",
            "550 5.1.1",
            "550 5.1.0",
            "5.1.1",
            "5.1.0",
            "mailbox unavailable",
        ]
    )

# =============================================================================
# Data Loading
# =============================================================================

resume_path = resolve_resume_path()
if resume_path is None:
    raise SystemExit(
        "Resume file not found. Put `resume.pdf` in this folder or set `RESUME_PATH` in your environment."
    )

# Load CSV file
df = pd.read_csv(r"c:\Users\HP\My-Doc\hr_list.csv")

# Load email template
with open("email_template.txt", "r") as f:
    TEMPLATE = f.read()

ai_lines = [
    "I admire your company's innovation and growth.",
    "I am excited about the impactful work your team is doing.",
    "Your organization's vision aligns with my skills and interests.",
]

# =============================================================================
# Main Execution
# =============================================================================

start_time = time.time()
success_count = 0
failure_count = 0
sent_records = []
wrong_records = []

# Loop through list
for index, row in df.iterrows():
    email = str(row.get("email", "")).strip() if "email" in row.index else ""
    if not is_valid_email(email):
        wrong_row = row.to_dict()
        wrong_row["email"] = email
        wrong_row["reason"] = "Invalid email format"
        wrong_records.append(wrong_row)
        print(f"❌ Invalid email skipped: {email or '<missing>'}")
        failure_count += 1
        continue

    try:
        ai_line = random.choice(ai_lines)
        recipient_name = get_recipient_name(row)

        body = TEMPLATE.format(
            name=recipient_name,
            ai_line=ai_line
        )

        send_email(email, "Application for DevOps Role", body, resume_path)

        sent_row = row.to_dict()
        sent_row["email"] = email
        sent_row["recipient_name"] = recipient_name
        sent_row["sent_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        sent_records.append(sent_row)

        print(f"✅ Sent to {email}")
        time.sleep(15)  # delay to avoid spam
        success_count += 1

    except Exception as e:
        error_message = str(e).strip()
        reason = (
            "Rejected or invalid recipient address"
            if is_wrong_mail_error(error_message)
            else error_message
        )
        wrong_row = row.to_dict()
        wrong_row["email"] = email
        wrong_row["reason"] = reason
        wrong_records.append(wrong_row)
        print(f"❌ Failed for {email}: {reason}")
        failure_count += 1

end_time = time.time()

# =============================================================================
# Save Results
# =============================================================================

if sent_records:
    pd.DataFrame(sent_records).to_csv("sent_emails.csv", index=False)
    print("Saved sent email log to sent_emails.csv")
    
    # Backup cumulative sent emails
    backup_file = "all_sent_emails.csv"
    df_sent = pd.DataFrame(sent_records)
    try:
        existing_df = pd.read_csv(backup_file)
        combined_df = pd.concat([existing_df, df_sent], ignore_index=True)
    except FileNotFoundError:
        combined_df = df_sent
    combined_df.to_csv(backup_file, index=False)
    print("Updated cumulative backup to all_sent_emails.csv")
else:
    print("No sent emails to log.")

if wrong_records:
    pd.DataFrame(wrong_records).to_csv("wrong_emails.csv", index=False)
    print("Saved wrong email log to wrong_emails.csv")
else:
    print("No wrong emails to log.")

# =============================================================================
# Print Summary
# =============================================================================

print(f"Total Sent: {success_count}")
print(f"Failed: {failure_count}")

total_seconds = end_time - start_time
if total_seconds >= 60:
    minutes = total_seconds / 60
    print(f"Time Taken: {minutes:.2f} minutes")
else:
    print(f"Time Taken: {total_seconds:.2f} seconds")
