import os
import random
import string
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import requests

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app.config["SECRET_KEY"]                     = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["SQLALCHEMY_DATABASE_URI"]        = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'eaglesai.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# ── Brevo config (set these in Railway environment variables) ─────────────────
BREVO_API_KEY    = os.environ.get("BREVO_API_KEY", "")
SENDER_EMAIL     = os.environ.get("SENDER_EMAIL", "noreply@eaglesailab.org")
SENDER_NAME      = os.environ.get("SENDER_NAME",  "Eagles AI Lab")

db = SQLAlchemy(app)


# ── Models ────────────────────────────────────────────────────────────────────

class Student(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    student_id   = db.Column(db.String(20), unique=True, nullable=False)
    first_name   = db.Column(db.String(80), nullable=False)
    last_name    = db.Column(db.String(80), nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    phone        = db.Column(db.String(30))
    program      = db.Column(db.String(120))
    password     = db.Column(db.String(256), nullable=False)
    is_active    = db.Column(db.Boolean, default=True)
    is_verified  = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":          self.id,
            "student_id":  self.student_id,
            "first_name":  self.first_name,
            "last_name":   self.last_name,
            "email":       self.email,
            "phone":       self.phone,
            "program":     self.program,
            "is_active":   self.is_active,
            "is_verified": self.is_verified,
            "created_at":  self.created_at.isoformat(),
        }


class OTP(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(120), nullable=False, index=True)
    code       = db.Column(db.String(6),   nullable=False)
    purpose    = db.Column(db.String(20),  nullable=False)   # "verify" | "reset"
    used       = db.Column(db.Boolean, default=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_student_id():
    year  = datetime.utcnow().year
    count = Student.query.count() + 1
    return f"EAL-{year}-{count:04d}"


def generate_otp(length=6):
    return "".join(random.choices(string.digits, k=length))


def send_email_brevo(to_email: str, to_name: str, subject: str, html_body: str) -> bool:
    if not BREVO_API_KEY:
        print("WARNING: BREVO_API_KEY not set — email not sent.")
        return False

    payload = {
        "sender":  {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to":      [{"email": to_email,  "name": to_name}],
        "subject": subject,
        "htmlContent": html_body,
    }
    headers = {
        "accept":       "application/json",
        "content-type": "application/json",
        "api-key":      BREVO_API_KEY,
    }
    try:
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if r.status_code in (200, 201):
            return True
        print(f"Brevo error {r.status_code}: {r.text}")
        return False
    except Exception as e:
        print(f"Brevo request failed: {e}")
        return False


def otp_email_html(name: str, code: str, purpose: str) -> str:
    action = "verify your email address" if purpose == "verify" else "reset your password"
    return f"""
    <div style="font-family:'Exo 2',Arial,sans-serif;background:#020810;color:#e0f0ff;padding:40px 20px;max-width:520px;margin:auto;border-radius:8px;">
      <div style="text-align:center;margin-bottom:28px;">
        <span style="font-family:monospace;font-size:1.4rem;font-weight:900;color:#00f5ff;letter-spacing:3px;">
          EAGLES AI LAB
        </span>
      </div>
      <h2 style="color:#e0f0ff;font-size:1.2rem;margin-bottom:12px;">Hello, {name} 👋</h2>
      <p style="color:#6a8aaa;line-height:1.7;margin-bottom:24px;">
        Use the code below to {action}. It expires in <strong style="color:#e0f0ff;">10 minutes</strong>.
      </p>
      <div style="background:#050f1f;border:1px solid rgba(0,245,255,0.25);border-radius:8px;padding:24px;text-align:center;margin-bottom:24px;">
        <div style="font-family:monospace;font-size:2.8rem;font-weight:900;color:#00f5ff;
                    letter-spacing:10px;text-shadow:0 0 20px #00f5ff;">
          {code}
        </div>
        <p style="color:#6a8aaa;font-size:0.8rem;margin-top:10px;">Do not share this code with anyone.</p>
      </div>
      <p style="color:#6a8aaa;font-size:0.82rem;line-height:1.6;">
        If you did not request this, you can safely ignore this email.
      </p>
      <hr style="border:none;border-top:1px solid rgba(0,245,255,0.1);margin:24px 0;">
      <p style="color:#6a8aaa;font-size:0.75rem;text-align:center;">
        © {datetime.utcnow().year} Eagles AI & Robotics Research Lab · Abuja, Nigeria
      </p>
    </div>
    """


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/register")
def register():
    data       = request.get_json(silent=True) or {}
    first_name = (data.get("first_name") or "").strip()
    last_name  = (data.get("last_name")  or "").strip()
    email      = (data.get("email")      or "").strip().lower()
    phone      = (data.get("phone")      or "").strip()
    program    = (data.get("program")    or "").strip()
    password   =  data.get("password")   or ""

    if not all([first_name, last_name, email, password]):
        return jsonify({"ok": False, "message": "First name, last name, email and password are required."}), 400

    if len(password) < 6:
        return jsonify({"ok": False, "message": "Password must be at least 6 characters."}), 400

    if Student.query.filter_by(email=email).first():
        return jsonify({"ok": False, "message": "An account with this email already exists."}), 409

    student = Student(
        student_id  = generate_student_id(),
        first_name  = first_name,
        last_name   = last_name,
        email       = email,
        phone       = phone,
        program     = program or "General",
        password    = generate_password_hash(password),
        is_verified = False,
    )
    db.session.add(student)
    db.session.commit()

    _create_and_send_otp(email, first_name, purpose="verify")

    return jsonify({
        "ok":      True,
        "message": "Registration successful. Check your email for a verification code.",
        "student": student.to_dict(),
    }), 201


@app.post("/api/verify-otp")
def verify_otp():
    data    = request.get_json(silent=True) or {}
    email   = (data.get("email") or "").strip().lower()
    code    = (data.get("code")  or "").strip()

    if not email or not code:
        return jsonify({"ok": False, "message": "Email and OTP code are required."}), 400

    result = _validate_otp(email, code, purpose="verify")
    if not result["ok"]:
        return jsonify(result), 400

    student = Student.query.filter_by(email=email).first()
    if not student:
        return jsonify({"ok": False, "message": "Account not found."}), 404

    student.is_verified = True
    db.session.commit()

    return jsonify({
        "ok":      True,
        "message": "Email verified successfully. You can now log in.",
        "student": student.to_dict(),
    })


@app.post("/api/login")
def login():
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email")    or "").strip().lower()
    password =  data.get("password") or ""

    if not email or not password:
        return jsonify({"ok": False, "message": "Email and password are required."}), 400

    student = Student.query.filter_by(email=email).first()
    if not student or not check_password_hash(student.password, password):
        return jsonify({"ok": False, "message": "Invalid email or password."}), 401

    if not student.is_active:
        return jsonify({"ok": False, "message": "Your account has been deactivated. Contact support."}), 403

    if not student.is_verified:
        _create_and_send_otp(email, student.first_name, purpose="verify")
        return jsonify({
            "ok":           False,
            "message":      "Email not verified. A new verification code has been sent to your email.",
            "needs_verify": True,
        }), 403

    return jsonify({
        "ok":      True,
        "message": "Login successful.",
        "student": student.to_dict(),
    })


@app.post("/api/resend-otp")
def resend_otp():
    data    = request.get_json(silent=True) or {}
    email   = (data.get("email")   or "").strip().lower()
    purpose = (data.get("purpose") or "verify").strip()

    if not email:
        return jsonify({"ok": False, "message": "Email is required."}), 400

    student = Student.query.filter_by(email=email).first()
    if not student:
        return jsonify({"ok": True, "message": "If that email is registered, a code has been sent."}), 200

    _create_and_send_otp(email, student.first_name, purpose=purpose)
    return jsonify({"ok": True, "message": "A new code has been sent to your email."})


@app.post("/api/forgot-password")
def forgot_password():
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return jsonify({"ok": False, "message": "Email is required."}), 400

    student = Student.query.filter_by(email=email).first()
    if student:
        _create_and_send_otp(email, student.first_name, purpose="reset")

    return jsonify({"ok": True, "message": "If that email is registered, a reset code has been sent."})


@app.post("/api/reset-password")
def reset_password():
    data         = request.get_json(silent=True) or {}
    email        = (data.get("email")        or "").strip().lower()
    code         = (data.get("code")         or "").strip()
    new_password =  data.get("new_password") or ""

    if not all([email, code, new_password]):
        return jsonify({"ok": False, "message": "Email, code and new password are required."}), 400

    if len(new_password) < 6:
        return jsonify({"ok": False, "message": "Password must be at least 6 characters."}), 400

    result = _validate_otp(email, code, purpose="reset")
    if not result["ok"]:
        return jsonify(result), 400

    student = Student.query.filter_by(email=email).first()
    if not student:
        return jsonify({"ok": False, "message": "Account not found."}), 404

    student.password = generate_password_hash(new_password)
    db.session.commit()

    return jsonify({"ok": True, "message": "Password reset successfully. You can now log in."})


@app.get("/api/student/<int:student_id>")
def get_student(student_id):
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "message": "Student not found."}), 404
    return jsonify({"ok": True, "student": student.to_dict()})


# ── Internal OTP helpers ──────────────────────────────────────────────────────

def _create_and_send_otp(email: str, name: str, purpose: str):
    OTP.query.filter_by(email=email, purpose=purpose, used=False).update({"used": True})
    db.session.commit()

    code       = generate_otp()
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    otp = OTP(email=email, code=code, purpose=purpose, expires_at=expires_at)
    db.session.add(otp)
    db.session.commit()

    subject = "Your Eagles AI Lab Verification Code" if purpose == "verify" else "Reset Your Eagles AI Lab Password"
    send_email_brevo(email, name, subject, otp_email_html(name, code, purpose))


def _validate_otp(email: str, code: str, purpose: str) -> dict:
    otp = (
        OTP.query
        .filter_by(email=email, purpose=purpose, used=False)
        .order_by(OTP.created_at.desc())
        .first()
    )

    if not otp:
        return {"ok": False, "message": "No active code found. Please request a new one."}

    if datetime.utcnow() > otp.expires_at:
        otp.used = True
        db.session.commit()
        return {"ok": False, "message": "Code has expired. Please request a new one."}

    if otp.code != code:
        return {"ok": False, "message": "Invalid code. Please try again."}

    otp.used = True
    db.session.commit()
    return {"ok": True, "message": "Code verified."}


# ── Init ──────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    print("Database ready.")

if __name__ == "__main__":
    app.run(debug=False, port=5000)