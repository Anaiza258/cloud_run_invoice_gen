from flask import Flask, request, render_template, jsonify, redirect, url_for
import os
import uuid
import requests
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv
import json
import re
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from PIL import Image  
from reportlab.pdfgen import canvas
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from clerk_backend_api import Clerk
from flask_cors import CORS


# Load environment variables
load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
APP_PASSWORD = os.getenv("APP_PASSWORD")



# Initialize Clerk
clerk = Clerk(os.getenv("CLERK_SECRET_KEY"))

# Flask setup and ensure upload folder exists
app = Flask(__name__)


# Allow Firebase origin
CORS(app, resources={r"/*": {"origins": ["https://invocue-ai-invoice-generator.web.app"]}})


UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

# Middleware-like decorator for auth 
def require_auth(func):
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "Missing Authorization header"}), 401

        token = auth_header.split(" ")[1]  # Bearer <token>

        try:
            session = clerk.sessions.verify_session(token)
            request.user = session["user_id"]  # save user ID
            return func(*args, **kwargs)
        except Exception as e:
            return jsonify({"error": str(e)}), 401

    wrapper.__name__ = func.__name__
    return wrapper

@app.route("/protected")
@require_auth
def protected():
    return jsonify({
        "message": "You are logged in!",
        "user_id": request.user
    })


@app.route('/invoice_tool')
def invoice_tool():
    return render_template('tool.html')
 

@app.route("/pricing")
def pricing():
    return render_template("pricing.html")

@app.route('/contact')
def contact():
    return render_template('contact.html')

# Submit Contact (email transfer)
@app.route('/submit-contact', methods=['POST'])
def submit_contact():
    data = request.get_json()
    name = data.get('name', '')
    email = data.get('email', '')
    subject = data.get('subject', 'No Subject')  
    message = data.get('message', '')

    if not name or not email or not message:
        return jsonify({"error": "Name, email, and message are required."}), 400

    # Email content
    email_subject = f"New Contact Form Submission: {subject}"
    email_body = f"""
    You have received a new message from your portfolio contact form.\n\n
    Name: {name}\n
    Email: {email}\n
    Subject: {subject}\n
    Message:\n{message}\n\n
    Timestamp: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    """

    try:
        # Create the email
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = EMAIL_ADDRESS  
        msg['Subject'] = email_subject
        msg.attach(MIMEText(email_body, 'plain'))

        # Connect to Gmail SMTP server and send the email
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Secure the connection
            server.login(EMAIL_ADDRESS, APP_PASSWORD) 
            server.send_message(msg) 

        return jsonify({"success": True, "message": "Thank you for your message! I will respond shortly."})

    except Exception as e:
        return jsonify({"error": f"An error occurred while sending the email: {str(e)}"}), 500


# upload audio  file
@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    try:
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400

        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        # Save audio file with a timestamped filename
        filename = f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        save_path = os.path.join(UPLOAD_FOLDER, filename)
        audio_file.save(save_path)
        
        print(f"Audio file saved at: {save_path}, size: {os.path.getsize(save_path)} bytes")

        transcript = get_transcript(save_path)
        if "Error" in transcript:
            return jsonify({"error": transcript}), 500

        invoice_content = generate_invoice(transcript)
        if isinstance(invoice_content, dict) and "error" in invoice_content:
            # Unwrap the error message so that a plain string is returned.
            return jsonify({"error": str(invoice_content["error"])}), 500

        print("Generated Invoice Content:")
        print(invoice_content)
        return jsonify({
            "file_path": save_path,
            "transcription": transcript,
            "invoice_content": invoice_content
        })
    except Exception as e:
        print(f"Error in upload_audio: {str(e)}")
        return jsonify({"error": "Something went wrong", "details": str(e)}), 500
    

@app.route('/generate_invoice_text', methods=['POST'])
def generate_invoice_text():
    try:
        invoice_text = request.form.get("invoiceText", "").strip()
        if not invoice_text:
            return jsonify({"error": "No text provided"}), 400

        invoice_content = generate_invoice(invoice_text)
        if isinstance(invoice_content, dict) and "error" in invoice_content:
            return jsonify({"error": str(invoice_content["error"])}), 500

        print("Generated Invoice Content from text input:")
        print(invoice_content)
        return jsonify({"invoice_content": invoice_content})
    except Exception as e:
        return jsonify({"error": "Something went wrong", "details": str(e)}), 500

def safe_float(val):
    try:
        return float(val) if val and val.strip() != '' else 0.0
    except ValueError:
        return 0.0

@app.route('/save_invoice', methods=['POST'])
def save_invoice():
    try:
        #invoice status
        payment_status = request.form.get("payment_status", "UNPAID").strip()  # default to UNPAID
 
        # Basic invoice fields
        invoice_number = request.form.get("invoiceNumber", "").strip()
        issue_date = request.form.get("issueDate", "").strip()
        due_date = request.form.get("dueDate", "").strip()

        # Issuer information
        issuer_name = request.form.get("issuerName", "").strip()
        issuer_contact = request.form.get("issuerContact", "").strip()
        issuer_address = request.form.get("issuerAddress", "").strip()
        issuer_email = request.form.get("issuerEmail", "").strip()

        # Client details
        client_name = request.form.get("clientName", "").strip()
        client_contact = request.form.get("clientContact", "").strip()
        client_address = request.form.get("clientAddress", "").strip() 
        client_email = request.form.get("clientEmail", "").strip()
        
        # other details
        currency = request.form.get("currency", "").strip()
        shipping_cost = request.form.get("shippingCost", "").strip()
        total_amount = request.form.get("totalAmount", "").strip()
        payment_method = request.form.get("paymentMethod", "").strip()
        end_note = request.form.get("endNote", "").strip()
        vat_amount = request.form.get("vatAmount", "").strip()
        vat_option = request.form.get("vatOption", "percentage").strip()
        tax_amount = request.form.get("taxAmount", "").strip()
        tax_option = request.form.get("taxOption", "percentage").strip()

        # Reconstruct service details
        service_details = []
        i = 0
        while f"service{i}_description" in request.form:
            service = {
                "description": request.form.get(f"service{i}_description", "").strip(),
                "quantity": int(request.form.get(f"service{i}_quantity", "0")),
                "unitPrice": request.form.get(f"service{i}_unitPrice", "").strip(),
                "totalPrice": request.form.get(f"service{i}_totalPrice", "").strip(),
            }
            service_details.append(service)
            i += 1

        # Optional logo upload: check field "logo"
        logo_file = request.files.get("logo")
        logo_filename = ""
        if logo_file and logo_file.filename != "":
            logo_filename = f"logo_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{logo_file.filename}"
            logo_save_path = os.path.join(UPLOAD_FOLDER, logo_filename)
            logo_file.save(logo_save_path)
            print("Logo file saved:", logo_save_path)  # Debug print

        invoice_data = {
            "invoice": {
                "invoiceNumber": invoice_number,
                "issueDate": issue_date,
                "dueDate": due_date,
                "payment_status": payment_status,
                "currency": currency,
                "issuer_info": {
                    "name": issuer_name,
                    "contact": issuer_contact,
                    "address": issuer_address,
                    "email": issuer_email,
                },
                "client": {
                    "name": client_name,
                    "contact": client_contact,
                    "address": client_address,
                    "email": client_email,
                },
                "serviceDetails": service_details,
                "shipping_cost": shipping_cost,
                "vatAmount": vat_amount,
                "vatOption": vat_option,
                "taxAmount": tax_amount,
                "taxOption": tax_option,
                "totalAmount": total_amount,
                "paymentMethod": payment_method,
                "endNote": end_note,
                "logo": logo_filename
            }
        }

        invoice_path = os.path.join(UPLOAD_FOLDER, f"invoice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(invoice_path, 'w') as f:
            json.dump(invoice_data, f, indent=4)

        pdf_path = generate_detailed_pdf(invoice_data)
        print("Generated PDF path:", pdf_path)  # Debug print
        pdf_url = f"/download_pdf/{os.path.basename(pdf_path)}"
        return jsonify({"success": True, "pdf_url": pdf_url})

    except Exception as e:
        return jsonify({"error": "Something went wrong", "details": str(e)}), 500

@app.route('/invoice_preview')
def invoice_preview():
    pdf_filename = request.args.get('pdf_filename', '')
    return render_template('invoice_preview.html', pdf_filename=pdf_filename)

# get transcript 
def get_transcript(audio_path):
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('HUGGINGFACE_API_KEY')}",
            "Content-Type": "audio/mpeg"  #  content type for MP3 files.
        }
        with open(audio_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        response = requests.post(
            "https://api-inference.huggingface.co/models/openai/whisper-large-v3-turbo",
            headers=headers,
            data=audio_data  # send raw binary data.
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("text", "No transcription found")
        else:
            return f"Error: Failed to transcribe, status code {response.status_code}. Response: {response.text}"
    except requests.exceptions.RequestException as e:
        return f"Error: Network issue or bad response from API ({str(e)})"
    except Exception as e:
        return f"Error: Unable to generate transcription ({str(e)})"



# generate invoice from transcript
def generate_invoice(transcript):
    try:
        prompt = f"""
        The output **MUST** be in **English**, regardless of the language of the input (Urdu, Hindi, English, etc.).
        Please generate a professional invoice and automatically identify and include all the key sections:
        - Invoice details (invoice number, issue date, due date)
        - Issuer details (name, address, email)
        - Client details (name, address, email)
        - Service details (for each service/product: description, quantity, unit price and total price)
        - Shipping cost (if applicable) to be added before total amount calculation
        - TAX amount to be applied on the services subtotal
        - VAT Amount to be applied on the services
        - Total amount and Payment Method
        - End Note
        Do not require the user to specify phrases like "add", "include", etc. Automatically determine and insert details.
        If any details are missing or unclear, use very concise and clear indicator to add correct info.
        Do not add any price if price is not provided; add 0.0 as a placeholder.
        Do not add any end note by your own.
        Ensure that all key sections of the invoice are formatted properly.
        The invoice **MUST** be in **valid JSON format** without any markdown formatting.

        The JSON structure must be as follows:
        {{
            "invoice": {{
                "invoiceNumber": "INV-XXXXXX",
                "issueDate": "YYYY-MM-DD",
                "dueDate": "YYYY-MM-DD",
                "issuer_info": {{
                    "name": "Your Name",
                    "contact": "Your Contact",
                    "address": "Your Address",
                    "email": "Your Email"
                }},
                "client": {{
                    "name": "Client Name",
                    "contact": "Client Contact",
                    "address": "Client Address",
                    "email": "Client Email"
                }},
                "serviceDetails": [
                    {{
                        "description": "Service/Product 1",
                        "quantity": 1,
                        "unitPrice": 100.00,
                        "totalPrice": 100.00
                    }}
                ],
                "shipping_cost": 0.0,
                "vatAmount": 0, or 0%,
                "taxAmount": 0, or 0%,
                "totalAmount": 100.00,
                "paymentMethod": "Payment Method",
                "endnote" : "End Note"
            }}
        }}

        Ensure the output **ONLY** contains valid JSON.

        Invoice Data:
        {transcript}
        """
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        if response and response.candidates:
            invoice_content = response.candidates[0].content.parts[0].text.strip()
            invoice_content = re.sub(r"```json|```", "", invoice_content).strip()
            try:
                invoice_json = json.loads(invoice_content)
                return invoice_json
            except json.JSONDecodeError as e:
                return {"error": "Invalid JSON response from model", "raw_response": invoice_content, "error_details": str(e)}
        else:
            return {"error": "No valid response from the model"}
    except Exception as e:
        return {"error": f"Unable to generate invoice: {str(e)}"}


# generate pdf from invoice data
def generate_detailed_pdf(invoice_data):
    try:
        # Get current time in UTC
        current_time = datetime.strptime("2025-02-26 11:39:17", "%Y-%m-%d %H:%M:%S")
        pdf_filename = f"detailed_invoice_{current_time.strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
        c = canvas.Canvas(pdf_path, pagesize=letter)
        width, height = letter
        
        # Set margins and initial positions
        left_margin = 50
        right_margin = width - 50
        top_margin = height - 50

        # Fixed dimensions for logo and title area
        LOGO_MAX_WIDTH = 80
        LOGO_MAX_HEIGHT = 40
        HEADER_SPACE = LOGO_MAX_HEIGHT + 20
        
        # Draw Logo if exists with fixed dimensions
        logo_filename = invoice_data['invoice'].get('logo', '')
        if logo_filename and os.path.exists(os.path.join(UPLOAD_FOLDER, logo_filename)):
            try:
                img = Image.open(os.path.join(UPLOAD_FOLDER, logo_filename))
                img_width, img_height = img.size
                width_ratio = LOGO_MAX_WIDTH / img_width
                height_ratio = LOGO_MAX_HEIGHT / img_height
                scale_factor = min(width_ratio, height_ratio)
                new_width = img_width * scale_factor
                new_height = img_height * scale_factor
                logo_x = left_margin
                logo_y = top_margin - new_height
                c.drawImage(os.path.join(UPLOAD_FOLDER, logo_filename),
                          logo_x,
                          logo_y,
                          width=new_width,
                          height=new_height,
                          mask='auto')
            except Exception as e:
                print(f"Logo error: {str(e)}")

        # Draw Payment Status between logo and title
        payment_status = invoice_data['invoice'].get('payment_status', 'UNPAID')
        status_y = top_margin - 30  
        c.setFont("Helvetica-Bold", 16)
        status_width = c.stringWidth(payment_status, "Helvetica-Bold", 16)
        status_x = (right_margin + left_margin - status_width) / 2
        if payment_status == "PAID":
            c.setFillColorRGB(0, 0.5, 0)  # Dark green for PAID
        else:
            c.setFillColorRGB(0.8, 0, 0)  # Dark red for UNPAID
        c.drawString(status_x, status_y, payment_status)
        c.setFillColorRGB(0, 0, 0)

        # Draw Invoice Title
        c.setFont("Helvetica-Bold", 24)
        c.drawRightString(right_margin, top_margin - 30, "INVOICE")
        
        # Horizontal Line below header
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(left_margin, top_margin - HEADER_SPACE, right_margin, top_margin - HEADER_SPACE)

        # Set starting position for content
        current_y = top_margin - HEADER_SPACE - 20

        # Invoice Information (Right Column)
        info_y = current_y
        c.setFont("Helvetica", 11)
        if invoice_data['invoice'].get('invoiceNumber'):
            c.drawRightString(right_margin, info_y, f"Invoice No: {invoice_data['invoice']['invoiceNumber']}")
            info_y -= 20
        if invoice_data['invoice'].get('issueDate'):
            c.drawRightString(right_margin, info_y, f"Issue Date: {invoice_data['invoice']['issueDate']}")
            info_y -= 20
        if invoice_data['invoice'].get('dueDate'):
            c.drawRightString(right_margin, info_y, f"Due Date: {invoice_data['invoice']['dueDate']}")
            info_y -= 20

        # From section (Left Column)
        issuer_info = invoice_data['invoice']['issuer_info']
        fields = ['name', 'email', 'contact', 'address']
        if any(issuer_info.get(field) for field in fields):
            c.setFont("Helvetica-Bold", 12)
            c.drawString(left_margin, current_y, "From")
            current_y -= 20
            c.setFont("Helvetica", 11)
            for field in fields:
                if issuer_info.get(field):
                    c.drawString(left_margin, current_y, issuer_info[field])
                    current_y -= 20

        # Bill To section - only if client info exists
        client = invoice_data['invoice']['client']
        if any(client.get(field) for field in fields):
            current_y -= 20
            c.setFont("Helvetica-Bold", 12)
            c.drawString(left_margin, current_y, "Bill To")
            current_y -= 20
            c.setFont("Helvetica", 11)
            for field in fields:
                if client.get(field):
                    c.drawString(left_margin, current_y, client[field])
                    current_y -= 20

        # Service Details Table Header with centered alignment for each column
        table_y = current_y - 40
        c.setFont("Helvetica-Bold", 10)
        c.setFillColorRGB(0.2, 0.2, 0.2)
        columns = [
            {"header": "SR#", "x": left_margin, "width": 30},
            {"header": "DESCRIPTION", "x": left_margin + 40, "width": 210},
            {"header": "UNIT PRICE", "x": left_margin + 260, "width": 80},
            {"header": "QTY", "x": left_margin + 350, "width": 60},
            {"header": "TOTAL", "x": left_margin + 420, "width": 80}
        ]
        for col in columns:
            header_width = c.stringWidth(col["header"], "Helvetica-Bold", 10)
            header_x = col["x"] + (col["width"] - header_width) / 2
            c.drawString(header_x, table_y, col["header"])
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(left_margin, table_y - 10, right_margin, table_y - 10)

        # Service Details Table Content
        y = table_y - 35
        c.setFont("Helvetica", 10)
        currency_symbol = invoice_data['invoice'].get('currency', '')
        for idx, service in enumerate(invoice_data['invoice']['serviceDetails'], 1):
            # SR# column
            sr = str(idx)
            sr_width = c.stringWidth(sr, "Helvetica", 10)
            sr_x = left_margin + (30 - sr_width) / 2
            c.drawString(sr_x, y, sr)
            # DESCRIPTION column
            desc = service.get('description', '')
            c.drawString(left_margin + 110, y, desc)
            # UNIT PRICE column
            unit_price = service.get('unitPrice', '')
            if isinstance(unit_price, str):
                unit_price = unit_price.replace(currency_symbol, '')
            text = f"{currency_symbol}{unit_price}"
            text_width = c.stringWidth(text, "Helvetica", 10)
            unit_price_x = left_margin + 260 + (80 - text_width) / 2
            c.drawString(unit_price_x, y, text)
            # QTY column
            qty = str(int(float(service.get('quantity', 0))))
            qty_width = c.stringWidth(qty, "Helvetica", 10)
            qty_x = left_margin + 350 + (60 - qty_width) / 2
            c.drawString(qty_x, y, qty)
            # TOTAL column
            total_price = service.get('totalPrice', '')
            if isinstance(total_price, str):
                total_price = total_price.replace(currency_symbol, '')
            total_text = f"{currency_symbol}{total_price}"
            total_width = c.stringWidth(total_text, "Helvetica", 10)
            total_x = left_margin + 420 + (80 - total_width) / 2
            c.drawString(total_x, y, total_text)
            y -= 25
        c.line(left_margin, y + 10, right_margin, y + 10)

        # Summary Section aligned on the right side (below the table, near the TOTAL column)
        subtotal = sum(float(str(s['totalPrice']).replace(currency_symbol, '')) for s in invoice_data['invoice']['serviceDetails'])
        summary_items = []
        summary_items.append(("Subtotal:", f"{currency_symbol}{subtotal:.2f}"))
        if invoice_data['invoice'].get('vatAmount'):
            vat_rate = safe_float(invoice_data['invoice']['vatAmount'])
            vat_option = invoice_data['invoice'].get('vatOption', 'percentage').lower()
            if vat_option == "percentage":
                vat_amount = subtotal * (vat_rate / 100)
                vat_label = f"Vat ({vat_rate}%):"
            elif vat_option == "fixed":
                vat_amount = vat_rate
                vat_label = "VAT:"
            else:
                vat_amount = subtotal * (vat_rate / 100)
                vat_label = f"Vat ({vat_rate}%):"
            summary_items.append((vat_label, f"{currency_symbol}{vat_amount:.2f}"))


        # Tax 
        if invoice_data['invoice'].get('taxAmount'):
            tax_rate = safe_float(invoice_data['invoice']['taxAmount'])
            tax_option = invoice_data['invoice'].get('taxOption', 'percentage').lower()
            if tax_option == "percentage":
                tax_amount = subtotal * (tax_rate / 100)
                tax_label = f"Tax ({tax_rate}%):"
            elif tax_option == "fixed":
                tax_amount = vat_rate
                tax_label = "TAX:"
            else:
                tax_amount = subtotal * (tax_rate / 100)
                tax_label = f"Tax ({vat_rate}%):"
            summary_items.append((tax_label, f"{currency_symbol}{tax_amount:.2f}"))


         # Only add Shipping if the field is non-empty
        shipping_field = invoice_data['invoice'].get('shipping_cost', '').strip()
        if shipping_field:
            shipping = safe_float(shipping_field)
            summary_items.append(("Shipping:", f"{currency_symbol}{shipping:.2f}"))
        total_amount_val = invoice_data['invoice']['totalAmount']
        try:
            total_amount_val = float(str(total_amount_val).replace(currency_symbol, ''))
        except:
            total_amount_val = 0.0
        summary_items.append(("Total Amount:", f"{currency_symbol}{total_amount_val:.2f}"))
        
        # Draw summary items as one full line per item, right-aligned.
        summary_y = y - 20
        for label, value in summary_items:
            full_text = f"{label} {value}"
            # Use bold for Total Amount line, else regular font.
            if label.strip() == "Total Amount:":
                c.setFont("Helvetica-Bold", 10)
            else:
                c.setFont("Helvetica", 10)
            c.drawRightString(right_margin, summary_y, full_text)
            summary_y -= 20

          # Only draw Payment Method if provided (non-empty)
        if invoice_data['invoice'].get('paymentMethod', '').strip():
            c.setFont("Helvetica-Bold", 11)
            c.drawString(left_margin, y - 20, "Payment Method:")
            c.setFont("Helvetica", 11)
            c.drawString(left_margin, y - 35, invoice_data['invoice']['paymentMethod'])
        
        # Only draw End Note if provided (non-empty)
        if invoice_data['invoice'].get('endNote', '').strip():
            c.setFont("Helvetica", 10)
            c.drawString(left_margin, 50, invoice_data['invoice']['endNote'])

        c.save()
        return pdf_path

    except Exception as e:
        print(f"Error generating PDF: {str(e)}")
        return ""


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))  #for google cloud run
    app.run(host="0.0.0.0", port=port)
    # app.run(debug=True)