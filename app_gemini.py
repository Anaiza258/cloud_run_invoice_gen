# app_gemini_api.py
import os
import json
import re
import traceback
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from werkzeug.utils import secure_filename
from functools import wraps

# load .env if present
load_dotenv()

# ---------- Config & globals ----------
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/tmp/uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

FIREBASE_HOSTING_URL = os.getenv("FIREBASE_HOSTING_URL", "").rstrip("/")
CLOUD_RUN_URL = os.getenv("CLOUD_RUN_URL", "").rstrip("/")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
APP_PASSWORD = os.getenv("APP_PASSWORD")
CLERK_SECRET = os.getenv("CLERK_SECRET_KEY")

app = Flask(__name__)

# CORS setup: prefer explicit origins; fallback to wildcard for dev
origins = []
if FIREBASE_HOSTING_URL:
    origins.append(FIREBASE_HOSTING_URL)
if CLOUD_RUN_URL:
    origins.append(CLOUD_RUN_URL)
origins.extend(["http://localhost:5000", "http://127.0.0.1:5000"])
if origins:
    CORS(app, origins=origins)
else:
    CORS(app)  # allow all (dev)

# Try to import and configure google.generativeai if key present
genai = None
if GEMINI_API_KEY:
    try:
        import google.generativeai as _genai
        _genai.configure(api_key=GEMINI_API_KEY)
        genai = _genai
    except Exception as e:
        print("Warning: google.generativeai not available or failed to configure:", e)
        genai = None

# Clerk server-side optional import (if you have it)
clerk = None
if CLERK_SECRET:
    try:
        from clerk_backend_api import Clerk
        clerk = Clerk(CLERK_SECRET)
    except Exception as e:
        print("Warning: clerk backend module not available or CLERK_SECRET invalid:", e)
        clerk = None

# ---------- Helpers ----------
def safe_float(val):
    try:
        return float(val) if (val is not None and str(val).strip() != "") else 0.0
    except Exception:
        return 0.0

def save_uploaded_file(file_storage, folder=UPLOAD_FOLDER):
    filename = secure_filename(file_storage.filename or f"file_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}")
    path = os.path.join(folder, filename)
    file_storage.save(path)
    return path

# Transcription via HuggingFace Whisper inference
def get_transcript(audio_path):
    try:
        hf_key = HUGGINGFACE_API_KEY
        if not hf_key:
            return "Error: Missing HUGGINGFACE_API_KEY"
        headers = {"Authorization": f"Bearer {hf_key}", "Content-Type": "audio/mpeg"}
        with open(audio_path, "rb") as fh:
            audio_data = fh.read()
        resp = requests.post(
            "https://api-inference.huggingface.co/models/openai/whisper-large-v3-turbo",
            headers=headers,
            data=audio_data,
            timeout=120
        )
        if resp.status_code == 200:
            rj = resp.json()
            return rj.get("text", "No transcription found")
        else:
            return f"Error: Transcription failed ({resp.status_code}) - {resp.text[:400]}"
    except Exception as e:
        return f"Error: Exception in transcription: {str(e)}"

# Generate invoice using Gemini (if available) else fallback
def generate_invoice(transcript):
    try:
        if genai:
            # Simple prompt; ensure output is JSON only
            prompt = (
                "You are an assistant that MUST output valid JSON only. "
                "From the following text, extract invoice data and output a JSON object with keys: invoice (containing invoiceNumber, issueDate, dueDate, issuer_info, client, serviceDetails (list of {description,quantity,unitPrice,totalPrice}), shipping_cost, vatAmount, taxAmount, totalAmount, paymentMethod, endnote). "
                "If any field is missing, provide reasonable placeholders or empty strings/numbers.\n\n"
                f"Input: {transcript}\n\nJSON:"
            )
            try:
                model = genai.GenerativeModel("gemini-2.0-flash")
                response = model.generate_content(prompt)
                if response and getattr(response, "candidates", None):
                    text = response.candidates[0].content.parts[0].text.strip()
                    # strip code fences
                    text = re.sub(r"```(?:json)?", "", text).strip()
                    try:
                        return json.loads(text)
                    except Exception:
                        return {"error": "LLM returned non-JSON or invalid JSON", "raw": text}
                return {"error": "No response from LLM"}
            except Exception as e:
                return {"error": f"Exception calling LLM: {str(e)}"}
        else:
            # fallback demo invoice
            return {
                "invoice": {
                    "invoiceNumber": f"INV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    "issueDate": datetime.utcnow().strftime("%Y-%m-%d"),
                    "dueDate": datetime.utcnow().strftime("%Y-%m-%d"),
                    "issuer_info": {"name": "Demo Issuer"},
                    "client": {"name": "Demo Client"},
                    "serviceDetails": [{"description": transcript[:80], "quantity": 1, "unitPrice": 100.0, "totalPrice": 100.0}],
                    "shipping_cost": 0.0,
                    "vatAmount": 0,
                    "taxAmount": 0,
                    "totalAmount": 100.0,
                    "paymentMethod": "",
                    "endnote": ""
                }
            }
    except Exception as e:
        return {"error": f"generate_invoice exception: {str(e)}"}

# PDF generation (ReportLab)
def generate_detailed_pdf(invoice_data):
    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        pdf_name = f"detailed_invoice_{timestamp}.pdf"
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)
        c = canvas.Canvas(pdf_path, pagesize=letter)
        width, height = letter
        left = 50
        y = height - 60

        c.setFont("Helvetica-Bold", 20)
        c.drawString(left, y, "INVOICE")
        y -= 30

        issuer = invoice_data.get("invoice", {}).get("issuer_info", {})
        client = invoice_data.get("invoice", {}).get("client", {})

        c.setFont("Helvetica", 11)
        c.drawString(left, y, f"Issuer: {issuer.get('name', '')}")
        y -= 16
        c.drawString(left, y, f"Client: {client.get('name', '')}")
        y -= 24

        c.setFont("Helvetica-Bold", 12)
        c.drawString(left, y, "Description")
        c.drawRightString(left + 420, y, "Total")
        y -= 16
        c.setFont("Helvetica", 11)

        subtotal = 0.0
        for item in invoice_data.get("invoice", {}).get("serviceDetails", []):
            desc = item.get("description", "")[:80]
            total = safe_float(item.get("totalPrice", 0))
            c.drawString(left, y, desc)
            c.drawRightString(left + 420, y, f"{total:.2f}")
            y -= 14
            subtotal += total
            if y < 100:
                c.showPage()
                y = height - 60

        y -= 10
        c.drawRightString(left + 420, y, f"Subtotal: {subtotal:.2f}")
        c.showPage()
        c.save()
        return pdf_path
    except Exception as e:
        print("PDF generation error:", e)
        return ""

# ---------- Auth decorator ----------
def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing Authorization header"}), 401
        token = auth_header.split(" ", 1)[1]
        if clerk:
            try:
                session = clerk.sessions.verify_session(token)
                request.user = session.get("user_id")
                return f(*args, **kwargs)
            except Exception as e:
                return jsonify({"error": f"Auth verification failed: {str(e)}"}), 401
        else:
            request.user = None
            return f(*args, **kwargs)
    return wrapper

# ---------- Routes (API only) ----------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat()})

# Info routes (do NOT redirect; frontend served by Firebase)
@app.route("/", methods=["GET"])
def root_info():
    return jsonify({"message": "Cloud Run backend (API-only). Serve UI from Firebase hosting."})

@app.route("/invoice_tool", methods=["GET"])
def invoice_tool_info():
    return jsonify({"message": "Open the tool on Firebase hosting: /invoice_tool (tool.html)"})


@app.route("/pricing", methods=["GET"])
def pricing_info():
    return jsonify({"message": "Pricing page should be served by frontend (Firebase)."})


@app.route("/contact", methods=["GET"])
def contact_info():
    return jsonify({"message": "Contact page served by frontend."})

@app.route("/protected", methods=["GET"])
@require_auth
def protected_route():
    return jsonify({"message": "Authenticated", "user_id": getattr(request, "user", None)})

@app.route("/upload_audio", methods=["POST"])
def upload_audio_route():
    try:
        f = None
        if "audio" in request.files:
            f = request.files["audio"]
        elif "file" in request.files:
            f = request.files["file"]
        if not f:
            return jsonify({"error": "No file uploaded"}), 400
        save_path = save_uploaded_file(f)
        transcript = get_transcript(save_path)
        if isinstance(transcript, str) and transcript.startswith("Error"):
            return jsonify({"error": transcript}), 500
        invoice_json = generate_invoice(transcript)
        return jsonify({"ok": True, "transcript": transcript, "invoice": invoice_json})
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({"error": str(e), "trace": tb.splitlines()[-6:]}), 500

@app.route("/generate_invoice_text", methods=["POST"])
def generate_invoice_text_route():
    try:
        if request.is_json:
            body = request.get_json()
            text = (body.get("invoiceText") or body.get("text") or "").strip()
        else:
            text = (request.form.get("invoiceText") or request.form.get("text") or "").strip()
        if not text:
            return jsonify({"error": "No text provided"}), 400
        invoice_json = generate_invoice(text)
        return jsonify({"ok": True, "invoice": invoice_json})
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({"error": str(e), "trace": tb.splitlines()[-6:]}), 500

@app.route("/submit-contact", methods=["POST"])
def submit_contact_route():
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        name = data.get("name", "")
        email = data.get("email", "")
        message = data.get("message", "")
        if not name or not email or not message:
            return jsonify({"error": "name, email and message required"}), 400

        # attempt to send email if credentials provided
        if EMAIL_ADDRESS and APP_PASSWORD:
            try:
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText
                import smtplib

                msg = MIMEMultipart()
                msg["From"] = EMAIL_ADDRESS
                msg["To"] = EMAIL_ADDRESS
                msg["Subject"] = f"Contact form: {data.get('subject','No Subject')}"
                body = f"From: {name} <{email}>\n\n{message}"
                msg.attach(MIMEText(body, "plain"))
                server = smtplib.SMTP("smtp.gmail.com", 587)
                server.starttls()
                server.login(EMAIL_ADDRESS, APP_PASSWORD)
                server.send_message(msg)
                server.quit()
            except Exception as e:
                print("Email send error:", e)
        else:
            print("Email creds not set — skipping send (contact):", data)

        return jsonify({"ok": True, "message": "Contact received."})
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({"error": str(e)}), 500

@app.route("/save_invoice", methods=["POST"])
def save_invoice_route():
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        invoice_data = data.get("invoice") if isinstance(data, dict) and "invoice" in data else data

        fname = f"invoice_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        json_path = os.path.join(UPLOAD_FOLDER, fname)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(invoice_data, fh, ensure_ascii=False, indent=2)

        pdf_path = generate_detailed_pdf(invoice_data)
        if not pdf_path:
            return jsonify({"error": "PDF generation failed"}), 500

        pdf_name = Path(pdf_path).name
        return jsonify({"ok": True, "pdf_filename": pdf_name, "download_url": f"/download_pdf/{pdf_name}"})
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({"error": str(e), "trace": tb.splitlines()[-6:]}), 500

@app.route("/download_pdf/<filename>", methods=["GET"])
def download_pdf(filename):
    try:
        full = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(full):
            return jsonify({"error": "File not found"}), 404
        return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({"error": str(e)}), 500

# Global exception handler
@app.errorhandler(Exception)
def handle_all_exceptions(e):
    tb = traceback.format_exc()
    print(tb)
    return jsonify({"error": str(e), "trace": tb.splitlines()[-6:]}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
