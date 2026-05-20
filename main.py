import os
import uuid
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app.config["SECRET_KEY"]                     = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["SQLALCHEMY_DATABASE_URI"]        = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'eaglesai.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ── Models ────────────────────────────────────────────────────────────────────

class Student(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    student_id   = db.Column(db.String(20), unique=True, nullable=False)   # e.g. EAL-2025-0001
    first_name   = db.Column(db.String(80), nullable=False)
    last_name    = db.Column(db.String(80), nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    phone        = db.Column(db.String(30))
    program      = db.Column(db.String(120))                               # enrolled program
    password     = db.Column(db.String(256), nullable=False)               # hashed
    is_active    = db.Column(db.Boolean, default=True)
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
            "created_at":  self.created_at.isoformat(),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_student_id():
    year  = datetime.utcnow().year
    count = Student.query.count() + 1
    return f"EAL-{year}-{count:04d}"


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

    # Validation
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
    )
    db.session.add(student)
    db.session.commit()

    return jsonify({
        "ok":      True,
        "message": "Registration successful. You can now log in.",
        "student": student.to_dict(),
    }), 201


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

    return jsonify({
        "ok":      True,
        "message": "Login successful.",
        "student": student.to_dict(),
    })


@app.get("/api/student/<int:student_id>")
def get_student(student_id):
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "message": "Student not found."}), 404
    return jsonify({"ok": True, "student": student.to_dict()})


# ── Init ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("Database ready.")
    app.run(debug=False, port=5000)