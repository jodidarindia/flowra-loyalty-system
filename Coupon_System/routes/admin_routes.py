import code
import time
from bson import ObjectId
import resend

from datetime import datetime, timedelta

import os

import io
from utils.email_service import send_company_credentials, send_redemption_email
from extensions import mail, csrf
from werkzeug.utils import secure_filename
import uuid
import pandas as pd
from flask import Blueprint, app, render_template, session, redirect, url_for, flash, request, current_app, send_file 
from werkzeug.security import generate_password_hash
from utils.qr_generator import generate_qr
import random

import string
try:
    import win32print
except ImportError:
    win32print = None
import secrets


def generate_code(length=16):
    characters = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))


admin_bp = Blueprint("admin", __name__)

print("admin_routes imported")

def send_company_credentials(to_email, contact_name, company_name, login_email, temp_password):
    params = {
        "from": "FLOWRA <noreply@flowralive.in>",
        "to": [to_email],
        "subject": "Your FLOWRA Company Admin Account",
        "html": f"""
        <h2>Welcome to FLOWRA</h2>
        <p>Hello {contact_name},</p>
        <p>Your company account has been created successfully.</p>

        <p><b>Company:</b> {company_name}</p>
        <p><b>Login Email:</b> {login_email}</p>
        <p><b>Password:</b> {temp_password}</p>

        <p>
            <a href="https://loyalty.flowralive.in/login">
                Login to FLOWRA
            </a>
        </p>
        """
    }

    return resend.Emails.send(params)



PRINTER_NAME = "TSC TE244"

def send_raw_to_usb_printer(raw_data: str):
    if win32print is None:
        print("Printer skipped on server")
        return False

    hprinter = win32print.OpenPrinter(PRINTER_NAME)
    try:
        hjob = win32print.StartDocPrinter(hprinter, 1, ("Coupon Print", None, "RAW"))
        try:
            win32print.StartPagePrinter(hprinter)
            win32print.WritePrinter(hprinter, raw_data.encode("utf-8"))
            win32print.EndPagePrinter(hprinter)
        finally:
            win32print.EndDocPrinter(hprinter)
    finally:
        win32print.ClosePrinter(hprinter)

    return True

def get_db():
    mongo = current_app.config["MONGO_INSTANCE"]
    return mongo.cx["flowra_db"]


def now():
    return datetime.utcnow()


def oid(value):
    try:
        return ObjectId(value)
    except Exception:
        return value

def has_active_subscription(user_id):
    db = get_db()

    sub = db.subscriptions.find_one({
        "$or": [
            {"user_id": user_id},
            {"user_id": oid(user_id)}
        ],
        "status": "active",
        "end_date": {"$gt": now()}
    })

    return sub is not None

def is_company_trial_expired(company_id):
    return not has_active_trial_for_company(company_id)


def block_if_trial_company_expired():
    company_id = session.get("company_id")

    if not company_id:
        return None

    if is_trial_company(company_id) and not has_active_trial_for_company(company_id):
        deactivate_expired_trial_company(company_id)

        session.clear()
        flash("This trial company has expired. Please upgrade your plan.", "warning")
        return redirect(url_for("auth.pricing"))

    return None


def is_trial_company(company_id):
    db = get_db()

    admin = db.users.find_one({
        "company_id": company_id,
        "role": "admin",
        "account_type": "trial",
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    return admin is not None


def deactivate_expired_trial_company(company_id):
    db = get_db()

    try:
        db.users.update_many(
            {
                "company_id": company_id,
                "role": {"$in": ["admin", "employee", "qr_employee", "sales"]},
                "account_type": "trial",
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            },
            {
                "$set": {
                    "is_deleted": 1,
                    "is_online": 0,
                    "deleted_at": now()
                }
            }
        )

        return True

    except Exception as e:
        print("TRIAL COMPANY DEACTIVATE ERROR:", str(e))
        return False


def has_active_trial_for_company(company_id):
    db = get_db()

    admin = db.users.find_one({
        "company_id": company_id,
        "role": "admin",
        "account_type": "trial",
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not admin:
        return False

    admin_id = admin.get("_id")

    active_trial = db.subscriptions.find_one({
        "$or": [
            {"user_id": str(admin_id)},
            {"user_id": admin_id}
        ],
        "status": "active",
        "end_date": {"$gt": now()}
    })

    return active_trial is not None


def is_trial_admin(user_id):
    db = get_db()

    user = db.users.find_one({
        "$or": [
            {"_id": oid(user_id)},
            {"id": user_id}
        ]
    })

    if not user:
        return False

    return (user.get("account_type") or "").strip().lower() == "trial"



def build_coupon_zpl(part_no, mrp, pack_size, points, code, brand_name, qr_size="25x50"):

    if qr_size == "50x50":
        return f"""
^XA
^PW400
^LL400
^LH0,0

^FO0,0^GB400,400,2^FS

^FO0,0^GB58,400,58^FS
^FO8,20^A0B,28,28^FR^FD{brand_name}^FS

^FO78,20^A0N,30,30^FD{part_no}^FS
^FO79,20^A0N,30,30^FD{part_no}^FS

^FO78,90^A0N,26,26^FDMRP    : Rs. {mrp:.2f}^FS
^FO79,90^A0N,26,26^FDMRP    : Rs. {mrp:.2f}^FS

^FO78,130^A0N,26,26^FDPACK   : {pack_size}^FS
^FO79,130^A0N,26,26^FDPACK   : {pack_size}^FS

^FO78,170^A0N,26,26^FDPOINTS : {points}^FS
^FO79,170^A0N,26,26^FDPOINTS : {points}^FS

^FO250,60
^BQN,2,8
^FDLA,{code}^FS

^FO78,340^A0N,36,36^FD{code}^FS
^FO79,340^A0N,36,36^FD{code}^FS

^XZ
"""
    else:
        return f"""
^XA
^PW400
^LL200
^LH0,0

^FO0,0^GB400,200,2^FS

^FO0,0^GB58,200,58^FS
^FO8,15^A0B,24,24^FR^FD{brand_name}^FS

^FO74,10^A0N,26,26^FD{part_no}^FS
^FO75,10^A0N,26,26^FD{part_no}^FS

^FO74,45^A0N,22,22^FDMRP    : Rs. {mrp:.2f}^FS
^FO75,45^A0N,22,22^FDMRP    : Rs. {mrp:.2f}^FS

^FO74,75^A0N,22,22^FDPACK   : {pack_size}^FS
^FO75,75^A0N,22,22^FDPACK   : {pack_size}^FS

^FO74,105^A0N,22,22^FDPOINTS : {points}^FS
^FO75,105^A0N,22,22^FDPOINTS : {points}^FS

^FO252,30
^BQN,2,5
^FDLA,{code}^FS

^FO74,160^A0N,30,30^FD{code}^FS
^FO75,160^A0N,30,30^FD{code}^FS

^XZ
"""
    


def send_redemption_email(to_email, dealer_name, coupon_code, points, redemption_type, invoice_no=""):
    params = {
        "from": "FLOWRA <noreply@flowralive.in>",
        "to": [to_email],
        "subject": "Coupon Redeemed Successfully",
        "html": f"""
        <h2>Coupon Redeemed Successfully</h2>
        <p>Hello {dealer_name},</p>

        <p>Your coupon has been redeemed successfully.</p>

        <p><b>Coupon Code:</b> {coupon_code}</p>
        <p><b>Points:</b> {points}</p>
        <p><b>Type:</b> {redemption_type}</p>
        <p><b>Invoice No:</b> {invoice_no if invoice_no else "N/A"}</p>

        <br>
        <p>Thank you,<br>FLOWRA Team</p>
        """
    }

    return resend.Emails.send(params)

def _check_company_admin():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return False
    return True


def _get_entity_label(entity_type: str) -> str:
    mapping = {
        "distributors": "Distributor",
        "retailers": "Retailer",
        "mechanics": "Mechanic",
    }
    return mapping.get(entity_type, "Record")



def verify_dealer_token(dealer_id, token):
    if not dealer_id or not token:
        return False

    db = get_db()

    dealer = db.distributors.find_one({
        "_id": oid(dealer_id),
        "active_token": token
    })

    return dealer is not None


def _get_entity_template(entity_type: str) -> str:
    mapping = {
        "distributors": "company_admin_distributors.html",
        "retailers": "company_admin_retailers.html",
        "mechanics": "company_admin_mechanics.html",
    }
    return mapping.get(entity_type, "company_admin_distributors.html")


def _fetch_entities(entity_type: str, company_id):
    db = get_db()

    if entity_type not in ["distributors", "retailers", "mechanics"]:
        return []

    rows = db[entity_type].find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    data = []
    for row in rows:
        data.append({
            "id": str(row.get("_id")),
            "dealer_code": row.get("dealer_code", ""),
            "name": row.get("name", ""),
            "mobile": row.get("mobile", ""),
            "email": row.get("email", ""),
            "pan": row.get("pan", ""),
            "gst": row.get("gst", ""),
            "city": row.get("city", ""),
            "state": row.get("state", ""),
            "address": row.get("address", ""),
        })

    return data


def _fetch_single_entity(entity_type: str, company_id, record_id):
    db = get_db()

    if entity_type not in ["distributors", "retailers", "mechanics"]:
        return None

    row = db[entity_type].find_one({
        "_id": oid(record_id),
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not row:
        return None

    return {
        "id": str(row.get("_id")),
        "dealer_code": row.get("dealer_code", ""),
        "name": row.get("name", ""),
        "mobile": row.get("mobile", ""),
        "email": row.get("email", ""),
        "pan": row.get("pan", ""),
        "gst": row.get("gst", ""),
        "city": row.get("city", ""),
        "state": row.get("state", ""),
        "address": row.get("address", ""),
    }

@admin_bp.route("/super-admin/companies", methods=["GET", "POST"])
def company_management():
    if "user_id" not in session or session.get("user_role") != "super_admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        admin_name = request.form.get("admin_name", "").strip()
        admin_email = request.form.get("admin_email", "").strip().lower()
        admin_password = request.form.get("admin_password", "").strip()
        status = request.form.get("status", "Active").strip()

        if not company_name or not admin_name or not admin_email or not admin_password:
            flash("Please fill all required fields.", "danger")
            return redirect(url_for("admin.company_management"))

        existing = db.users.find_one({
            "email": admin_email,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing:
            flash("Admin email already exists!", "danger")
            return redirect(url_for("admin.company_management"))

        try:
            hashed_password = generate_password_hash(admin_password)

            last_company = db.companies.find_one(
                {"company_code": {"$regex": "^FLR"}},
                sort=[("company_code", -1)]
            )

            if last_company and last_company.get("company_code"):
                try:
                    last_number = int(last_company.get("company_code").replace("FLR", ""))
                except:
                    last_number = db.companies.count_documents({})
            else:
                last_number = db.companies.count_documents({})

            company_code = f"FLR{last_number + 1:03d}"

            company_result = db.companies.insert_one({
                "company_code": company_code,
                "name": company_name,
                "status": status,
                "is_deleted": 0,
                "created_at": now()
            })

            company_id = str(company_result.inserted_id)

            db.users.insert_one({
                "name": admin_name,
                "email": admin_email,
                "password": hashed_password,
                "role": "admin",
                "company_id": company_id,
                "is_online": 0,
                "is_deleted": 0,
                "account_type": "paid",
                "created_at": now()
            })

            try:
                send_company_credentials(
                    to_email=admin_email,
                    contact_name=admin_name,
                    company_name=company_name,
                    login_email=admin_email,
                    temp_password=admin_password
                )

                flash(
                    f"Company created successfully. Code: {company_code}. Credentials sent to admin email.",
                    "success"
                )

            except Exception as mail_error:
                print("MAIL ERROR:", mail_error)

                flash(
                    f"Company created successfully. Code: {company_code}. But email sending failed.",
                    "warning"
                )

            return redirect(url_for("admin.company_management"))

        except Exception as e:
            flash(f"Error creating company: {str(e)}", "danger")
            return redirect(url_for("admin.company_management"))

    companies_cursor = db.companies.find({
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    companies = []

    for company in companies_cursor:
        company_id = str(company.get("_id"))

        admin = db.users.find_one({
            "company_id": company_id,
            "role": "admin",
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        companies.append({
            "id": company_id,
            "company_code": company.get("company_code", "FLR---"),
            "name": company.get("name", ""),
            "status": company.get("status", "Active"),
            "admin": admin.get("name", "N/A") if admin else "N/A"
        })

    return render_template("company_management.html", companies=companies)


@admin_bp.route("/company-admin/employees", methods=["GET", "POST"])
def manage_employees():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    expired_redirect = block_if_trial_company_expired()
    if expired_redirect:
        return expired_redirect

    db = get_db()

    company_id = session.get("company_id")
    admin_account_type = session.get("account_type", "paid")

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        allowed_roles = ["employee", "qr_employee", "sales"]

        if not name or not email or not password or not role:
            flash("Please fill all fields.", "danger")
            return redirect(url_for("admin.manage_employees"))

        if role not in allowed_roles:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("admin.manage_employees"))

        existing_user = db.users.find_one({
            "email": email,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing_user:
            flash("Email already exists. Please use a different email.", "danger")
            return redirect(url_for("admin.manage_employees"))

        try:
            hashed_password = generate_password_hash(password)

            db.users.insert_one({
                "name": name,
                "email": email,
                "password": hashed_password,
                "role": role,
                "company_id": company_id,
                "is_online": 0,
                "is_deleted": 0,
                "account_type": admin_account_type,
                "trial_used": 0,
                "created_at": now()
            })

            flash("Employee created successfully!", "success")
            return redirect(url_for("admin.manage_employees"))

        except Exception as e:
            flash(f"Error creating employee: {str(e)}", "danger")
            return redirect(url_for("admin.manage_employees"))

    employees_cursor = db.users.find({
        "company_id": company_id,
        "role": {
            "$in": ["employee", "qr_employee", "sales"]
        },
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    employees = []

    for emp in employees_cursor:
        employees.append({
            "id": str(emp.get("_id")),
            "name": emp.get("name", ""),
            "email": emp.get("email", ""),
            "role": emp.get("role", "")
        })

    return render_template("manage_employees.html", employees=employees)


@admin_bp.route("/company-admin/employee/delete/<employee_id>", methods=["POST"])
def delete_employee(employee_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    expired_redirect = block_if_trial_company_expired()
    if expired_redirect:
        return expired_redirect

    db = get_db()
    company_id = session.get("company_id")

    try:
        result = db.users.update_one(
            {
                "_id": oid(employee_id),
                "company_id": company_id,
                "role": {"$in": ["employee", "qr_employee", "sales"]},
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            },
            {
                "$set": {
                    "is_deleted": 1,
                    "deleted_at": now(),
                    "is_online": 0
                }
            }
        )

        if result.modified_count == 0:
            flash("Employee not found or delete not allowed.", "danger")
            return redirect(url_for("admin.manage_employees"))

        flash("Employee removed successfully.", "success")

    except Exception as e:
        flash(f"Error deleting employee: {str(e)}", "danger")

    return redirect(url_for("admin.manage_employees"))


@admin_bp.route("/super-admin/company/edit/<company_id>", methods=["GET", "POST"])
def edit_company(company_id):
    if "user_id" not in session or session.get("user_role") != "super_admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    company = db.companies.find_one({
        "_id": oid(company_id),
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not company:
        flash("Company not found.", "danger")
        return redirect(url_for("admin.company_management"))

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        status = request.form.get("status", "").strip()
        admin_name = request.form.get("admin_name", "").strip()

        db.companies.update_one(
            {"_id": oid(company_id)},
            {
                "$set": {
                    "name": company_name,
                    "status": status,
                    "updated_at": now()
                }
            }
        )

        db.users.update_one(
            {
                "company_id": str(company.get("_id")),
                "role": "admin"
            },
            {
                "$set": {
                    "name": admin_name,
                    "updated_at": now()
                }
            }
        )

        flash("Company updated successfully.", "success")
        return redirect(url_for("admin.company_management"))

    admin = db.users.find_one({
        "company_id": str(company.get("_id")),
        "role": "admin"
    })

    company_data = {
        "id": str(company.get("_id")),
        "name": company.get("name", ""),
        "status": company.get("status", ""),
        "admin_name": admin.get("name", "") if admin else ""
    }

    return render_template("edit_company.html", company=company_data)


@admin_bp.route("/super-admin/company/delete/<company_id>", methods=["POST"])
def delete_company(company_id):
    if "user_id" not in session or session.get("user_role") != "super_admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    try:
        result = db.companies.update_one(
            {
                "_id": oid(company_id)
            },
            {
                "$set": {
                    "is_deleted": 1,
                    "deleted_at": now()
                }
            }
        )

        if result.modified_count == 0:
            flash("Company not found.", "danger")
            return redirect(url_for("admin.company_management"))

        flash("Company removed from list successfully.", "success")

    except Exception as e:
        flash(f"Error deleting company: {str(e)}", "danger")

    return redirect(url_for("admin.company_management"))




@admin_bp.route("/qr-employee/generate", methods=["GET", "POST"])
def qr_employee_generate():
    if "user_id" not in session or session.get("user_role") != "qr_employee":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    if request.method == "POST":
        product_name = request.form.get("product_name", "").strip()
        product_type = request.form.get("product_type", "").strip()

        try:
            coupon_count = int(request.form.get("coupon_count", 0) or 0)
        except:
            coupon_count = 0

        try:
            points = int(request.form.get("points", 0) or 0)
        except:
            points = 0

        if not product_name or not product_type or coupon_count <= 0 or points <= 0:
            flash("Please fill all fields correctly.", "danger")
            return redirect(url_for("admin.qr_employee_generate"))

        generated_count = 0

        for _ in range(coupon_count):
            code = generate_code(16)

            while db.coupons.find_one({"code": code}):
                code = generate_code(16)

            qr_data = request.host_url.rstrip("/") + f"/scan/{code}"
            filename = f"{code}.png"
            qr_path = generate_qr(qr_data, filename)

            db.coupons.insert_one({
                "code": code,
                "product_name": product_name,
                "product_type": product_type,
                "part_no": "",
                "mrp": 0,
                "dlp": 0,
                "pack_size": "",
                "points": points,
                "qr_size": "25x50",
                "qr_image": qr_path.replace("\\", "/"),
                "company_id": company_id,
                "created_by": session.get("user_id"),
                "status": "unused",
                "is_deleted": 0,
                "created_at": now()
            })

            generated_count += 1

        flash(f"{generated_count} coupons generated for {product_name}.", "success")
        return redirect(url_for("admin.coupon_list"))

    return render_template("qr_employee_generate.html")


@admin_bp.route("/employee/dashboard")
def general_employee_dashboard():

    if "user_id" not in session or session.get("user_role") != "employee":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    # Pending redemptions
    pending_redemptions = db.coupons.count_documents({
        "company_id": company_id,
        "scanned_at": {"$ne": None},
        "status": "scanned",
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    # Redeemed coupons
    redeemed_count = db.coupons.count_documents({
        "company_id": company_id,
        "status": {
            "$in": [
                "redeemed",
                "material_redeemed",
                "credit_note_issued",
                "credit_note"
            ]
        },
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    # Total dealers
    total_dealers = db.distributors.count_documents({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    # Wallet points
    pipeline = [
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$total_points"}
            }
        }
    ]

    wallet_result = list(db.dealer_wallets.aggregate(pipeline))
    total_wallet_points = wallet_result[0]["total"] if wallet_result else 0

    # Total scans
    total_scans = db.coupons.count_documents({
        "company_id": company_id,
        "scanned_at": {"$ne": None}
    })

    # Total coupons
    total_coupons = db.coupons.count_documents({
        "company_id": company_id
    })

    return render_template(
        "general_employee_dashboard.html",
        pending_redemptions=pending_redemptions,
        redeemed_count=redeemed_count,
        total_dealers=total_dealers,
        total_wallet_points=total_wallet_points,
        total_scans=total_scans,
        total_coupons=total_coupons
    )
@admin_bp.route("/qr-employee/dashboard")
def qr_employee_dashboard():

    if "user_id" not in session or session.get("user_role") != "qr_employee":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    return render_template("qr_employee_dashboard.html")
@admin_bp.route("/qr-employee/import-excel", methods=["GET", "POST"])
def import_excel_qr():
    if "user_id" not in session or session.get("user_role") != "qr_employee":
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        file = request.files.get("excel_file")

        if not file or file.filename == "":
            flash("Upload Excel file", "danger")
            return redirect(url_for("admin.import_excel_qr"))

        db = get_db()
        company_id = session.get("company_id")

        try:
            df = pd.read_excel(file)
            df.columns = [
                str(col).strip().lower().replace(" ", "_").replace(".", "").replace("/", "_")
                for col in df.columns
            ]

            generated_count = 0
            skipped_count = 0

            for _, row in df.iterrows():
                part_no = str(row.get("part_no", "")).strip()
                product_name = str(row.get("product_name", "")).strip()
                product_type = str(row.get("product_type", "Lubricant")).strip() or "Lubricant"
                pack_size = str(row.get("pack_size", "N/A")).strip() or "N/A"

                if not part_no or part_no.lower() == "nan":
                    skipped_count += 1
                    continue

                if not product_name or product_name.lower() == "nan":
                    skipped_count += 1
                    continue

                mrp = row.get("mrp", 0)
                dlp = row.get("dlp", 0)

                reward_value = (
                    row.get("coupon", 0)
                    or row.get("coupon_value", 0)
                    or row.get("points", 0)
                    or row.get("value", 0)
                )

                qr_size = str(row.get("qr_size", "25x50")).strip() or "25x50"

                excel_code = row.get("code", None)

                if excel_code is not None and not pd.isna(excel_code) and str(excel_code).strip() != "":
                    code = str(excel_code).strip().upper()
                else:
                    code = generate_code()

                while db.coupons.find_one({"code": code}):
                    code = generate_code()

                try:
                    if str(mrp).strip() == "***":
                        mrp = 0
                    mrp = float(mrp) if mrp not in ("", None) and not pd.isna(mrp) else 0
                except Exception:
                    mrp = 0

                try:
                    if str(dlp).strip() == "***":
                        dlp = 0
                    dlp = float(dlp) if dlp not in ("", None) and not pd.isna(dlp) else 0
                except Exception:
                    dlp = 0

                try:
                    reward_value = int(float(reward_value)) if reward_value not in ("", None) and not pd.isna(reward_value) else 0
                except Exception:
                    reward_value = 0

                qr_data = request.host_url.rstrip("/") + f"/scan/{code}"
                filename = f"{code}.png"
                qr_path = generate_qr(qr_data, filename)

                db.coupons.insert_one({
                    "code": code,
                    "product_name": product_name,
                    "product_type": product_type,
                    "part_no": part_no,
                    "mrp": mrp,
                    "dlp": dlp,
                    "pack_size": pack_size,
                    "points": reward_value,
                    "qr_size": qr_size,
                    "qr_image": qr_path.replace("\\", "/"),
                    "company_id": company_id,
                    "created_by": session.get("user_id"),
                    "status": "unused",
                    "is_deleted": 0,
                    "created_at": now()
                })

                generated_count += 1

            flash(f"Import complete. Generated: {generated_count}, Skipped: {skipped_count}", "success")
            return redirect(url_for("admin.coupon_list"))

        except Exception as e:
            flash(f"Excel import failed: {str(e)}", "danger")
            return redirect(url_for("admin.import_excel_qr"))

    return render_template("import_excel_qr.html")


@admin_bp.route("/qr-employee/coupons")
def coupon_list():

    if "user_id" not in session or session.get("user_role") != "qr_employee":
        return redirect(url_for("auth.login"))

    db = get_db()

    company_id = session.get("company_id")

    rows = db.coupons.find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    coupons = []

    for row in rows:

        coupons.append({
            "id": str(row.get("_id")),
            "code": row.get("code", ""),
            "product_name": row.get("product_name", ""),
            "product_type": row.get("product_type", ""),
            "part_no": row.get("part_no", ""),
            "mrp": row.get("mrp", 0),
            "dlp": row.get("dlp", 0),
            "pack_size": row.get("pack_size", ""),
            "points": row.get("points", 0),
            "qr_size": row.get("qr_size", "")
        })

    return render_template(
        "coupon_list.html",
        coupons=coupons
    )


@admin_bp.route("/coupon/edit/<id>", methods=["GET", "POST"])
def edit_coupon(id):

    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    db = get_db()

    coupon = db.coupons.find_one({
        "_id": oid(id)
    })

    if not coupon:
        flash("Coupon not found", "danger")
        return redirect(url_for("admin.coupon_list"))

    if request.method == "POST":

        product_name = request.form.get("product_name", "").strip()
        product_type = request.form.get("product_type", "").strip()
        part_no = request.form.get("part_no", "").strip()

        try:
            mrp = float(request.form.get("mrp", 0) or 0)
        except:
            mrp = 0

        try:
            dlp = float(request.form.get("dlp", 0) or 0)
        except:
            dlp = 0

        try:
            points = int(request.form.get("points", 0) or 0)
        except:
            points = 0

        pack_size = request.form.get("pack_size", "").strip()
        qr_size = request.form.get("qr_size", "").strip()

        db.coupons.update_one(
            {"_id": oid(id)},
            {
                "$set": {
                    "product_name": product_name,
                    "product_type": product_type,
                    "part_no": part_no,
                    "mrp": mrp,
                    "dlp": dlp,
                    "points": points,
                    "pack_size": pack_size,
                    "qr_size": qr_size,
                    "updated_at": now()
                }
            }
        )

        flash("Coupon updated successfully", "success")
        return redirect(url_for("admin.coupon_list"))

    coupon["_id"] = str(coupon["_id"])

    return render_template(
        "edit_coupon.html",
        coupon=coupon
    )


@admin_bp.route("/coupon/delete/<id>", methods=["POST"])
def delete_coupon(id):

    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    db = get_db()

    db.coupons.update_one(
        {"_id": oid(id)},
        {
            "$set": {
                "is_deleted": 1,
                "deleted_at": now()
            }
        }
    )

    flash("Coupon deleted successfully", "success")

    return redirect(url_for("admin.coupon_list"))

@admin_bp.route("/company-admin/employee/edit/<employee_id>", methods=["GET", "POST"])
def edit_employee(employee_id):

    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    try:
        employee_obj_id = ObjectId(employee_id)
    except:
        flash("Invalid employee ID.", "danger")
        return redirect(url_for("admin.manage_employees"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        allowed_roles = ["employee", "qr_employee", "sales"]

        if not name or not email or not role:
            flash("Please fill all required fields.", "danger")
            return redirect(url_for("admin.edit_employee", employee_id=employee_id))

        if role not in allowed_roles:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("admin.edit_employee", employee_id=employee_id))

        try:

            # same email kisi aur employee ka na ho
            existing_email = db.users.find_one({
                "email": email,
                "_id": {"$ne": employee_obj_id},
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            })

            if existing_email:
                flash("This email is already used by another user.", "danger")
                return redirect(url_for("admin.edit_employee", employee_id=employee_id))

            update_data = {
                "name": name,
                "email": email,
                "role": role
            }

            # password diya hai to password bhi update karo
            if password:
                update_data["password"] = generate_password_hash(password)

            result = db.users.update_one(
                {
                    "_id": employee_obj_id,
                    "company_id": company_id,
                    "role": {
                        "$in": ["employee", "qr_employee", "sales"]
                    },
                    "$or": [
                        {"is_deleted": 0},
                        {"is_deleted": False},
                        {"is_deleted": {"$exists": False}},
                        {"is_deleted": None}
                    ]
                },
                {
                    "$set": update_data
                }
            )

            if result.matched_count == 0:
                flash("Employee not found or update not allowed.", "danger")
                return redirect(url_for("admin.manage_employees"))

            flash("Employee updated successfully.", "success")
            return redirect(url_for("admin.manage_employees"))

        except Exception as e:
            flash(f"Error updating employee: {str(e)}", "danger")
            return redirect(url_for("admin.edit_employee", employee_id=employee_id))

    # GET request ke liye employee fetch karo
    employee = db.users.find_one({
        "_id": employee_obj_id,
        "company_id": company_id,
        "role": {
            "$in": ["employee", "qr_employee", "sales"]
        },
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not employee:
        flash("Employee not found.", "danger")
        return redirect(url_for("admin.manage_employees"))

    employee_data = {
        "id": str(employee.get("_id")),
        "name": employee.get("name", ""),
        "email": employee.get("email", ""),
        "role": employee.get("role", "")
    }

    return render_template(
        "edit_employee.html",
        employee=employee_data
    )



import qrcode
import base64
from flask import render_template, request, redirect, url_for, flash, session, current_app

@admin_bp.route("/qr-employee/coupon-generator", methods=["GET", "POST"])
def coupon_generator():

    if "user_id" not in session or session.get("user_role") != "qr_employee":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    search_text = ""
    selected_qr_size = "25x50"
    brand_name = ""
    count = 10

    pipeline = [
        {
            "$match": {
                "company_id": company_id,
                "part_no": {"$nin": [None, ""]},
                "product_name": {"$nin": [None, ""]},
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            }
        },
        {
            "$group": {
                "_id": "$part_no",
                "product_name": {"$first": "$product_name"}
            }
        },
        {"$sort": {"_id": 1}}
    ]

    parts = []
    for item in db.coupons.aggregate(pipeline):
        parts.append((item.get("_id", ""), item.get("product_name", "")))

    if request.method == "POST":
        search_text = request.form.get("search_text", "").strip()
        selected_qr_size = request.form.get("qr_size", "25x50").strip()
        brand_name = request.form.get("brand_name", "").strip()

        try:
            count = int(request.form.get("count", 10) or 10)
            if count <= 0:
                count = 1
        except:
            count = 1

        if not search_text:
            flash("Please select part number.", "danger")
            return redirect(url_for("admin.coupon_generator"))

        product = db.coupons.find_one(
            {
                "company_id": company_id,
                "part_no": search_text,
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            },
            sort=[("_id", -1)]
        )

        if not product:
            flash("No product found.", "danger")
            return redirect(url_for("admin.coupon_generator"))

        part_no = product.get("part_no", "")
        product_name = product.get("product_name", "")
        product_type = product.get("product_type", "")
        mrp = float(product.get("mrp") or 0)
        dlp = float(product.get("dlp") or 0)
        pack_size = product.get("pack_size", "")
        points = int(product.get("points") or 0)

        zpl_batch = ""

        try:
            generated_count = 0

            for _ in range(count):
                code = generate_code(16)

                while db.coupons.find_one({"code": code}):
                    code = generate_code(16)

                qr_data = request.host_url.rstrip("/") + f"/scan/{code}"
                filename = f"{code}.png"
                qr_path = generate_qr(qr_data, filename)

                db.coupons.insert_one({
                    "code": code,
                    "product_name": product_name,
                    "product_type": product_type,
                    "part_no": part_no,
                    "mrp": mrp,
                    "dlp": dlp,
                    "pack_size": pack_size,
                    "points": points,
                    "qr_size": selected_qr_size,
                    "qr_image": qr_path.replace("\\", "/"),
                    "company_id": company_id,
                    "created_by": session.get("user_id"),
                    "status": "unused",
                    "is_deleted": 0,
                    "created_at": now()
                })

                zpl_batch += build_coupon_zpl(
                    part_no=part_no,
                    mrp=mrp,
                    pack_size=pack_size,
                    points=points,
                    code=code,
                    brand_name=brand_name,
                    qr_size=selected_qr_size
                )

                generated_count += 1

            db.print_jobs.insert_one({
                "company_id": company_id,
                "printer_name": "TSC TE244",
                "raw_data": zpl_batch,
                "status": "pending",
                "created_by": session.get("user_id"),
                "created_at": now()
            })

            flash(f"{generated_count} coupons generated & sent to print queue!", "success")

        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

        return redirect(url_for("admin.coupon_generator"))

    print_jobs = list(
        db.print_jobs.find({
            "company_id": company_id
        }).sort("_id", -1).limit(20)
    )

    return render_template(
        "coupon_generator.html",
        parts=parts,
        brand_name=brand_name,
        selected_qr_size=selected_qr_size,
        count=count,
        search_text=search_text,
        coupon=None,
        print_jobs=print_jobs
    )






@admin_bp.route("/company-admin/analytics")
def company_admin_analytics():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    base_query = {
        "company_id": company_id,
        "is_deleted": 0
    }

    total_generated = db.coupons.count_documents(base_query)

    total_points_generated = sum(
        int(c.get("points") or 0)
        for c in db.coupons.find(base_query, {"points": 1})
    )

    scanned_query = {
        **base_query,
        "scanned_at": {"$exists": True, "$ne": None}
    }

    total_scanned = db.coupons.count_documents(scanned_query)

    total_points_scanned = sum(
        int(c.get("points") or 0)
        for c in db.coupons.find(scanned_query, {"points": 1})
    )

    redeemed_query = {
        **base_query,
        "status": "redeemed"
    }

    total_redeemed = db.coupons.count_documents(redeemed_query)

    total_points_redeemed = sum(
        int(c.get("points") or 0)
        for c in db.coupons.find(redeemed_query, {"points": 1})
    )

    scanned_not_redeemed_query = {
        **base_query,
        "scanned_at": {"$exists": True, "$ne": None},
        "status": "scanned"
    }

    scanned_not_redeemed = db.coupons.count_documents(scanned_not_redeemed_query)

    points_scanned_not_redeemed = sum(
        int(c.get("points") or 0)
        for c in db.coupons.find(scanned_not_redeemed_query, {"points": 1})
    )

    generated_by_user = []
    pipeline_generated = [
        {"$match": base_query},
        {
            "$group": {
                "_id": "$created_by",
                "count": {"$sum": 1},
                "points": {"$sum": {"$toInt": "$points"}}
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 15}
    ]

    for r in db.coupons.aggregate(pipeline_generated):
        generated_by_user.append((
            str(r.get("_id") or "Unknown"),
            r.get("count", 0),
            r.get("points", 0)
        ))

    scanned_by_user = []
    pipeline_scanned = [
        {
            "$match": {
                **base_query,
                "scanned_at": {"$exists": True, "$ne": None},
                "status": {"$in": ["scanned", "redeemed"]}
            }
        },
        {
            "$group": {
                "_id": "$scanned_by",
                "count": {"$sum": 1},
                "points": {"$sum": {"$toInt": "$points"}}
            }
        },
        {"$sort": {"count": -1}}
    ]

    for r in db.coupons.aggregate(pipeline_scanned):
        dealer = db.distributors.find_one({"_id": oid(r.get("_id"))})
        dealer_name = dealer.get("name", "Unknown") if dealer else "Unknown"

        scanned_by_user.append((
            dealer_name,
            r.get("count", 0),
            r.get("points", 0)
        ))

    return render_template(
        "company_admin_analytics.html",
        total_generated=total_generated,
        total_points_generated=total_points_generated,
        total_scanned=total_scanned,
        total_points_scanned=total_points_scanned,
        total_redeemed=total_redeemed,
        total_points_redeemed=total_points_redeemed,
        scanned_not_redeemed=scanned_not_redeemed,
        points_scanned_not_redeemed=points_scanned_not_redeemed,
        generated_by_user=generated_by_user,
        scanned_by_user=scanned_by_user
    )


@admin_bp.route("/company-admin/history")
def company_admin_history():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    rows = db.coupons.find({
        "company_id": company_id,
        "is_deleted": 0
    }).sort("_id", -1).limit(300)

    history_rows = []

    for c in rows:
        created_at = c.get("created_at")
        scanned_at = c.get("scanned_at")
        redeemed_at = c.get("redeemed_at")

        history_rows.append((
            str(c.get("_id")),
            c.get("code", ""),
            c.get("product_name", ""),
            c.get("part_no", ""),
            c.get("pack_size", ""),
            int(c.get("points") or 0),
            c.get("status", ""),
            created_at.date() if created_at else "",
            scanned_at.date() if scanned_at else "",
            redeemed_at.date() if redeemed_at else ""
        ))

    return render_template(
        "company_admin_history.html",
        history_rows=history_rows
    )

@admin_bp.route("/company-admin/dashboard")
def company_admin_dashboard():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    if session.get("user_role") != "admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    expired_redirect = block_if_trial_company_expired()
    if expired_redirect:
        return expired_redirect

    db = get_db()
    company_id = session.get("company_id")

    active_filter = {
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }

    employee_count = db.users.count_documents({
        "company_id": company_id,
        "role": {"$in": ["employee", "qr_employee", "redeem_employee", "sales"]},
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    distributor_count = db.distributors.count_documents(active_filter)
    retailer_count = db.retailers.count_documents(active_filter)
    mechanic_count = db.mechanics.count_documents(active_filter)
    catalogue_count = db.catalogues.count_documents(active_filter)

    product_pipeline = [
        {
            "$match": {
                "company_id": company_id,
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ],
                "part_no": {"$nin": [None, ""]},
                "product_name": {"$nin": [None, ""]}
            }
        },
        {
            "$group": {
                "_id": {
                    "part_no": "$part_no",
                    "product_name": "$product_name",
                    "product_type": "$product_type",
                    "pack_size": "$pack_size",
                    "mrp": "$mrp",
                    "dlp": "$dlp",
                    "points": "$points",
                    "qr_size": "$qr_size"
                }
            }
        },
        {"$count": "count"}
    ]

    product_result = list(db.coupons.aggregate(product_pipeline))
    product_count = product_result[0]["count"] if product_result else 0

    total_generated = db.coupons.count_documents(active_filter)

    total_scans = db.coupons.count_documents({
        **active_filter,
        "scanned_at": {"$exists": True, "$ne": None}
    })

    redeemed_count = db.coupons.count_documents({
        **active_filter,
        "status": {
            "$in": [
                "redeemed",
                "material_redeemed",
                "credit_note_issued",
                "set_redeemed",
                "credit_note"
            ]
        }
    })

    pending_count = db.coupons.count_documents({
        **active_filter,
        "scanned_at": {"$exists": True, "$ne": None},
        "$or": [
            {"status": "scanned"},
            {"status": "pending"},
            {"is_redeemed": 0},
            {"is_redeemed": False},
            {"is_redeemed": {"$exists": False}},
            {"is_redeemed": None}
        ]
    })

    return render_template(
        "company_admin_dashboard.html",
        employee_count=employee_count,
        distributor_count=distributor_count,
        retailer_count=retailer_count,
        mechanic_count=mechanic_count,
        product_count=product_count,
        catalogue_count=catalogue_count,
        total_generated=total_generated,
        total_scans=total_scans,
        redeemed_count=redeemed_count,
        pending_count=pending_count
    )


@admin_bp.route("/company-admin/employees")
def company_admin_employees_page():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    return render_template("company_admin_employees.html")


@admin_bp.route("/company-admin/distributors")
def company_admin_distributors_page():

    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    company_id = session.get("company_id")
    user_role = session.get("user_role")
    user_id = session.get("user_id")

    query = {
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }

    if user_role == "sales":
        query["salesman_id"] = user_id

    rows = db.distributors.find(query).sort("_id", -1)

    distributors = []

    for row in rows:

        distributors.append({
            "id": str(row.get("_id")),
            "dealer_code": row.get("dealer_code", ""),
            "name": row.get("name", ""),
            "mobile": row.get("mobile", ""),
            "email": row.get("email", ""),
            "pan": row.get("pan", ""),
            "gst": row.get("gst", ""),
            "city": row.get("city", ""),
            "state": row.get("state", ""),
            "address": row.get("address", "")
        })

    return render_template(
        "company_admin_distributors.html",
        distributors=distributors
    )

@admin_bp.route("/company-admin/distributors/add", methods=["POST"])
def add_distributor():
    if "user_id" not in session or session.get("user_role") not in ["admin", "sales"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    dealer_code = request.form.get("dealer_code", "").strip()
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    pan = request.form.get("pan", "").strip().upper()
    gst = request.form.get("gst", "").strip().upper()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip()
    address = request.form.get("address", "").strip()

    if not dealer_code or not name:
        flash("Dealer code and name are required.", "danger")
        return redirect(url_for("admin.company_admin_distributors_page"))

    hashed_password = generate_password_hash(password) if password else None

    existing = db.distributors.find_one({
        "dealer_code": dealer_code,
        "company_id": company_id
    })

    if existing:
        is_deleted = existing.get("is_deleted", 0)

        if is_deleted == 0 or is_deleted is False or is_deleted is None:
            flash("Dealer code already exists. Please use a different code.", "danger")
            return redirect(url_for("admin.company_admin_distributors_page"))

        db.distributors.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "name": name,
                    "mobile": mobile,
                    "email": email,
                    "password": hashed_password,
                    "pan": pan,
                    "gst": gst,
                    "city": city,
                    "state": state,
                    "address": address,
                    "is_deleted": 0,
                    "updated_at": now()
                }
            }
        )

        flash("Previously deleted distributor restored successfully.", "success")
        return redirect(url_for("admin.company_admin_distributors_page"))

    if email:
        existing_email = db.distributors.find_one({
            "email": email,
            "company_id": company_id,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing_email:
            flash("Email already exists. Please use a different email.", "danger")
            return redirect(url_for("admin.company_admin_distributors_page"))

    db.distributors.insert_one({
        "dealer_code": dealer_code,
        "name": name,
        "mobile": mobile,
        "email": email,
        "password": hashed_password,
        "pan": pan,
        "gst": gst,
        "city": city,
        "state": state,
        "address": address,
        "company_id": company_id,
        "salesman_id": session.get("user_id") if session.get("user_role") == "sales" else None,
        "is_deleted": 0,
        "created_at": now()
    })

    flash("Distributor added successfully.", "success")
    return redirect(url_for("admin.company_admin_distributors_page"))
    



@admin_bp.route("/company-admin/retailers/add", methods=["POST"])
def add_retailer():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    dealer_code = request.form.get("dealer_code", "").strip()
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    pan = request.form.get("pan", "").strip().upper()
    gst = request.form.get("gst", "").strip().upper()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip()
    address = request.form.get("address", "").strip()

    hashed_password = generate_password_hash(password) if password else None

    db.retailers.insert_one({
        "dealer_code": dealer_code,
        "name": name,
        "mobile": mobile,
        "email": email,
        "password": hashed_password,
        "pan": pan,
        "gst": gst,
        "city": city,
        "state": state,
        "address": address,
        "company_id": company_id,
        "is_deleted": 0,
        "created_at": now()
    })

    flash("Retailer added successfully.", "success")
    return redirect(url_for("admin.company_admin_retailers_page"))


@admin_bp.route("/company-admin/mechanics")
def company_admin_mechanics_page():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    rows = db.mechanics.find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    mechanics = []

    for row in rows:
        mechanics.append({
            "id": str(row.get("_id")),
            "dealer_code": row.get("dealer_code", ""),
            "name": row.get("name", ""),
            "mobile": row.get("mobile", ""),
            "email": row.get("email", ""),
            "pan": row.get("pan", ""),
            "gst": row.get("gst", ""),
            "city": row.get("city", ""),
            "state": row.get("state", ""),
            "address": row.get("address", "")
        })

    return render_template("company_admin_mechanics.html", mechanics=mechanics)

@admin_bp.route("/company-admin/mechanics/add", methods=["POST"])
def add_mechanic():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    dealer_code = request.form.get("dealer_code", "").strip()
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    pan = request.form.get("pan", "").strip().upper()
    gst = request.form.get("gst", "").strip().upper()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip()
    address = request.form.get("address", "").strip()

    hashed_password = generate_password_hash(password) if password else None

    db.mechanics.insert_one({
        "dealer_code": dealer_code,
        "name": name,
        "mobile": mobile,
        "email": email,
        "password": hashed_password,
        "pan": pan,
        "gst": gst,
        "city": city,
        "state": state,
        "address": address,
        "company_id": company_id,
        "is_deleted": 0,
        "created_at": now()
    })

    flash("Mechanic added successfully.", "success")
    return redirect(url_for("admin.company_admin_mechanics_page"))

@admin_bp.route("/company-admin/products")
def company_admin_products_page():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    pipeline = [
        {
            "$match": {
                "company_id": company_id,
                "is_deleted": 0,
                "part_no": {"$nin": [None, ""]},
                "product_name": {"$nin": [None, ""]}
            }
        },
        {
            "$group": {
                "_id": {
                    "part_no": "$part_no",
                    "product_name": "$product_name",
                    "product_type": "$product_type",
                    "pack_size": "$pack_size",
                    "mrp": "$mrp",
                    "dlp": "$dlp",
                    "points": "$points",
                    "qr_size": "$qr_size"
                },
                "id": {"$first": "$_id"},
                "total_coupons": {"$sum": 1}
            }
        },
        {"$sort": {"id": -1}}
    ]

    products = []

    for r in db.coupons.aggregate(pipeline):
        item = r["_id"]
        products.append({
            "id": str(r["id"]),
            "part_no": item.get("part_no", ""),
            "product_name": item.get("product_name", ""),
            "product_type": item.get("product_type", ""),
            "pack_size": item.get("pack_size", ""),
            "mrp": item.get("mrp", 0),
            "dlp": item.get("dlp", 0),
            "points": item.get("points", 0),
            "qr_size": item.get("qr_size", ""),
            "total_coupons": r.get("total_coupons", 0)
        })

    return render_template("company_admin_products.html", products=products)

    
@admin_bp.route("/company-admin/products/export")
def export_products():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    rows = db.coupons.find({
        "company_id": company_id,
        "is_deleted": 0,
        "part_no": {"$nin": [None, ""]},
        "product_name": {"$nin": [None, ""]}
    })

    data = []
    seen = set()

    for r in rows:
        key = (
            r.get("part_no", ""),
            r.get("product_name", ""),
            r.get("product_type", ""),
            r.get("pack_size", ""),
            r.get("mrp", 0),
            r.get("dlp", 0),
            r.get("points", 0)
        )

        if key in seen:
            continue

        seen.add(key)

        data.append({
            "part_no": key[0],
            "product_name": key[1],
            "product_type": key[2],
            "pack_size": key[3],
            "mrp": key[4],
            "dlp": key[5],
            "points": key[6]
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Products")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="products.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@admin_bp.route("/company-admin/products/import", methods=["POST"])
def import_products():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    file = request.files.get("excel_file")

    if not file or file.filename == "":
        flash("No file selected", "danger")
        return redirect(url_for("admin.company_admin_products_page"))

    db = get_db()
    company_id = session.get("company_id")

    try:
        df = pd.read_excel(file)

        df.columns = [
            str(col).strip().lower().replace(" ", "_").replace(".", "").replace("/", "_")
            for col in df.columns
        ]

        imported = 0
        skipped = 0

        for _, row in df.iterrows():
            part_no = str(row.get("part_no", "")).strip()
            product_name = str(row.get("product_name", "")).strip()
            product_type = str(row.get("product_type", "Lubricant")).strip() or "Lubricant"
            pack_size = str(row.get("pack_size", "")).strip()

            if not part_no or part_no.lower() == "nan":
                skipped += 1
                continue

            if not product_name or product_name.lower() == "nan":
                skipped += 1
                continue

            try:
                mrp = float(row.get("mrp", 0) or 0)
            except:
                mrp = 0

            try:
                dlp = float(row.get("dlp", 0) or 0)
            except:
                dlp = 0

            try:
                points = int(float(row.get("points", row.get("coupon", 0)) or 0))
            except:
                points = 0

            qr_size = str(row.get("qr_size", "25x50")).strip() or "25x50"

            code = generate_code(16)
            while db.coupons.find_one({"code": code}):
                code = generate_code(16)

            qr_data = request.host_url.rstrip("/") + f"/scan/{code}"
            filename = f"{code}.png"
            qr_path = generate_qr(qr_data, filename)

            db.coupons.insert_one({
                "code": code,
                "product_name": product_name,
                "product_type": product_type,
                "part_no": part_no,
                "mrp": mrp,
                "dlp": dlp,
                "pack_size": pack_size,
                "points": points,
                "qr_size": qr_size,
                "qr_image": qr_path.replace("\\", "/"),
                "company_id": company_id,
                "created_by": session.get("user_id"),
                "status": "unused",
                "is_deleted": 0,
                "created_at": now()
            })

            imported += 1

        flash(f"Products imported successfully. Imported: {imported}, Skipped: {skipped}", "success")

    except Exception as e:
        flash(f"Import failed: {str(e)}", "danger")

    return redirect(url_for("admin.company_admin_products_page"))

@admin_bp.route("/company-admin/export-all-data")
def export_all_data():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        products_data = []
        seen = set()

        for r in db.coupons.find({"company_id": company_id, "is_deleted": 0}):
            key = (
                r.get("part_no", ""),
                r.get("product_name", ""),
                r.get("product_type", ""),
                r.get("pack_size", ""),
                r.get("mrp", 0),
                r.get("dlp", 0),
                r.get("points", 0),
                r.get("qr_size", "")
            )

            if key in seen:
                continue

            seen.add(key)

            products_data.append({
                "part_no": key[0],
                "product_name": key[1],
                "product_type": key[2],
                "pack_size": key[3],
                "mrp": key[4],
                "dlp": key[5],
                "points": key[6],
                "qr_size": key[7]
            })

        pd.DataFrame(products_data).to_excel(writer, index=False, sheet_name="Products")

        distributors_data = []
        for r in db.distributors.find({"company_id": company_id}):
            distributors_data.append({
                "dealer_code": r.get("dealer_code", ""),
                "name": r.get("name", ""),
                "mobile": r.get("mobile", ""),
                "email": r.get("email", ""),
                "pan": r.get("pan", ""),
                "gst": r.get("gst", ""),
                "city": r.get("city", ""),
                "state": r.get("state", ""),
                "address": r.get("address", "")
            })

        pd.DataFrame(distributors_data).to_excel(writer, index=False, sheet_name="Distributors")

        retailers_data = []
        for r in db.retailers.find({"company_id": company_id}):
            retailers_data.append({
                "dealer_code": r.get("dealer_code", ""),
                "name": r.get("name", ""),
                "mobile": r.get("mobile", ""),
                "email": r.get("email", ""),
                "pan": r.get("pan", ""),
                "gst": r.get("gst", ""),
                "city": r.get("city", ""),
                "state": r.get("state", ""),
                "address": r.get("address", "")
            })

        pd.DataFrame(retailers_data).to_excel(writer, index=False, sheet_name="Retailers")

        mechanics_data = []
        for r in db.mechanics.find({"company_id": company_id}):
            mechanics_data.append({
                "dealer_code": r.get("dealer_code", ""),
                "name": r.get("name", ""),
                "mobile": r.get("mobile", ""),
                "email": r.get("email", ""),
                "pan": r.get("pan", ""),
                "gst": r.get("gst", ""),
                "city": r.get("city", ""),
                "state": r.get("state", ""),
                "address": r.get("address", "")
            })

        pd.DataFrame(mechanics_data).to_excel(writer, index=False, sheet_name="Mechanics")

        coupons_data = []
        for r in db.coupons.find({"company_id": company_id}):
            coupons_data.append({
                "id": str(r.get("_id")),
                "code": r.get("code", ""),
                "product_name": r.get("product_name", ""),
                "product_type": r.get("product_type", ""),
                "part_no": r.get("part_no", ""),
                "mrp": r.get("mrp", 0),
                "dlp": r.get("dlp", 0),
                "pack_size": r.get("pack_size", ""),
                "points": r.get("points", 0),
                "qr_size": r.get("qr_size", ""),
                "status": r.get("status", ""),
                "dealer_id": r.get("dealer_id", ""),
                "scanned_by": r.get("scanned_by", ""),
                "created_at": str(r.get("created_at", "")),
                "scanned_at": str(r.get("scanned_at", "")),
                "redeemed_at": str(r.get("redeemed_at", ""))
            })

        pd.DataFrame(coupons_data).to_excel(writer, index=False, sheet_name="Coupons")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="all_company_data.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@admin_bp.route("/company-admin/products/add", methods=["POST"])
def add_product():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    part_no = request.form.get("part_no", "").strip()
    product_name = request.form.get("product_name", "").strip()
    product_type = request.form.get("product_type", "").strip()
    pack_size = request.form.get("pack_size", "").strip()

    try:
        mrp = float(request.form.get("mrp", 0) or 0)
    except:
        mrp = 0

    try:
        dlp = float(request.form.get("dlp", 0) or 0)
    except:
        dlp = 0

    try:
        points = int(request.form.get("points", 0) or 0)
    except:
        points = 0

    if not part_no or not product_name:
        flash("Part No and Product Name are required.", "danger")
        return redirect(url_for("admin.company_admin_products_page"))

    code = generate_code(16)
    while db.coupons.find_one({"code": code}):
        code = generate_code(16)

    qr_data = request.host_url.rstrip("/") + f"/scan/{code}"
    filename = f"{code}.png"
    qr_path = generate_qr(qr_data, filename)

    db.coupons.insert_one({
        "code": code,
        "product_name": product_name,
        "product_type": product_type,
        "part_no": part_no,
        "mrp": mrp,
        "dlp": dlp,
        "pack_size": pack_size,
        "points": points,
        "qr_size": "25x50",
        "qr_image": qr_path.replace("\\", "/"),
        "company_id": company_id,
        "created_by": session.get("user_id"),
        "status": "unused",
        "is_deleted": 0,
        "created_at": now()
    })

    flash("Product added successfully.", "success")
    return redirect(url_for("admin.company_admin_products_page"))



@admin_bp.route("/company-admin/banners")
def company_admin_banners_page():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    rows = db.banners.find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    banners = []

    for row in rows:
        banners.append((
            str(row.get("_id")),
            row.get("title", ""),
            row.get("image", "")
        ))

    return render_template("company_admin_banners.html", banners=banners)


@admin_bp.route("/company-admin/banners/add", methods=["POST"])
def add_banner():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    title = request.form.get("title", "").strip()
    image = request.files.get("image")

    if not title or not image or image.filename == "":
        flash("Please provide banner title and image.", "danger")
        return redirect(url_for("admin.company_admin_banners_page"))

    upload_folder = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(upload_folder, exist_ok=True)

    original_filename = secure_filename(image.filename)
    ext = os.path.splitext(original_filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"

    save_path = os.path.join(upload_folder, unique_filename)
    image.save(save_path)

    db.banners.insert_one({
        "title": title,
        "image": unique_filename,
        "company_id": company_id,
        "is_deleted": 0,
        "is_active": 1,
        "created_at": now()
    })

    flash("Banner added successfully.", "success")
    return redirect(url_for("admin.company_admin_banners_page"))


@admin_bp.route("/company-admin/banners/delete/<banner_id>", methods=["POST"])
def delete_banner(banner_id):

    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    try:
        banner_obj_id = ObjectId(banner_id)
    except:
        flash("Invalid banner ID.", "danger")
        return redirect(url_for("admin.company_admin_banners_page"))

    banner = db.banners.find_one({
        "_id": banner_obj_id,
        "company_id": company_id
    })

    if banner:

        image_filename = banner.get("image", "")

        image_path = os.path.join(
            current_app.root_path,
            "static",
            "uploads",
            image_filename
        )

        # Soft delete
        db.banners.update_one(
            {
                "_id": banner_obj_id,
                "company_id": company_id
            },
            {
                "$set": {
                    "is_deleted": 1,
                    "deleted_at": now()
                }
            }
        )

        # optional physical delete
        if image_filename and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception:
                pass

    flash("Banner deleted successfully.", "success")
    return redirect(url_for("admin.company_admin_banners_page"))


@admin_bp.route("/company-admin/catalogues")
def company_admin_catalogues_page():

    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    rows = db.catalogues.find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    catalogues = []

    for row in rows:
        catalogues.append({
            "id": str(row.get("_id")),
            "title": row.get("title", ""),
            "file_name": row.get("file_name", ""),
            "file_path": row.get("file_path", ""),
            "created_at": row.get("created_at")
        })

    return render_template(
        "company_admin_catalogues.html",
        catalogues=catalogues
    )

@admin_bp.route("/company-admin/catalogues/add", methods=["POST"])
def add_catalogue():

    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    title = request.form.get("title", "").strip()
    pdf_file = request.files.get("pdf_file")

    if not title or not pdf_file:
        flash("Title and PDF file are required.", "danger")
        return redirect(url_for("admin.company_admin_catalogues_page"))

    if not pdf_file.filename.lower().endswith(".pdf"):
        flash("Only PDF files are allowed.", "danger")
        return redirect(url_for("admin.company_admin_catalogues_page"))

    original_filename = secure_filename(pdf_file.filename)

    # unique filename
    unique_filename = f"{uuid.uuid4().hex}_{original_filename}"

    upload_folder = os.path.join(
        current_app.root_path,
        "static",
        "catalogues"
    )

    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, unique_filename)

    pdf_file.save(file_path)

    db_path = f"catalogues/{unique_filename}"

    db.catalogues.insert_one({
        "title": title,
        "file_name": unique_filename,
        "file_path": db_path,
        "company_id": company_id,
        "is_deleted": 0,
        "created_by": session.get("user_id"),
        "created_at": now()
    })

    flash("Catalogue uploaded successfully.", "success")
    return redirect(url_for("admin.company_admin_catalogues_page"))

@admin_bp.route("/company-admin/catalogues/delete/<catalogue_id>", methods=["POST"])
def delete_catalogue(catalogue_id):

    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    try:
        catalogue_obj_id = ObjectId(catalogue_id)
    except:
        flash("Invalid catalogue ID.", "danger")
        return redirect(url_for("admin.company_admin_catalogues_page"))

    db.catalogues.update_one(
        {"_id": catalogue_obj_id},
        {
            "$set": {
                "is_deleted": 1,
                "deleted_at": now()
            }
        }
    )

    flash("Catalogue deleted successfully.", "success")
    return redirect(url_for("admin.company_admin_catalogues_page"))


@admin_bp.route("/salesman/dashboard")
def salesman_dashboard():

    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    salesman_id = session["user_id"]

    active_filter = {
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }

    total_dealers = db.distributors.count_documents({
        "salesman_id": salesman_id,
        **active_filter
    })

    total_orders = db.dealer_orders.count_documents({
        "salesman_id": salesman_id
    })

    pending_orders = db.dealer_orders.count_documents({
        "salesman_id": salesman_id,
        "order_status": "pending"
    })

    completed_orders = db.dealer_orders.count_documents({
        "salesman_id": salesman_id,
        "order_status": "completed"
    })

    return render_template(
        "salesman_dashboard.html",
        total_dealers=total_dealers,
        total_orders=total_orders,
        pending_orders=pending_orders,
        completed_orders=completed_orders
    )


@admin_bp.route("/salesman/dealers")
def salesman_dealers():

    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    salesman_id = session["user_id"]

    rows = db.distributors.find({
        "salesman_id": salesman_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    dealers = []

    for row in rows:
        dealers.append((
            str(row.get("_id")),
            row.get("dealer_code", ""),
            row.get("name", ""),
            row.get("mobile", ""),
            row.get("email", ""),
            row.get("city", ""),
            row.get("state", ""),
            row.get("address", "")
        ))

    return render_template(
        "salesman_dealers.html",
        dealers=dealers
    )

@admin_bp.route("/salesman/dealers/add", methods=["GET", "POST"])
def salesman_add_dealer():

    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    if request.method == "POST":

        dealer_code = request.form.get("dealer_code", "").strip()
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        pan = request.form.get("pan", "").strip().upper()
        gst = request.form.get("gst", "").strip().upper()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        address = request.form.get("address", "").strip()

        if not dealer_code or not name:
            flash("Dealer code and name are required.", "danger")
            return redirect(url_for("admin.salesman_add_dealer"))

        existing = db.distributors.find_one({
            "dealer_code": dealer_code,
            "company_id": session.get("company_id"),
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing:
            flash("Dealer code already exists.", "danger")
            return redirect(url_for("admin.salesman_add_dealer"))

        hashed_password = generate_password_hash(password) if password else None

        db.distributors.insert_one({
            "dealer_code": dealer_code,
            "name": name,
            "mobile": mobile,
            "email": email,
            "password": hashed_password,
            "pan": pan,
            "gst": gst,
            "city": city,
            "state": state,
            "address": address,
            "company_id": session.get("company_id"),
            "salesman_id": session.get("user_id"),
            "is_deleted": 0,
            "created_at": now()
        })

        flash("Dealer created successfully.", "success")
        return redirect(url_for("admin.salesman_dealers"))

    return render_template("salesman_add_dealer.html")


@admin_bp.route("/salesman/orders")
def salesman_orders():

    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    salesman_id = session.get("user_id")

    rows = db.dealer_orders.find({
        "salesman_id": salesman_id
    }).sort("_id", -1)

    orders = []

    for order in rows:
        dealer_name = "N/A"

        dealer_id = order.get("dealer_id")
        if dealer_id:
            dealer = db.distributors.find_one({"_id": oid(dealer_id)})
            if dealer:
                dealer_name = dealer.get("name", "N/A")

        orders.append((
            str(order.get("_id")),
            order.get("order_no", ""),
            dealer_name,
            order.get("part_no", ""),
            order.get("part_name", ""),
            order.get("order_status", ""),
            order.get("total_amount", 0),
            order.get("created_at", "")
        ))

    return render_template("salesman_orders.html", orders=orders)


def generate_order_no():
    return "ORD-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


@admin_bp.route("/salesman/orders/create", methods=["GET", "POST"])
def salesman_create_order():

    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    salesman_id = session.get("user_id")
    company_id = session.get("company_id")

    if request.method == "POST":
        dealer_id = request.form.get("dealer_id", "").strip()
        product_part_no = request.form.get("product_part_no", "").strip()
        product_name = request.form.get("product_name", "").strip()

        try:
            qty = int(request.form.get("qty", 1) or 1)
        except:
            qty = 1

        try:
            rate = float(request.form.get("rate", 0) or 0)
        except:
            rate = 0

        try:
            amount = float(request.form.get("amount", 0) or 0)
        except:
            amount = qty * rate

        remarks = request.form.get("remarks", "").strip()

        if not dealer_id:
            flash("Dealer is required.", "danger")
            return redirect(url_for("admin.salesman_create_order"))

        if not product_part_no:
            flash("Part number is required.", "danger")
            return redirect(url_for("admin.salesman_create_order"))

        if not product_name:
            flash("Part name is required.", "danger")
            return redirect(url_for("admin.salesman_create_order"))

        dealer = db.distributors.find_one({
            "_id": oid(dealer_id),
            "salesman_id": salesman_id,
            "company_id": company_id,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if not dealer:
            flash("Dealer not found or not assigned to you.", "danger")
            return redirect(url_for("admin.salesman_create_order"))

        order_no = generate_order_no()

        order_result = db.dealer_orders.insert_one({
            "dealer_id": dealer_id,
            "salesman_id": salesman_id,
            "company_id": company_id,
            "order_no": order_no,
            "part_no": product_part_no,
            "part_name": product_name,
            "order_status": "pending",
            "total_amount": amount,
            "remarks": remarks,
            "created_at": now()
        })

        db.dealer_order_items.insert_one({
            "order_id": str(order_result.inserted_id),
            "dealer_id": dealer_id,
            "salesman_id": salesman_id,
            "company_id": company_id,
            "product_part_no": product_part_no,
            "product_name": product_name,
            "qty": qty,
            "rate": rate,
            "amount": amount,
            "created_at": now()
        })

        flash("Order created successfully.", "success")
        return redirect(url_for("admin.salesman_orders"))

    dealer_rows = db.distributors.find({
        "salesman_id": salesman_id,
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("name", 1)

    dealers = []

    for d in dealer_rows:
        dealers.append((
            str(d.get("_id")),
            d.get("name", "")
        ))

    return render_template("salesman_create_order.html", dealers=dealers)






@admin_bp.route("/redeem-coupon/<coupon_id>", methods=["POST"])
def redeem_coupon(coupon_id):

    if "user_id" not in session:
        flash("Login first", "danger")
        return redirect(url_for("auth.login"))

    db = get_db()

    manual_reason = request.form.get("manual_reason", "").strip()
    company_id = session.get("company_id")

    try:

        coupon = db.coupons.find_one({
            "_id": oid(coupon_id),
            "company_id": company_id
        })

        if not coupon:
            flash("Invalid coupon", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        db.coupons.update_one(
            {"_id": oid(coupon_id)},
            {
                "$set": {
                    "is_redeemed": 1,
                    "status": "redeemed",
                    "redeemed_at": now(),
                    "redeemed_by": session.get("user_id")
                }
            }
        )

        db.dealer_redemptions.insert_one({
            "dealer_id": coupon.get("scanned_by") or coupon.get("dealer_id"),
            "coupon_id": coupon_id,
            "coupon_code": coupon.get("code"),
            "redemption_type": "manual",
            "part_no": coupon.get("part_no"),
            "product_name": coupon.get("product_name"),
            "coupons_count": 1,
            "redeemed_points": int(coupon.get("points") or 0),
            "remarks": manual_reason,
            "redeemed_by": session.get("user_id"),
            "company_id": company_id,
            "created_at": now()
        })

        flash("Redeemed successfully", "success")

    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("admin.pending_redemptions"))

@admin_bp.route("/employee/pending-redemptions")
def pending_redemptions():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    if session.get("user_role") not in ["employee", "admin"]:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    rows = db.coupons.find({
        "company_id": company_id,
        "scanned_at": {"$exists": True, "$ne": None},
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ],
        "$and": [
            {
                "$or": [
                    {"is_redeemed": 0},
                    {"is_redeemed": False},
                    {"is_redeemed": {"$exists": False}},
                    {"is_redeemed": None}
                ]
            },
            {
                "$or": [
                    {"status": None},
                    {"status": ""},
                    {"status": "scanned"},
                    {"status": "pending"}
                ]
            }
        ]
    }).sort("_id", -1)

    coupons = []

    for c in rows:
        dealer_name = "Unknown"

        dealer_id = c.get("scanned_by") or c.get("dealer_id")
        if dealer_id:
            dealer = db.distributors.find_one({"_id": oid(dealer_id)})
            if dealer:
                dealer_name = dealer.get("name", "Unknown")

        coupons.append((
            str(c.get("_id")),
            c.get("code", ""),
            c.get("product_name", ""),
            c.get("part_no", ""),
            int(c.get("points") or 0),
            c.get("scanned_at"),
            dealer_name
        ))

    return render_template(
        "pending_redemptions.html",
        coupons=coupons
    )

@admin_bp.route("/redeem-by-invoice", methods=["POST"])
def redeem_by_invoice():

    if "user_id" not in session:
        flash("Login first", "danger")
        return redirect(url_for("auth.login"))

    db = get_db()

    invoice_no = request.form.get("invoice_no", "").strip()
    dealer_id = request.form.get("dealer_id", "").strip()
    company_id = session.get("company_id")

    if not invoice_no:
        flash("Invoice number is required.", "danger")
        return redirect(url_for("admin.pending_redemptions"))

    try:
        coupons = list(db.coupons.find({
            "invoice_no": invoice_no,
            "company_id": company_id,
            "$or": [
                {"is_redeemed": 0},
                {"is_redeemed": False},
                {"is_redeemed": {"$exists": False}},
                {"is_redeemed": None}
            ]
        }))

        if not coupons:
            flash("No coupons found for invoice", "warning")
            return redirect(url_for("admin.pending_redemptions"))

        count = len(coupons)
        total_points = sum(int(c.get("points") or 0) for c in coupons)

        db.coupons.update_many(
            {
                "invoice_no": invoice_no,
                "company_id": company_id
            },
            {
                "$set": {
                    "is_redeemed": 1,
                    "status": "redeemed",
                    "redeemed_at": now(),
                    "redeemed_by": session.get("user_id")
                }
            }
        )

        db.dealer_redemptions.insert_one({
            "dealer_id": dealer_id,
            "invoice_no": invoice_no,
            "redemption_type": "invoice",
            "coupons_count": count,
            "redeemed_points": total_points,
            "redeemed_by": session.get("user_id"),
            "company_id": company_id,
            "created_at": now()
        })

        flash("Invoice redeemed successfully", "success")

    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("admin.pending_redemptions"))

@admin_bp.route("/employee/dealer-wallets")
def dealer_wallets():

    if "user_id" not in session or session.get("user_role") != "employee":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    dealers = db.distributors.find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    wallets = []

    for dealer in dealers:
        dealer_id = str(dealer.get("_id"))

        coupons = list(db.coupons.find({
            "$or": [
                {"scanned_by": dealer_id},
                {"dealer_id": dealer_id}
            ],
            "status": {"$in": ["scanned", "redeemed"]}
        }))

        total_points = sum(int(c.get("points") or 0) for c in coupons)

        updated_at = None
        scanned_dates = [c.get("scanned_at") for c in coupons if c.get("scanned_at")]
        if scanned_dates:
            updated_at = max(scanned_dates)

        wallets.append((
            dealer_id,
            dealer.get("name", ""),
            dealer.get("mobile", ""),
            total_points,
            updated_at
        ))

    return render_template("dealer_wallets.html", wallets=wallets)

@admin_bp.route("/employee/wallet-transactions")
def wallet_transactions():

    if "user_id" not in session or session.get("user_role") != "employee":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    transactions = []

    # Manual wallet transactions
    wallet_rows = db.wallet_transactions.find({
        "company_id": company_id
    })

    for wt in wallet_rows:
        dealer_name = "Unknown"
        dealer_id = wt.get("dealer_id")

        if dealer_id:
            dealer = db.distributors.find_one({"_id": oid(dealer_id)})
            if dealer:
                dealer_name = dealer.get("name", "Unknown")

        transactions.append((
            str(wt.get("_id")),
            dealer_name,
            wt.get("coupon_id", ""),
            int(wt.get("points") or 0),
            wt.get("transaction_type", ""),
            wt.get("remarks", ""),
            wt.get("created_at")
        ))

    # Scan transactions from coupons
    coupon_rows = db.coupons.find({
        "company_id": company_id,
        "scanned_at": {"$exists": True, "$ne": None}
    })

    for c in coupon_rows:
        dealer_name = "Unknown"
        dealer_id = c.get("scanned_by") or c.get("dealer_id")

        if dealer_id:
            dealer = db.distributors.find_one({"_id": oid(dealer_id)})
            if dealer:
                dealer_name = dealer.get("name", "Unknown")

        transactions.append((
            str(c.get("_id")),
            dealer_name,
            str(c.get("_id")),
            int(c.get("points") or 0),
            "scan",
            f"Coupon scanned: {c.get('code', '')}",
            c.get("scanned_at")
        ))

    transactions.sort(
        key=lambda x: x[6] or datetime.min,
        reverse=True
    )

    return render_template(
        "wallet_transactions.html",
        transactions=transactions
    )


@admin_bp.route("/scan/<code>")
def scan_coupon(code):

    db = get_db()
    code = code.strip().upper()

    coupon = db.coupons.find_one({
        "code": code,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not coupon:
        return render_template("scan_result.html", status="invalid")

    status = (coupon.get("status") or "").strip().lower()

    if status == "redeemed":
        return render_template(
            "scan_result.html",
            status="already",
            points=int(coupon.get("points") or 0)
        )

    db.coupons.update_one(
        {"_id": coupon["_id"]},
        {
            "$set": {
                "status": "redeemed",
                "is_redeemed": 1,
                "scanned_at": coupon.get("scanned_at") or now(),
                "redeemed_at": now()
            }
        }
    )

    return render_template(
        "scan_result.html",
        status="success",
        points=int(coupon.get("points") or 0)
    )

from flask import jsonify
from pymongo import DESCENDING


@admin_bp.route("/api/scan/<code>")
def api_scan_coupon(code):

    db = get_db()
    code = code.strip().upper()

    coupon = db.coupons.find_one({
        "code": code,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not coupon:
        return jsonify({
            "success": False,
            "status": "invalid",
            "message": "Coupon not found"
        }), 404

    status = (coupon.get("status") or "").strip().lower()

    if status == "redeemed":
        return jsonify({
            "success": False,
            "status": "already",
            "message": "Coupon already redeemed",
            "points": int(coupon.get("points") or 0)
        }), 200

    db.coupons.update_one(
        {"_id": coupon["_id"]},
        {
            "$set": {
                "status": "redeemed",
                "is_redeemed": 1,
                "scanned_at": now(),
                "redeemed_at": now()
            }
        }
    )

    return jsonify({
        "success": True,
        "status": "success",
        "message": "Coupon applied successfully",
        "points": int(coupon.get("points") or 0)
    }), 200



@admin_bp.route("/salesman/products/search")
def salesman_product_search():

    if "user_id" not in session or session.get("user_role") != "sales":
        return {"items": []}

    db = get_db()

    company_id = session.get("company_id")
    q = request.args.get("q", "").strip()

    match_filter = {
        "company_id": company_id,
        "is_deleted": 0,
        "part_no": {"$nin": [None, ""]},
        "product_name": {"$nin": [None, ""]}
    }

    if q:
        match_filter["$or"] = [
            {"part_no": {"$regex": q, "$options": "i"}},
            {"product_name": {"$regex": q, "$options": "i"}}
        ]

    pipeline = [
        {"$match": match_filter},

        {
            "$group": {
                "_id": {
                    "part_no": "$part_no",
                    "product_name": "$product_name",
                    "product_type": "$product_type",
                    "pack_size": "$pack_size",
                    "mrp": "$mrp",
                    "dlp": "$dlp",
                    "points": "$points"
                },
                "latest_id": {"$max": "$_id"}
            }
        },

        {
            "$sort": {
                "latest_id": -1
            }
        },

        {
            "$limit": 20
        }
    ]

    rows = list(db.coupons.aggregate(pipeline))

    items = []

    for r in rows:
        item = r.get("_id", {})

        items.append({
            "part_no": item.get("part_no", ""),
            "product_name": item.get("product_name", ""),
            "product_type": item.get("product_type", ""),
            "pack_size": item.get("pack_size", ""),
            "mrp": float(item.get("mrp") or 0),
            "dlp": float(item.get("dlp") or 0),
            "points": int(item.get("points") or 0)
        })

    return {"items": items}




@admin_bp.route("/employee/orders")
def general_employee_orders():

    if "user_id" not in session or session.get("user_role") not in ["employee", "admin"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    rows = db.dealer_orders.find({
        "company_id": company_id
    }).sort("_id", -1)

    orders = []

    for order in rows:
        dealer_name = "N/A"
        salesman_name = "N/A"

        dealer_id = order.get("dealer_id")
        salesman_id = order.get("salesman_id")

        if dealer_id:
            dealer = db.distributors.find_one({"_id": oid(dealer_id)})
            if dealer:
                dealer_name = dealer.get("name", "N/A")

        if salesman_id:
            salesman = db.users.find_one({"_id": oid(salesman_id)})
            if salesman:
                salesman_name = salesman.get("name", "N/A")

        orders.append((
            str(order.get("_id")),
            order.get("order_no", ""),
            dealer_name,
            salesman_name,
            order.get("part_no", ""),
            order.get("part_name", ""),
            order.get("order_status", ""),
            float(order.get("total_amount") or 0),
            order.get("created_at", "")
        ))

    return render_template(
        "general_employee_orders.html",
        orders=orders
    )

from flask import request, jsonify, current_app
from werkzeug.security import check_password_hash
import secrets

@csrf.exempt
@admin_bp.route("/api/dealer/login", methods=["POST"])
def dealer_login_api():
    try:
        data = request.get_json(silent=True)

        if not data:
            return jsonify({"success": False, "message": "Invalid request"}), 400

        login_value = (data.get("login") or "").strip().lower()
        password = data.get("password") or ""

        if not login_value or not password:
            return jsonify({"success": False, "message": "Login and password required"}), 400

        db = get_db()

        dealer = db.distributors.find_one({
    "$and": [
        {
            "$or": [
                {"email": login_value},
                {"mobile": login_value}
            ]
        },
        {
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        }
    ]
})

        if not dealer:
            return jsonify({"success": False, "message": "Invalid login"}), 401

        dealer_password = dealer.get("password") or ""

        if not dealer_password or not check_password_hash(dealer_password, password):
            return jsonify({"success": False, "message": "Invalid password"}), 401

        dealer_id = dealer["_id"]

        token = secrets.token_hex(32)

        db.distributors.update_one(
            {"_id": dealer_id},
            {"$set": {"active_token": token, "last_login": now()}}
        )

        profile_image = ""
        if dealer.get("profile_image"):
            value = str(dealer.get("profile_image")).strip()

            if value.startswith("http"):
                profile_image = value
            else:
                profile_image = request.host_url.rstrip("/") + "/static/uploads/" + value

        return jsonify({
            "success": True,
            "token": token,
            "dealer": {
                "id": str(dealer.get("_id")),
                "dealer_code": dealer.get("dealer_code", ""),
                "name": dealer.get("name", ""),
                "mobile": dealer.get("mobile", ""),
                "email": dealer.get("email", ""),
                "city": dealer.get("city", ""),
                "state": dealer.get("state", ""),
                "gst": dealer.get("gst", ""),
                "pan": dealer.get("pan", ""),
                "address": dealer.get("address", ""),
                "profile_image": profile_image
            }
        }), 200

    except Exception as e:
        current_app.logger.exception("Dealer login error")
        return jsonify({"success": False, "message": str(e)}), 500


@csrf.exempt
@admin_bp.route("/api/dealer/logout", methods=["POST"])
def dealer_logout_api():
    try:
        data = request.get_json(silent=True) or {}
        dealer_id = data.get("dealer_id")

        if not dealer_id:
            return jsonify({"success": False, "message": "Dealer ID is required"}), 400

        db = get_db()

        db.distributors.update_one(
            {"_id": oid(dealer_id)},
            {"$set": {"active_token": None, "last_logout": now()}}
        )

        return jsonify({"success": True, "message": "Logged out successfully"}), 200

    except Exception as e:
        current_app.logger.exception("Dealer logout API error")
        return jsonify({"success": False, "message": str(e)}), 500
    
@csrf.exempt
@admin_bp.route("/api/dealer/scan/<code>/<dealer_id>", methods=["POST"])
def dealer_scan_coupon(code, dealer_id):
    try:
        db = get_db()
        code = code.strip().upper()

        dealer = db.distributors.find_one({
            "_id": oid(dealer_id),
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if not dealer:
            return jsonify({"success": False, "message": "Dealer not found"}), 404

        coupon = db.coupons.find_one({
            "code": code,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if not coupon:
            return jsonify({"success": False, "message": "Invalid coupon code"}), 404

        status = (coupon.get("status") or "").strip().lower()

        if status == "redeemed":
            return jsonify({"success": False, "message": "Coupon already redeemed"}), 200

        if status == "scanned":
            return jsonify({"success": False, "message": "Coupon already scanned"}), 200

        part_no = coupon.get("part_no", "")
        points = int(coupon.get("points") or 0)

        db.coupons.update_one(
            {"_id": coupon["_id"]},
            {
                "$set": {
                    "dealer_id": dealer_id,
                    "scanned_by": dealer_id,
                    "status": "scanned",
                    "scanned_at": now()
                }
            }
        )

        scanned_coupons = list(db.coupons.find({
            "dealer_id": dealer_id,
            "part_no": part_no,
            "status": {"$in": ["scanned", "redeemed"]},
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        }))

        total_scans = len(scanned_coupons)
        total_points = sum(int(c.get("points") or 0) for c in scanned_coupons)

        set_size = 10
        completed_sets = total_scans // set_size
        remaining_scans = total_scans % set_size

        db.dealer_coupon_sets.update_one(
            {
                "dealer_id": dealer_id,
                "part_no": part_no
            },
            {
                "$set": {
                    "dealer_id": dealer_id,
                    "part_no": part_no,
                    "total_scans": total_scans,
                    "set_size": set_size,
                    "completed_sets": completed_sets,
                    "remaining_scans": remaining_scans,
                    "total_points": total_points,
                    "updated_at": now()
                }
            },
            upsert=True
        )

        return jsonify({
            "success": True,
            "message": f"Coupon scanned successfully. {points} points added.",
            "coupon_code": coupon.get("code", code),
            "part_no": part_no,
            "points": points,
            "dealer_id": dealer_id,
            "total_scans_for_part": total_scans,
            "completed_sets": completed_sets,
            "remaining_scans": remaining_scans
        }), 200

    except Exception as e:
        current_app.logger.exception("Dealer scan error")
        return jsonify({
            "success": False,
            "message": f"Scan failed: {str(e)}"
        }), 500

from flask import request, jsonify, current_app

@admin_bp.route("/api/dealer/scanned-history/<dealer_id>", methods=["GET"])
def dealer_scanned_history_api(dealer_id):
    db = get_db()

    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()

    query = {
        "dealer_id": dealer_id,
        "status": {"$in": ["scanned", "redeemed"]},
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }

    if from_date or to_date:
        query["scanned_at"] = {}

        if from_date:
            query["scanned_at"]["$gte"] = datetime.strptime(from_date, "%Y-%m-%d")

        if to_date:
            end_date = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)
            query["scanned_at"]["$lt"] = end_date

    rows = db.coupons.find(query).sort("scanned_at", -1)

    history = []
    for r in rows:
        history.append({
            "code": r.get("code", ""),
            "part_no": r.get("part_no", ""),
            "product_name": r.get("product_name", ""),
            "points": int(r.get("points") or 0),
            "scanned_at": str(r.get("scanned_at") or ""),
            "status": r.get("status", "")
        })

    return jsonify({
        "success": True,
        "history": history
    })

from flask import jsonify, current_app

@admin_bp.route("/api/dealer/sets/<dealer_id>", methods=["GET"])
def dealer_sets_api(dealer_id):
    db = get_db()

    rows = db.dealer_coupon_sets.find({
        "dealer_id": dealer_id
    }).sort("part_no", 1)

    sets = []

    for r in rows:
        part_no = r.get("part_no") or "-"
        set_size = int(r.get("set_size") or 10)
        total_scans = int(r.get("total_scans") or 0)
        completed_sets = int(r.get("completed_sets") or 0)
        total_points = int(r.get("total_points") or 0)

        current_progress = total_scans % set_size
        if current_progress == 0 and total_scans > 0:
            current_progress = set_size

        pending = set_size - current_progress
        if current_progress == set_size:
            pending = 0

        sets.append({
            "part_no": part_no,
            "total": set_size,
            "scanned": current_progress,
            "pending": pending,
            "completed_sets": completed_sets,
            "current_progress": current_progress,
            "total_scans": total_scans,
            "total_points": total_points
        })

    return jsonify({
        "success": True,
        "sets": sets
    })

@admin_bp.route("/employee/manual-settlement", methods=["POST"])
def manual_settlement():

    if "user_id" not in session or session.get("user_role") not in ["employee", "admin"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    dealer_id = request.form.get("dealer_id", "").strip()
    part_no = request.form.get("part_no", "").strip()
    remarks = request.form.get("remarks", "").strip()

    if not dealer_id or not part_no:
        flash("Dealer and part number are required.", "danger")
        return redirect(url_for("admin.pending_redemptions"))

    coupons = list(
        db.coupons.find({
            "dealer_id": dealer_id,
            "part_no": part_no,
            "status": "scanned"
        })
        .sort("scanned_at", 1)
        .limit(10)
    )

    if len(coupons) < 10:
        flash("At least 10 scanned coupons are required for settlement.", "danger")
        return redirect(url_for("admin.pending_redemptions"))

    coupon_ids = [c["_id"] for c in coupons]
    product_name = coupons[0].get("product_name", "")
    total_points = sum(int(c.get("points") or 0) for c in coupons)

    db.coupons.update_many(
        {"_id": {"$in": coupon_ids}},
        {
            "$set": {
                "status": "redeemed",
                "is_redeemed": 1,
                "redeemed_by": session.get("user_id"),
                "redeemed_at": now()
            }
        }
    )

    db.dealer_wallets.update_one(
        {"dealer_id": dealer_id},
        {
            "$inc": {
                "total_points": total_points
            },
            "$set": {
                "dealer_id": dealer_id,
                "updated_at": now()
            }
        },
        upsert=True
    )

    db.wallet_transactions.insert_one({
        "dealer_id": dealer_id,
        "coupon_id": None,
        "points": total_points,
        "transaction_type": "credit",
        "remarks": f"Settlement for part {part_no}",
        "created_by": session.get("user_id"),
        "company_id": session.get("company_id"),
        "created_at": now()
    })

    db.dealer_settlements.insert_one({
        "dealer_id": dealer_id,
        "part_no": part_no,
        "product_name": product_name,
        "settled_sets": 1,
        "coupons_count": 10,
        "total_points": total_points,
        "settlement_type": "manual",
        "remarks": remarks,
        "settled_by": session.get("user_id"),
        "company_id": session.get("company_id"),
        "created_at": now()
    })

    remaining_coupons = list(db.coupons.find({
        "dealer_id": dealer_id,
        "part_no": part_no,
        "status": "scanned"
    }))

    scanned_count = len(remaining_coupons)
    scanned_points = sum(int(c.get("points") or 0) for c in remaining_coupons)

    completed_sets = scanned_count // 10
    remaining_scans = scanned_count % 10

    db.dealer_coupon_sets.update_one(
        {
            "dealer_id": dealer_id,
            "part_no": part_no
        },
        {
            "$set": {
                "dealer_id": dealer_id,
                "part_no": part_no,
                "total_scans": scanned_count,
                "completed_sets": completed_sets,
                "remaining_scans": remaining_scans,
                "total_points": scanned_points,
                "set_size": 10,
                "updated_at": now()
            }
        },
        upsert=True
    )

    flash("Manual settlement completed successfully.", "success")
    return redirect(url_for("admin.pending_redemptions"))










from flask import jsonify, current_app

@admin_bp.route("/api/dealer/wallet/<dealer_id>", methods=["GET"])
def dealer_wallet_api(dealer_id):
    db = get_db()

    coupons = list(db.coupons.find({
        "dealer_id": dealer_id,
        "status": {"$in": ["scanned", "redeemed"]},
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }))

    total_points = sum(int(c.get("points") or 0) for c in coupons)

    part_map = {}
    for c in coupons:
        part_no = c.get("part_no") or "-"
        part_map[part_no] = part_map.get(part_no, 0) + int(c.get("points") or 0)

    part_points = [
        {"part_no": part_no, "points": points}
        for part_no, points in part_map.items()
        if points > 0
    ]

    return jsonify({
        "success": True,
        "total_points": total_points,
        "part_points": part_points
    })

@admin_bp.route("/employee/redeem-points", methods=["POST"])
def redeem_points():

    if "user_id" not in session or session.get("user_role") not in ["employee", "admin"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    dealer_id = request.form.get("dealer_id", "").strip()
    invoice_no = request.form.get("invoice_no", "").strip()
    redemption_type = request.form.get("redemption_type", "manual").strip()
    part_no = request.form.get("part_no", "").strip()
    product_name = request.form.get("product_name", "").strip()
    remarks = request.form.get("remarks", "").strip()

    try:
        sets_count = int(request.form.get("sets_count", 0) or 0)
    except:
        sets_count = 0

    try:
        manual_points = int(request.form.get("manual_points", 0) or 0)
    except:
        manual_points = 0

    if not dealer_id or not invoice_no:
        flash("Dealer and invoice number are required.", "danger")
        return redirect(url_for("admin.redemptions_page"))

    wallet = db.dealer_wallets.find_one({"dealer_id": dealer_id})

    if not wallet:
        flash("Wallet not found for dealer.", "danger")
        return redirect(url_for("admin.redemptions_page"))

    earned_points = int(wallet.get("earned_points") or wallet.get("total_points") or 0)
    redeemed_points = int(wallet.get("redeemed_points") or 0)
    available_points = int(wallet.get("available_points") or (earned_points - redeemed_points))

    redeem_points_value = 0
    coupons_count = 0

    if redemption_type == "set":
        if not part_no or sets_count <= 0:
            flash("Part no and set count are required for set redemption.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        set_row = db.dealer_coupon_sets.find_one({
            "dealer_id": dealer_id,
            "part_no": part_no
        })

        if not set_row:
            flash("No set summary found for this part.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        completed_sets = int(set_row.get("completed_sets") or 0)

        if not product_name:
            product_name = set_row.get("product_name", "")

        if completed_sets < sets_count:
            flash("Requested set count is higher than available completed sets.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        coupons_count = sets_count * 10

        coupons = list(
            db.coupons.find({
                "dealer_id": dealer_id,
                "part_no": part_no,
                "status": "scanned"
            })
            .sort("scanned_at", 1)
            .limit(coupons_count)
        )

        if len(coupons) < coupons_count:
            flash("Not enough scanned coupons found for this part.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        redeem_points_value = sum(int(c.get("points") or 0) for c in coupons)

        if redeem_points_value <= 0:
            flash("No redeemable scanned coupons found for this part.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        coupon_ids = [c["_id"] for c in coupons]

        db.coupons.update_many(
            {"_id": {"$in": coupon_ids}},
            {
                "$set": {
                    "status": "redeemed",
                    "is_redeemed": 1,
                    "redeemed_by": session.get("user_id"),
                    "redeemed_at": now()
                }
            }
        )

        remaining_coupons = list(db.coupons.find({
            "dealer_id": dealer_id,
            "part_no": part_no,
            "status": "scanned"
        }))

        scanned_count = len(remaining_coupons)
        scanned_points = sum(int(c.get("points") or 0) for c in remaining_coupons)

        db.dealer_coupon_sets.update_one(
            {
                "dealer_id": dealer_id,
                "part_no": part_no
            },
            {
                "$set": {
                    "total_scans": scanned_count,
                    "completed_sets": scanned_count // 10,
                    "remaining_scans": scanned_count % 10,
                    "total_points": scanned_points,
                    "updated_at": now()
                }
            }
        )

    else:
        redeem_points_value = manual_points
        coupons_count = 0

        if redeem_points_value <= 0:
            flash("Manual points must be greater than zero.", "danger")
            return redirect(url_for("admin.redemptions_page"))

    if available_points < redeem_points_value:
        flash("Not enough available points.", "danger")
        return redirect(url_for("admin.redemptions_page"))

    new_redeemed_points = redeemed_points + redeem_points_value
    new_available_points = earned_points - new_redeemed_points

    db.dealer_wallets.update_one(
        {"dealer_id": dealer_id},
        {
            "$set": {
                "earned_points": earned_points,
                "redeemed_points": new_redeemed_points,
                "available_points": new_available_points,
                "updated_at": now()
            }
        },
        upsert=True
    )

    db.dealer_redemptions.insert_one({
        "dealer_id": dealer_id,
        "invoice_no": invoice_no,
        "redemption_type": redemption_type,
        "part_no": part_no if part_no else None,
        "product_name": product_name if product_name else None,
        "sets_count": sets_count,
        "coupons_count": coupons_count,
        "redeemed_points": redeem_points_value,
        "remarks": remarks,
        "redeemed_by": session.get("user_id"),
        "company_id": session.get("company_id"),
        "created_at": now()
    })

    db.wallet_transactions.insert_one({
        "dealer_id": dealer_id,
        "coupon_id": None,
        "points": redeem_points_value,
        "transaction_type": "redeem_invoice",
        "remarks": f"Invoice {invoice_no}",
        "created_by": session.get("user_id"),
        "company_id": session.get("company_id"),
        "created_at": now()
    })

    flash("Points redeemed successfully.", "success")
    return redirect(url_for("admin.redemptions_page"))

@admin_bp.route("/employee/redemption-history")
def redemption_history():

    if "user_id" not in session or session.get("user_role") not in ["employee", "admin"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    redemptions_cursor = db.dealer_redemptions.find({
        "company_id": company_id
    }).sort("created_at", -1)

    rows = []

    for r in redemptions_cursor:

        dealer_name = "Unknown"

        dealer_id = r.get("dealer_id")

        if dealer_id:
            dealer = db.distributors.find_one({
                "_id": oid(dealer_id)
            })

            if dealer:
                dealer_name = dealer.get("name", "Unknown")

        rows.append((
            str(r.get("_id")),
            dealer_name,
            r.get("invoice_no", ""),
            r.get("redemption_type", ""),
            r.get("part_no", ""),
            r.get("product_name", ""),
            int(r.get("sets_count") or 0),
            int(r.get("coupons_count") or 0),
            int(r.get("redeemed_points") or 0),
            r.get("remarks", ""),
            r.get("created_at")
        ))

    return render_template(
        "redemption_history.html",
        redemptions=rows
    )

@admin_bp.route("/api/dealer/redemption-history/<dealer_id>", methods=["GET"])
def dealer_redemption_history_api(dealer_id):
    db = get_db()

    rows = db.dealer_redemptions.find({
        "dealer_id": dealer_id
    }).sort("created_at", -1).limit(100)

    history = []

    for r in rows:
        history.append({
            "invoice_no": r.get("invoice_no", ""),
            "type": r.get("redemption_type", ""),
            "part_no": r.get("part_no", "-"),
            "product_name": r.get("product_name", "-"),
            "sets": int(r.get("sets_count") or 0),
            "coupons": int(r.get("coupons_count") or 0),
            "points": int(r.get("redeemed_points") or 0),
            "remarks": r.get("remarks", ""),
            "redeemed_at": str(r.get("created_at") or ""),
            "redeemed_by": str(r.get("redeemed_by") or "-")
        })

    return jsonify({
        "success": True,
        "history": history
    })



from flask import jsonify

@admin_bp.route("/api/dealer/banners/<dealer_id>", methods=["GET"])
def dealer_banners_api(dealer_id):
    db = get_db()

    dealer = db.distributors.find_one({
        "_id": oid(dealer_id),
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not dealer:
        return jsonify({
            "success": False,
            "message": "Dealer not found",
            "banners": []
        }), 404

    company_id = dealer.get("company_id")

    banner = db.banners.find_one(
        {
            "company_id": company_id,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ],
            "$and": [
                {
                    "$or": [
                        {"is_active": 1},
                        {"is_active": True},
                        {"is_active": {"$exists": False}},
                        {"is_active": None}
                    ]
                }
            ]
        },
        sort=[("_id", -1)]
    )

    if not banner:
        return jsonify({
            "success": True,
            "message": "No banner found",
            "banners": []
        }), 200

    image = banner.get("image", "")

    return jsonify({
        "success": True,
        "banners": [{
            "id": str(banner.get("_id")),
            "title": banner.get("title", ""),
            "image_url": request.host_url.rstrip("/") + "/static/uploads/" + image if image else ""
        }]
    }), 200


import os
import time
from werkzeug.utils import secure_filename
from flask import request, jsonify, current_app, url_for

@csrf.exempt
@admin_bp.route("/api/dealer/upload-profile-image/<dealer_id>", methods=["POST"])
def upload_profile_image(dealer_id):
    try:
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()

        if not verify_dealer_token(dealer_id, token):
            return jsonify({"success": False, "message": "Session expired"}), 401

        if "profile_image" not in request.files:
            return jsonify({"success": False, "message": "No file"}), 400

        image = request.files["profile_image"]

        if not image or image.filename == "":
            return jsonify({"success": False, "message": "No selected file"}), 400

        ext = image.filename.rsplit(".", 1)[-1].lower()
        filename = f"dealer_{dealer_id}_{int(time.time())}.{ext}"

        folder = os.path.join(current_app.root_path, "static", "uploads", "profiles")
        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, filename)
        image.save(path)

        db_path = f"profiles/{filename}"

        db = get_db()

        db.distributors.update_one(
            {"_id": oid(dealer_id)},
            {"$set": {"profile_image": db_path, "updated_at": now()}}
        )

        image_url = request.host_url.rstrip("/") + "/static/uploads/" + db_path

        return jsonify({
            "success": True,
            "message": "Profile image updated",
            "profile_image": image_url
        }), 200

    except Exception as e:
        current_app.logger.exception("Upload error")
        return jsonify({"success": False, "message": str(e)}), 500


@admin_bp.route("/company-admin/distributors", methods=["GET"])
def company_admin_distributors_crud():
    if not _check_company_admin():
        return redirect(url_for("auth.login"))

    company_id = session.get("company_id")
    distributors = _fetch_entities("distributors", company_id)

    return render_template(
        "company_admin_distributors.html",
        distributors=distributors,
        edit_item=None
    )


@admin_bp.route("/company-admin/retailers")
def company_admin_retailers_page():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    rows = db.retailers.find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    retailers = []

    for row in rows:
        retailers.append({
            "id": str(row.get("_id")),
            "dealer_code": row.get("dealer_code", ""),
            "name": row.get("name", ""),
            "mobile": row.get("mobile", ""),
            "email": row.get("email", ""),
            "pan": row.get("pan", ""),
            "gst": row.get("gst", ""),
            "city": row.get("city", ""),
            "state": row.get("state", ""),
            "address": row.get("address", "")
        })

    return render_template("company_admin_retailers.html", retailers=retailers)


@admin_bp.route("/company-admin/mechanics", methods=["GET"])
def company_admin_mechanics_CRUD_page():
    if not _check_company_admin():
        return redirect(url_for("auth.login"))

    company_id = session.get("company_id")
    mechanics = _fetch_entities("mechanics", company_id)

    return render_template(
        "company_admin_mechanics.html",
        mechanics=mechanics,
        edit_item=None
    )


@admin_bp.route("/company-admin/<entity_type>/add", methods=["POST"])
def add_entity(entity_type):

    if not _check_company_admin():
        return redirect(url_for("auth.login"))

    if entity_type not in ["distributors", "retailers", "mechanics"]:
        flash("Invalid entity type.", "danger")
        return redirect(url_for("admin.company_admin_dashboard"))

    db = get_db()
    company_id = session.get("company_id")
    label = _get_entity_label(entity_type)

    dealer_code = request.form.get("dealer_code", "").strip()
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    pan = request.form.get("pan", "").strip().upper()
    gst = request.form.get("gst", "").strip().upper()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip()
    address = request.form.get("address", "").strip()

    if not dealer_code or not name or not mobile:
        flash(f"{label} code, name and mobile are required.", "danger")
        return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

    existing_code = db[entity_type].find_one({
        "company_id": company_id,
        "dealer_code": dealer_code,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if existing_code:
        flash(f"{label} code already exists.", "danger")
        return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

    if email:
        existing_email = db[entity_type].find_one({
            "company_id": company_id,
            "email": email,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing_email:
            flash(f"{label} email already exists.", "danger")
            return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

    hashed_password = generate_password_hash(password) if password else None

    db[entity_type].insert_one({
        "dealer_code": dealer_code,
        "name": name,
        "mobile": mobile,
        "email": email,
        "password": hashed_password,
        "pan": pan,
        "gst": gst,
        "city": city,
        "state": state,
        "address": address,
        "company_id": company_id,
        "is_deleted": 0,
        "created_at": now()
    })

    flash(f"{label} added successfully.", "success")
    return redirect(url_for(f"admin.company_admin_{entity_type}_page"))


@admin_bp.route("/company-admin/<entity_type>/edit/<record_id>", methods=["GET", "POST"])
def edit_entity(entity_type, record_id):

    if not _check_company_admin():
        return redirect(url_for("auth.login"))

    if entity_type not in ["distributors", "retailers", "mechanics"]:
        flash("Invalid entity type.", "danger")
        return redirect(url_for("admin.company_admin_dashboard"))

    db = get_db()
    company_id = session.get("company_id")
    label = _get_entity_label(entity_type)
    template_name = _get_entity_template(entity_type)

    record_obj_id = oid(record_id)

    if request.method == "POST":
        dealer_code = request.form.get("dealer_code", "").strip()
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        email = request.form.get("email", "").strip().lower()
        pan = request.form.get("pan", "").strip().upper()
        gst = request.form.get("gst", "").strip().upper()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        address = request.form.get("address", "").strip()

        if not dealer_code or not name or not mobile:
            flash(f"{label} code, name and mobile are required.", "danger")
            return redirect(url_for("admin.edit_entity", entity_type=entity_type, record_id=record_id))

        existing_code = db[entity_type].find_one({
            "company_id": company_id,
            "dealer_code": dealer_code,
            "_id": {"$ne": record_obj_id},
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing_code:
            flash(f"{label} code already exists.", "danger")
            return redirect(url_for("admin.edit_entity", entity_type=entity_type, record_id=record_id))

        if email:
            existing_email = db[entity_type].find_one({
                "company_id": company_id,
                "email": email,
                "_id": {"$ne": record_obj_id},
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            })

            if existing_email:
                flash(f"{label} email already exists.", "danger")
                return redirect(url_for("admin.edit_entity", entity_type=entity_type, record_id=record_id))

        result = db[entity_type].update_one(
            {
                "_id": record_obj_id,
                "company_id": company_id,
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            },
            {
                "$set": {
                    "dealer_code": dealer_code,
                    "name": name,
                    "mobile": mobile,
                    "email": email,
                    "pan": pan,
                    "gst": gst,
                    "city": city,
                    "state": state,
                    "address": address,
                    "updated_at": now()
                }
            }
        )

        if result.matched_count == 0:
            flash(f"{label} not found.", "danger")
            return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

        flash(f"{label} updated successfully.", "success")
        return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

    edit_item = _fetch_single_entity(entity_type, company_id, record_id)
    if not edit_item:
        flash(f"{label} not found.", "danger")
        return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

    all_items = _fetch_entities(entity_type, company_id)

    return render_template(
        template_name,
        **{entity_type: all_items},
        edit_item=edit_item
    )


@admin_bp.route("/company-admin/<entity_type>/delete/<record_id>", methods=["POST"])
def delete_entity(entity_type, record_id):

    if not _check_company_admin():
        return redirect(url_for("auth.login"))

    if entity_type not in ["distributors", "retailers", "mechanics"]:
        flash("Invalid entity type.", "danger")
        return redirect(url_for("admin.company_admin_dashboard"))

    db = get_db()
    company_id = session.get("company_id")
    label = _get_entity_label(entity_type)

    try:
        result = db[entity_type].update_one(
            {
                "_id": oid(record_id),
                "company_id": company_id
            },
            {
                "$set": {
                    "is_deleted": 1,
                    "deleted_at": now()
                }
            }
        )

        if result.matched_count == 0:
            flash(f"{label} not found.", "danger")
        else:
            flash(f"{label} deleted successfully.", "success")

    except Exception as e:
        flash(f"Error deleting {label.lower()}: {str(e)}", "danger")

    return redirect(url_for(f"admin.company_admin_{entity_type}_page"))



@admin_bp.route("/api/dealer/request-set-redemption", methods=["POST"])
def request_set_redemption():
    db = get_db()
    data = request.get_json(silent=True) or {}

    dealer_id = data.get("dealer_id")
    set_key = data.get("set_key")

    if not dealer_id or not set_key:
        return {"success": False, "message": "Dealer ID and set key required"}, 400

    dealer = db.distributors.find_one({"_id": oid(dealer_id)})

    if not dealer:
        return {"success": False, "message": "Dealer not found"}, 404

    company_id = dealer.get("company_id")

    existing = db.redemption_requests.find_one({
        "dealer_id": dealer_id,
        "set_key": set_key,
        "status": {"$in": ["pending", "approved"]}
    })

    if existing:
        return {
            "success": False,
            "message": "Redemption request already submitted"
        }, 400

    coupons = list(db.coupons.find({
        "company_id": company_id,
        "scanned_by": dealer_id,
        "part_no": set_key,
        "status": {"$in": ["scanned", "unused"]}
    }).limit(10))

    if len(coupons) < 10:
        return {
            "success": False,
            "message": "Set is not complete yet"
        }, 400

    total_points = sum(int(c.get("points") or 0) for c in coupons)

    db.redemption_requests.insert_one({
        "dealer_id": dealer_id,
        "dealer_name": dealer.get("name", ""),
        "company_id": company_id,
        "set_key": set_key,
        "total_coupons": len(coupons),
        "total_points": total_points,
        "coupon_ids": [str(c["_id"]) for c in coupons],
        "status": "pending",
        "created_at": now()
    })

    return {
        "success": True,
        "message": "Redemption request sent successfully"
    }

@admin_bp.route("/api/print-agent/login", methods=["POST"])
def print_agent_login():

    data = request.get_json(silent=True) or {}

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", "")).strip()

    if not email or not password:
        return {
            "success": False,
            "message": "Email and password required"
        }, 400

    db = get_db()

    user = db.users.find_one({
        "email": email,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
        ]
    })

    if not user:
        return {
            "success": False,
            "message": "Invalid credentials"
        }, 401

    if not check_password_hash(user["password"], password):
        return {
            "success": False,
            "message": "Invalid credentials"
        }, 401

    if user.get("role") not in ["admin", "qr_employee"]:
        return {
            "success": False,
            "message": "Access denied"
        }, 403

    token = secrets.token_hex(32)

    db.print_agent_sessions.insert_one({
        "token": token,
        "user_id": str(user["_id"]),
        "company_id": user.get("company_id"),
        "created_at": datetime.utcnow()
    })

    return {
        "success": True,
        "token": token,
        "company_id": user.get("company_id"),
        "company_name": user.get("company_name", ""),
        "user_name": user.get("name", "")
    }


@admin_bp.route("/api/print-agent/jobs", methods=["GET"])
def get_print_jobs():

    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    if not token:
        return {"success": False}, 401

    db = get_db()

    session_data = db.print_agent_sessions.find_one({
        "token": token
    })

    if not session_data:
        return {"success": False}, 401

    company_id = session_data.get("company_id")

    job = db.print_jobs.find_one({
        "company_id": company_id,
        "status": "pending"
    })

    if not job:
        return {
            "success": True,
            "job": None
        }

    return {
        "success": True,
        "job": {
            "id": str(job["_id"]),
            "raw_data": job.get("raw_data", "")
        }
    }


@admin_bp.route("/api/print-agent/job-complete", methods=["POST"])
def print_job_complete():

    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    db = get_db()

    session_data = db.print_agent_sessions.find_one({
        "token": token
    })

    if not session_data:
        return {"success": False}, 401

    data = request.get_json(silent=True) or {}

    job_id = data.get("job_id")

    if not job_id:
        return {"success": False}, 400

    db.print_jobs.update_one(
        {"_id": oid(job_id)},
        {
            "$set": {
                "status": "printed",
                "printed_at": datetime.utcnow()
            }
        }
    )

    return {"success": True}


@admin_bp.route("/company-admin/distributors/edit/<distributor_id>", methods=["GET", "POST"])
def edit_distributor(distributor_id):

    if "user_id" not in session or session.get("user_role") not in ["admin", "sales"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    company_id = session.get("company_id")
    user_role = session.get("user_role")
    user_id = session.get("user_id")

    # ================= POST =================
    if request.method == "POST":

        dealer_code = request.form.get("dealer_code", "").strip()
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        email = request.form.get("email", "").strip().lower()
        pan = request.form.get("pan", "").strip().upper()
        gst = request.form.get("gst", "").strip().upper()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        address = request.form.get("address", "").strip()

        if not dealer_code or not name:
            flash("Dealer code and name are required.", "danger")
            return redirect(url_for("admin.edit_distributor", distributor_id=distributor_id))

        try:

            existing_code = db.distributors.find_one({
                "_id": {"$ne": oid(distributor_id)},
                "dealer_code": dealer_code,
                "company_id": company_id,
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            })

            if existing_code:
                flash("Dealer code already exists.", "danger")
                return redirect(url_for("admin.edit_distributor", distributor_id=distributor_id))

            if email:
                existing_email = db.distributors.find_one({
                    "_id": {"$ne": oid(distributor_id)},
                    "email": email,
                    "company_id": company_id,
                    "$or": [
                        {"is_deleted": 0},
                        {"is_deleted": False},
                        {"is_deleted": {"$exists": False}},
                        {"is_deleted": None}
                    ]
                })

                if existing_email:
                    flash("Email already exists.", "danger")
                    return redirect(url_for("admin.edit_distributor", distributor_id=distributor_id))

            filter_query = {
                "_id": oid(distributor_id),
                "company_id": company_id
            }

            if user_role == "sales":
                filter_query["salesman_id"] = user_id

            result = db.distributors.update_one(
                filter_query,
                {
                    "$set": {
                        "dealer_code": dealer_code,
                        "name": name,
                        "mobile": mobile,
                        "email": email,
                        "pan": pan,
                        "gst": gst,
                        "city": city,
                        "state": state,
                        "address": address,
                        "updated_at": now()
                    }
                }
            )

            if result.matched_count == 0:
                flash("Distributor not found.", "danger")
                return redirect(url_for("admin.company_admin_distributors_page"))

            flash("Distributor updated successfully.", "success")
            return redirect(url_for("admin.company_admin_distributors_page"))

        except Exception as e:
            flash(f"Error updating distributor: {str(e)}", "danger")
            return redirect(url_for("admin.edit_distributor", distributor_id=distributor_id))

    # ================= GET =================
    filter_query = {
        "_id": oid(distributor_id),
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }

    if user_role == "sales":
        filter_query["salesman_id"] = user_id

    row = db.distributors.find_one(filter_query)

    if not row:
        flash("Distributor not found.", "danger")
        return redirect(url_for("admin.company_admin_distributors_page"))

    distributor = {
        "id": str(row.get("_id")),
        "dealer_code": row.get("dealer_code", ""),
        "name": row.get("name", ""),
        "mobile": row.get("mobile", ""),
        "email": row.get("email", ""),
        "pan": row.get("pan", ""),
        "gst": row.get("gst", ""),
        "city": row.get("city", ""),
        "state": row.get("state", ""),
        "address": row.get("address", "")
    }

    list_filter = {
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }

    if user_role == "sales":
        list_filter["salesman_id"] = user_id

    rows = db.distributors.find(list_filter).sort("_id", -1)

    distributors = []

    for r in rows:
        distributors.append({
            "id": str(r.get("_id")),
            "dealer_code": r.get("dealer_code", ""),
            "name": r.get("name", ""),
            "mobile": r.get("mobile", ""),
            "email": r.get("email", ""),
            "pan": r.get("pan", ""),
            "gst": r.get("gst", ""),
            "city": r.get("city", ""),
            "state": r.get("state", ""),
            "address": r.get("address", "")
        })

    return render_template(
        "company_admin_distributors.html",
        distributors=distributors,
        edit_distributor=distributor
    )


@admin_bp.route("/company-admin/retailers/edit/<retailer_id>", methods=["GET", "POST"])
def edit_retailer(retailer_id):

    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    # ================= POST =================
    if request.method == "POST":

        dealer_code = request.form.get("dealer_code", "").strip()
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        email = request.form.get("email", "").strip().lower()
        pan = request.form.get("pan", "").strip().upper()
        gst = request.form.get("gst", "").strip().upper()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        address = request.form.get("address", "").strip()

        try:

            db.retailers.update_one(
                {
                    "_id": oid(retailer_id),
                    "company_id": company_id
                },
                {
                    "$set": {
                        "dealer_code": dealer_code,
                        "name": name,
                        "mobile": mobile,
                        "email": email,
                        "pan": pan,
                        "gst": gst,
                        "city": city,
                        "state": state,
                        "address": address,
                        "updated_at": now()
                    }
                }
            )

            flash("Retailer updated successfully.", "success")
            return redirect(url_for("admin.company_admin_retailers_page"))

        except Exception as e:
            flash(f"Error updating retailer: {str(e)}", "danger")
            return redirect(url_for("admin.edit_retailer", retailer_id=retailer_id))

    # ================= GET =================
    row = db.retailers.find_one({
        "_id": oid(retailer_id),
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not row:
        flash("Retailer not found.", "danger")
        return redirect(url_for("admin.company_admin_retailers_page"))

    retailer = {
        "id": str(row.get("_id")),
        "dealer_code": row.get("dealer_code", ""),
        "name": row.get("name", ""),
        "mobile": row.get("mobile", ""),
        "email": row.get("email", ""),
        "pan": row.get("pan", ""),
        "gst": row.get("gst", ""),
        "city": row.get("city", ""),
        "state": row.get("state", ""),
        "address": row.get("address", "")
    }

    rows = db.retailers.find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    retailers = []

    for r in rows:
        retailers.append({
            "id": str(r.get("_id")),
            "dealer_code": r.get("dealer_code", ""),
            "name": r.get("name", ""),
            "mobile": r.get("mobile", ""),
            "email": r.get("email", ""),
            "pan": r.get("pan", ""),
            "gst": r.get("gst", ""),
            "city": r.get("city", ""),
            "state": r.get("state", ""),
            "address": r.get("address", "")
        })

    return render_template(
        "company_admin_retailers.html",
        retailers=retailers,
        edit_retailer=retailer
    )


@admin_bp.route("/company-admin/mechanics/edit/<mechanic_id>", methods=["GET", "POST"])
def edit_mechanic(mechanic_id):

    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()
    company_id = session.get("company_id")

    # ================= POST =================
    if request.method == "POST":

        dealer_code = request.form.get("dealer_code", "").strip()
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        email = request.form.get("email", "").strip().lower()
        pan = request.form.get("pan", "").strip().upper()
        gst = request.form.get("gst", "").strip().upper()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        address = request.form.get("address", "").strip()

        try:

            db.mechanics.update_one(
                {
                    "_id": oid(mechanic_id),
                    "company_id": company_id
                },
                {
                    "$set": {
                        "dealer_code": dealer_code,
                        "name": name,
                        "mobile": mobile,
                        "email": email,
                        "pan": pan,
                        "gst": gst,
                        "city": city,
                        "state": state,
                        "address": address,
                        "updated_at": now()
                    }
                }
            )

            flash("Mechanic updated successfully.", "success")
            return redirect(url_for("admin.company_admin_mechanics_page"))

        except Exception as e:
            flash(f"Error updating mechanic: {str(e)}", "danger")
            return redirect(url_for("admin.edit_mechanic", mechanic_id=mechanic_id))

    # ================= GET =================
    row = db.mechanics.find_one({
        "_id": oid(mechanic_id),
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if not row:
        flash("Mechanic not found.", "danger")
        return redirect(url_for("admin.company_admin_mechanics_page"))

    edit_mechanic = {
        "id": str(row.get("_id")),
        "dealer_code": row.get("dealer_code", ""),
        "name": row.get("name", ""),
        "mobile": row.get("mobile", ""),
        "email": row.get("email", ""),
        "pan": row.get("pan", ""),
        "gst": row.get("gst", ""),
        "city": row.get("city", ""),
        "state": row.get("state", ""),
        "address": row.get("address", "")
    }

    rows = db.mechanics.find({
        "company_id": company_id,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }).sort("_id", -1)

    mechanics = []

    for r in rows:
        mechanics.append({
            "id": str(r.get("_id")),
            "dealer_code": r.get("dealer_code", ""),
            "name": r.get("name", ""),
            "mobile": r.get("mobile", ""),
            "email": r.get("email", ""),
            "pan": r.get("pan", ""),
            "gst": r.get("gst", ""),
            "city": r.get("city", ""),
            "state": r.get("state", ""),
            "address": r.get("address", "")
        })

    return render_template(
        "company_admin_mechanics.html",
        mechanics=mechanics,
        edit_mechanic=edit_mechanic
    )

@admin_bp.route("/manual-redeem", methods=["POST"])
def manual_redeem():

    if "user_id" not in session:
        flash("Please login first.", "danger")
        return redirect(url_for("auth.login"))

    if session.get("user_role") != "employee":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    db = get_db()

    coupon_code = request.form.get("coupon_code", "").strip().upper()
    reason = request.form.get("reason", "").strip()
    company_id = session.get("company_id")

    if not coupon_code:
        flash("Coupon code is required.", "danger")
        return redirect(url_for("admin.general_employee_dashboard"))

    if not reason:
        flash("Reason is required for manual redeem.", "danger")
        return redirect(url_for("admin.general_employee_dashboard"))

    try:
        coupon = db.coupons.find_one({
            "code": coupon_code,
            "company_id": company_id
        })

        if not coupon:
            flash("Invalid coupon code.", "danger")
            return redirect(url_for("admin.general_employee_dashboard"))

        if int(coupon.get("is_redeemed") or 0) == 1 or coupon.get("status") == "redeemed":
            flash("This coupon is already redeemed.", "warning")
            return redirect(url_for("admin.general_employee_dashboard"))

        db.coupons.update_one(
            {"_id": coupon["_id"]},
            {
                "$set": {
                    "is_redeemed": 1,
                    "status": "redeemed",
                    "redeemed_by": session.get("user_id"),
                    "redeemed_at": now()
                }
            }
        )

        db.dealer_redemptions.insert_one({
            "dealer_id": coupon.get("dealer_id") or coupon.get("scanned_by"),
            "coupon_id": str(coupon.get("_id")),
            "coupon_code": coupon.get("code", ""),
            "redemption_type": "manual",
            "part_no": coupon.get("part_no", ""),
            "product_name": coupon.get("product_name", ""),
            "coupons_count": 1,
            "redeemed_points": int(coupon.get("points") or 0),
            "remarks": reason,
            "redeemed_by": session.get("user_id"),
            "company_id": company_id,
            "is_manual": 1,
            "created_at": now()
        })

        flash("Coupon redeemed manually successfully.", "success")

    except Exception as e:
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("admin.general_employee_dashboard"))


@admin_bp.route("/redeem-set/<coupon_id>", methods=["POST"])
def redeem_set(coupon_id):

    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    if session.get("user_role") not in ["employee", "admin"]:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    db = get_db()

    remarks = request.form.get("set_reason", "").strip()
    company_id = session.get("company_id")

    if not remarks:
        flash("Set remark is required.", "danger")
        return redirect(url_for("admin.pending_redemptions"))

    try:
        coupon = db.coupons.find_one({
            "_id": oid(coupon_id),
            "company_id": company_id
        })

        if not coupon:
            flash("Coupon not found.", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        invoice_no = coupon.get("invoice_no", "")
        dealer_id = coupon.get("dealer_id") or coupon.get("scanned_by")
        redemption_status = coupon.get("redemption_status", "pending")

        if not invoice_no:
            flash("Invoice number is required.", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        if redemption_status != "pending":
            flash("This coupon is already processed.", "warning")
            return redirect(url_for("admin.pending_redemptions"))

        db.dealer_coupon_sets.insert_one({
            "dealer_id": dealer_id,
            "coupon_id": str(coupon.get("_id")),
            "coupon_code": coupon.get("code", ""),
            "invoice_no": invoice_no,
            "part_no": coupon.get("part_no", ""),
            "product_name": coupon.get("product_name", ""),
            "points": int(coupon.get("points") or 0),
            "set_size": 10,
            "remarks": remarks,
            "created_by": session.get("user_id"),
            "company_id": company_id,
            "created_at": now()
        })

        db.coupons.update_one(
            {"_id": coupon["_id"]},
            {
                "$set": {
                    "redemption_status": "set_redeemed",
                    "updated_at": now()
                }
            }
        )

        flash("Coupon moved to set redemption successfully.", "success")

    except Exception as e:
        flash(f"Set redeem error: {str(e)}", "danger")

    return redirect(url_for("admin.pending_redemptions"))


from flask import jsonify, request

@admin_bp.route("/api/states", methods=["GET"])
def api_states():
    states = [
        "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
        "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana",
        "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
        "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
        "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
        "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
        "Uttar Pradesh", "Uttarakhand", "West Bengal"
    ]
    return jsonify({"states": states})


@admin_bp.route("/api/cities", methods=["GET"])
def api_cities():
    state = request.args.get("state", "").strip()

    state_city_map = {
        "Chhattisgarh": ["Raipur", "Bhilai", "Durg", "Bilaspur", "Korba"],
        "Madhya Pradesh": ["Bhopal", "Indore", "Jabalpur", "Gwalior"],
        "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik"],
        "Delhi": ["New Delhi", "North Delhi", "South Delhi", "East Delhi", "West Delhi"],
        "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot"],
        "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur", "Kota"],
        "Uttar Pradesh": ["Lucknow", "Kanpur", "Noida", "Varanasi"],
        "West Bengal": ["Kolkata", "Howrah", "Durgapur"],
    }

    return jsonify({"cities": state_city_map.get(state, [])})

@admin_bp.route("/redeem/material/<coupon_id>", methods=["POST"])
def redeem_material(coupon_id):

    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    db = get_db()

    try:
        invoice_no = request.form.get("invoice_no", "").strip()
        remarks = request.form.get("remarks", "").strip()
        company_id = session.get("company_id")

        if not invoice_no:
            flash("Invoice number is required.", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        coupon = db.coupons.find_one({
            "_id": oid(coupon_id),
            "company_id": company_id
        })

        if not coupon:
            flash("Coupon not found.", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        dealer_id = coupon.get("scanned_by") or coupon.get("dealer_id")
        dealer_name = "User"
        dealer_email = ""

        if dealer_id:
            dealer = db.distributors.find_one({"_id": oid(dealer_id)})
            if dealer:
                dealer_name = dealer.get("name", "User")
                dealer_email = dealer.get("email", "")

        already = db.dealer_redemptions.find_one({
            "coupon_id": str(coupon.get("_id"))
        })

        if already:
            flash("Already redeemed.", "warning")
            return redirect(url_for("admin.pending_redemptions"))

        points = int(coupon.get("points") or 0)
        coupon_code = coupon.get("code", "")

        db.dealer_redemptions.insert_one({
            "dealer_id": dealer_id,
            "coupon_id": str(coupon.get("_id")),
            "coupon_code": coupon_code,
            "invoice_no": invoice_no,
            "redemption_type": "material",
            "part_no": coupon.get("part_no", "-"),
            "product_name": coupon.get("product_name", "-"),
            "coupons_count": 1,
            "redeemed_points": points,
            "remarks": remarks,
            "redeemed_by": session.get("user_id"),
            "company_id": company_id,
            "created_at": now()
        })

        db.coupons.update_one(
            {"_id": coupon["_id"]},
            {
                "$set": {
                    "is_redeemed": 1,
                    "status": "redeemed",
                    "invoice_no": invoice_no,
                    "redeemed_at": now(),
                    "redeemed_by": session.get("user_id")
                }
            }
        )

        if dealer_email:
            send_redemption_email(
                to_email=dealer_email,
                dealer_name=dealer_name,
                coupon_code=coupon_code,
                points=points,
                redemption_type="Material Redeem",
                invoice_no=invoice_no
            )

        flash("Coupon redeemed successfully.", "success")

    except Exception as e:
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("admin.pending_redemptions"))


@admin_bp.route("/redeem/cn/<coupon_id>", methods=["POST"])
def redeem_cn(coupon_id):

    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    db = get_db()

    try:
        remarks = request.form.get("remarks", "").strip()
        company_id = session.get("company_id")

        coupon = db.coupons.find_one({
            "_id": oid(coupon_id),
            "company_id": company_id
        })

        if not coupon:
            flash("Coupon not found", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        dealer_id = coupon.get("scanned_by") or coupon.get("dealer_id")
        dealer_name = "User"
        dealer_email = ""

        if dealer_id:
            dealer = db.distributors.find_one({"_id": oid(dealer_id)})
            if dealer:
                dealer_name = dealer.get("name", "User")
                dealer_email = dealer.get("email", "")

        points = int(coupon.get("points") or 0)
        coupon_code = coupon.get("code", "")

        db.dealer_redemptions.insert_one({
            "dealer_id": dealer_id,
            "coupon_id": str(coupon.get("_id")),
            "coupon_code": coupon_code,
            "redemption_type": "credit_note",
            "part_no": coupon.get("part_no", "-"),
            "product_name": coupon.get("product_name", "-"),
            "coupons_count": 1,
            "redeemed_points": points,
            "remarks": remarks,
            "redeemed_by": session.get("user_id"),
            "company_id": company_id,
            "created_at": now()
        })

        db.coupons.update_one(
            {"_id": coupon["_id"]},
            {
                "$set": {
                    "is_redeemed": 1,
                    "status": "redeemed",
                    "redeemed_at": now(),
                    "redeemed_by": session.get("user_id")
                }
            }
        )

        if dealer_email:
            send_redemption_email(
                to_email=dealer_email,
                dealer_name=dealer_name,
                coupon_code=coupon_code,
                points=points,
                redemption_type="Credit Note"
            )

        flash("Credit note redeemed", "success")

    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("admin.pending_redemptions"))