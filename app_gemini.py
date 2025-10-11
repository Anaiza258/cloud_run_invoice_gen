# app_gemini_api.py
import os
import json
import re
import traceback
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, redirect, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from PIL import Image

# load .env if present
load_dotenv()

# Optional 3rd-party libs (Gemini) — only configure if key present
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print("Warning: google.generativeai not configured:", e)

# Email creds (optional)
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
APP_PASSWORD = os.getenv("APP_PASSWORD")

# Clerk secret if you verify sessions server-side (optional)
CLERK_SECRET = os.getenv("CLERK_SECRET_KEY")
# if you have clerk_backend_api.py and Clerk implementation, import it
try:
    from clerk_backend_api import Clerk
    clerk = Clerk(CLERK_SECRET) if CLERK_SECRET else None
except Exception:
    clerk = None
    print("Clerk backend API not available or CLERK_SECRET_KEY missing. Protected endpoints will require token only (no server verify).")

# Upload folder (Cloud Run ephemeral)
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/tmp/uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Firebase hosting URL (for redirects/CORS). Set this in Cloud Run env vars.
FIREBASE_HOSTING_URL = os.getenv("FIREBASE_HOSTING_URL", "").rstrip("/")

# Optional Cloud Run URL (add to CORS)
CLOUD_RUN_URL = os.getenv("CLOUD_RUN_URL", "")

app = Flask(__name__)

# CORS: allow firebase host + localhost for testing. Avoid "*" in production.
origins = []
if FIREBASE_HOSTING_URL:
    origins.append(FIREBASE_HOSTING_URL)
origins.extend(["http://localhost:5000", "http://127.0.0.1:5000"])
if CLOUD_RUN_URL:
    origins.append(CLOUD_RUN_URL)
# during rapid testing you can use ["*"], but prefer explicit origins
CORS(app, origins=origins or ["*"])


# ---------------- Utility & helpers (kept from your original code, slightly hardened) ----------------

def safe_float(val):
    try:
        return float(val) if val and str(val).strip() != '' else 0.0
    except Exception:
        return 0.0

# Transcript using HuggingFace Whisper endpoint (from your original)
def get_transcript(audio_path):
    try:
        hf_key = os.getenv("HUGGINGFACE_API_KEY")
        if not hf_key:
            return "Error: Missing HUGGINGFACE_API_KEY"
        headers = {"Authorization": f"Bearer {hf_key}", "Content-Type": "audio/mpeg"}
        with open(audio_path, "rb") as audio_file:
            audio_data = audio_file.read()
        resp = requests.post(
            "https://api-inference.huggingface.co/models/openai/whisper-large-v3-turbo",
            headers=headers,
            data=audio_data,
            timeout=60
        )
        if resp.status_code == 200:
            rj = resp.json()
            return rj.get("text", "No transcription found")
        else:
            return f"Error: Failed to transcribe, status {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Error: Exception in transcription: {str(e)}"

# Invoice generation using Gemini (or fallback)
def generate_invoice(transcript):
    try:
        if GEMINI_API_KEY:
            # Use Gemini model (your original prompt). Keep it simple here.
            model = genai.GenerativeModel("gemini-2.0-flash")
            prompt = f"Generate valid JSON invoice from the following text. Output must be JSON only.\n\n{transcript}"
            response = model.generate_content(prompt)
            if response and response.candidates:
                text = response.candidates[0].content.parts[0].text.strip()
                text = re.sub(r"```json|```", "", text).strip()
                try:
                    return json.loads(text)
                except Exception:
                    return {"error": "Invalid JSON from LLM", "raw": text}
            return {"error": "No response from LLM"}
        else:
            # Demo fallback — return a minimal invoice JSON so API works without keys
            return {
                "invoice": {
                    "invoiceNumber": f"INV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    "issueDate": datetime.utcnow().strftime("%Y-%m-%d"),
                    "dueDate": datetime.utcnow().strftime("%Y-%m-%d"),
                    "issuer_info": {"name": "Demo Issuer", "contact": "", "address": "", "email": ""},
                    "client": {"name": "Demo Client", "contact": "", "address": "", "email": ""},
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
        return {"error": f"Exception in generate_invoice: {str(e)}"}

# PDF generation (kept largely as your existing implementation but simplified a bit)
def generate_detailed_pdf(invoice_data):
    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        pdf_name = f"detailed_invoice_{timestamp}.pdf"
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)
        c = canvas.Canvas(pdf_path, pagesize=letter)
        width, height = letter
        left_margin = 50
        top_margin = height - 50

        c.setFont("Helvetica-Bold", 24)
        c.drawString(left_margin, top_margin, "INVOICE")
        current_y = top_margin - 50

        issuer = invoice_data.get("invoice", {}).get("issuer_info", {})
        client = invoice_data.get("invoice", {}).get("client", {})

        c.setFont("Helvetica", 11)
        c.drawString(left_margin, current_y, f"Issuer: {issuer.get('name','')}")
        current_y -= 18
        c.drawString(left_margin, current_y, f"Client: {client.get('name','')}")
        current_y -= 30

        # services
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left_margin, current_y, "Description")
        c.drawString(left_margin + 320, current_y, "Total")
        current_y -= 18
        c.setFont("Helvetica", 11)
        subtotal = 0.0
        for s in invoice_data.get("invoice", {}).get("serviceDetails", []):
            desc = s.get("description", "")
            total = safe_float(s.get("totalPrice", 0))
            c.drawString(left_margin, current_y, desc[:60])
            c.drawRightString(left_margin + 420, current_y, f"{total:.2f}")
            current_y -= 16
            subtotal += total

        # summary
        current_y -= 18
        c.drawRightString(left_margin + 420, current_y, f"Subtotal: {subtotal:.2f}")
        c.showPage()
        c.save()
        return pdf_path
    except Exception as e:
        print("PDF generation error:", e)
        return ""

# ------------------- Auth wrapper (Clerk) -------------------
def require_auth(func):
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing Authorization header"}), 401
        token = auth_header.split(" ", 1)[1]
        # If clerk object available, try verifying; otherwise accept token format only (you can extend)
        if clerk:
            try:
                session = clerk.sessions.verify_session(token)
                request.user = session.get("user_id")
                return func(*args, **kwargs)
            except Exception as e:
                return jsonify({"error": f"Auth error: {str(e)}"}), 401
        else:
            # fallback — let token pass (but you may reject in production)
            request.user = None
            return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# ------------------- Routes (API only) -------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat()})

# Frontend pages should be served by Firebase hosting.
# Redirects here will send user to Firebase page if they accidentally hit Cloud Run UI routes.
@app.route("/", methods=["GET"])
def root_redirect():
    if FIREBASE_HOSTING_URL:
        return redirect(FIREBASE_HOSTING_URL + "/")
    return jsonify({"message": "Backend running. Set FIREBASE_HOSTING_URL env var to redirect to frontend."})

@app.route("/invoice_tool", methods=["GET"])
def invoice_tool_redirect():
    if FIREBASE_HOSTING_URL:
        return redirect(FIREBASE_HOSTING_URL + "/tool.html")
    return jsonify({"message": "Use frontend to open the invoice tool."})

@app.route("/pricing", methods=["GET"])
def pricing_redirect():
    if FIREBASE_HOSTING_URL:
        return redirect(FIREBASE_HOSTING_URL + "/pricing.html")
    return jsonify({"message": "Pricing route. Frontend should serve this."})

@app.route("/contact", methods=["GET"])
def contact_redirect():
    if FIREBASE_HOSTING_URL:
        return redirect(FIREBASE_HOSTING_URL + "/contact.html")
    return jsonify({"message": "Contact route. Frontend should serve this."})

@app.route("/protected", methods=["GET"])
@require_auth
def protected():
    return jsonify({"message": "You are authenticated", "user_id": getattr(request, "user", None)})

# Upload audio (file key may be 'audio' or 'file')
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

        filename = f.filename or f"audio_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.mp3"
        save_path = os.path.join(UPLOAD_FOLDER, filename)
        f.save(save_path)

        transcript = get_transcript(save_path)
        if isinstance(transcript, str) and transcript.startswith("Error"):
            return jsonify({"error": transcript}), 500

        invoice_json = generate_invoice(transcript)
        return jsonify({"ok": True, "transcript": transcript, "invoice": invoice_json})
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({"error": str(e), "trace": tb.splitlines()[-6:]}), 500

# Generate from text (accept JSON or form)
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

# Submit contact (email)
@app.route("/submit-contact", methods=["POST"])
def submit_contact_route():
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        name = data.get("name", "")
        email = data.get("email", "")
        message = data.get("message", "")
        if not name or not email or not message:
            return jsonify({"error": "name, email and message required"}), 400

        # If EMAIL creds exist, try sending email (kept simple)
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
                # continue and still return success (or return error if you prefer)
        else:
            print("Email creds not set — skipping send (contact payload):", data)

        return jsonify({"ok": True, "message": "Contact received."})
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({"error": str(e)}), 500

# Save invoice: accepts form or JSON, saves JSON, generates PDF, returns download URL
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
        # Return path that frontend can fetch: using relative download endpoint (will be proxied by firebase if configured)
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

# Global exception handler — helpful for Cloud Run debugging
@app.errorhandler(Exception)
def handle_all_exceptions(e):
    tb = traceback.format_exc()
    print(tb)
    return jsonify({"error": str(e), "trace": tb.splitlines()[-6:]}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
