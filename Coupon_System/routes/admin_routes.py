import code

from bson import ObjectId
from extensions import mail
from datetime import datetime, timedelta
from flask_mail import Message
import os
import io
from extensions import mail, csrf
from werkzeug.utils import secure_filename
import uuid
import pandas as pd
from flask import Blueprint, app, render_template, session, redirect, url_for, flash, request, current_app, send_file 
from werkzeug.security import generate_password_hash
from utils.qr_generator import generate_qr
import random
import string
import win32print
import secrets


def generate_code(length=16):
    characters = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))


admin_bp = Blueprint("admin", __name__)

print("admin_routes imported")


PRINTER_NAME = "TSC TE244"

def send_raw_to_usb_printer(raw_data: str):
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
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT id
        FROM subscriptions
        WHERE user_id = %s
          AND status = 'active'
          AND end_date > NOW()
        LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    cur.close()

    return bool(row)

def is_company_trial_expired(company_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT s.id
        FROM subscriptions s
        JOIN users u ON s.user_id = u.id
        WHERE u.company_id = %s
          AND u.account_type = 'trial'
          AND u.role = 'admin'
          AND s.status = 'active'
          AND s.end_date > NOW()
        LIMIT 1
    """, (company_id,))

    active_trial = cur.fetchone()
    cur.close()

    return not bool(active_trial)

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
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT id
        FROM users
        WHERE company_id = %s
          AND role = 'admin'
          AND account_type = 'trial'
          AND (is_deleted = 0 OR is_deleted IS NULL)
        LIMIT 1
    """, (company_id,))

    row = cur.fetchone()
    cur.close()
    return bool(row)

def deactivate_expired_trial_company(company_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        cur.execute("""
            UPDATE users
            SET is_deleted = 1,
                is_online = 0,
                deleted_at = NOW()
            WHERE company_id = %s
              AND role IN ('admin', 'employee', 'qr_employee', 'sales')
              AND account_type = 'trial'
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (company_id,))

        mysql.connection.commit()
        cur.close()
        return True

    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        print("TRIAL COMPANY DEACTIVATE ERROR:", str(e))
        return False
    

def has_active_trial_for_company(company_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT s.id
        FROM subscriptions s
        JOIN users u ON s.user_id = u.id
        WHERE u.company_id = %s
          AND u.role = 'admin'
          AND u.account_type = 'trial'
          AND s.status = 'active'
          AND s.end_date > NOW()
        LIMIT 1
    """, (company_id,))

    row = cur.fetchone()
    cur.close()
    return bool(row)

def is_trial_admin(user_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT account_type
        FROM users
        WHERE id = %s
        LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    cur.close()

    if not row:
        return False

    return (row[0] or "").strip().lower() == "trial"



def build_coupon_zpl(part_no, mrp, pack_size, points, code, brand_name, qr_size="25x50"):

    if qr_size == "50x50":
        return f"""
^XA
^PW400
^LL400
^LH0,0

^FO0,0^GB400,400,2^FS

^FO0,0^GB58,400,58^FS

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
^FO8,15^A0B,24,24^FD{brand_name}^FS

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
    msg = Message(
        subject="Coupon Redeemed Successfully",
        recipients=[to_email]
    )

    msg.body = f"""
Hello {dealer_name},

Your coupon has been redeemed successfully.

Details:
Coupon Code : {coupon_code}
Points      : {points}
Type        : {redemption_type}
Invoice No  : {invoice_no if invoice_no else 'N/A'}

Thank you,
FLOWRA Team
"""
    mail.send(msg)

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
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT active_token
        FROM distributors
        WHERE id = %s
        LIMIT 1
    """, (dealer_id,))
    row = cur.fetchone()
    cur.close()

    if not row:
        return False

    db_token = row[0]
    return bool(db_token and db_token == token)


def _get_entity_template(entity_type: str) -> str:
    mapping = {
        "distributors": "company_admin_distributors.html",
        "retailers": "company_admin_retailers.html",
        "mechanics": "company_admin_mechanics.html",
    }
    return mapping.get(entity_type, "company_admin_distributors.html")


def _fetch_entities(entity_type: str, company_id: int):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute(f"""
        SELECT
            id,
            dealer_code,
            name,
            mobile,
            email,
            pan,
            gst,
            city,
            state,
            address
        FROM {entity_type}
        WHERE company_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY id DESC
    """, (company_id,))

    rows = cur.fetchall()
    cur.close()

    data = []
    for row in rows:
        data.append({
            "id": row[0],
            "dealer_code": row[1] or "",
            "name": row[2] or "",
            "mobile": row[3] or "",
            "email": row[4] or "",
            "pan": row[5] or "",
            "gst": row[6] or "",
            "city": row[7] or "",
            "state": row[8] or "",
            "address": row[9] or "",
        })
    return data


def _fetch_single_entity(entity_type: str, company_id: int, record_id: int):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute(f"""
        SELECT
            id,
            dealer_code,
            name,
            mobile,
            email,
            pan,
            gst,
            city,
            state,
            address
        FROM {entity_type}
        WHERE id = %s
          AND company_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        LIMIT 1
    """, (record_id, company_id))

    row = cur.fetchone()
    cur.close()

    if not row:
        return None

    return {
        "id": row[0],
        "dealer_code": row[1] or "",
        "name": row[2] or "",
        "mobile": row[3] or "",
        "email": row[4] or "",
        "pan": row[5] or "",
        "gst": row[6] or "",
        "city": row[7] or "",
        "state": row[8] or "",
        "address": row[9] or "",
    }

@admin_bp.route("/super-admin/companies", methods=["GET", "POST"])
def company_management():
    if "user_id" not in session or session.get("user_role") != "super_admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        admin_name = request.form.get("admin_name", "").strip()
        admin_email = request.form.get("admin_email", "").strip()
        admin_password = request.form.get("admin_password", "").strip()
        status = request.form.get("status", "Active").strip()

        if not company_name or not admin_name or not admin_email or not admin_password:
            flash("Please fill all required fields.", "danger")
            return redirect(url_for("admin.company_management"))

        cur = mysql.connection.cursor()

        cur.execute("SELECT id FROM users WHERE email = %s", (admin_email,))
        existing = cur.fetchone()

        if existing:
            cur.close()
            flash("Admin email already exists!", "danger")
            return redirect(url_for("admin.company_management"))

        try:
            hashed_password = generate_password_hash(admin_password)

            cur.execute(
                "INSERT INTO companies (name, status) VALUES (%s, %s)",
                (company_name, status)
            )
            company_id = cur.lastrowid

            cur.execute(
                "INSERT INTO users (name, email, password, role, company_id, is_online, is_deleted) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (admin_name, admin_email, hashed_password, "admin", company_id, 0, 0)
            )

            mysql.connection.commit()
            cur.close()

            flash("Company created successfully.", "success")
            return redirect(url_for("admin.company_management"))

        except Exception as e:
            cur.close()
            flash(f"Error creating company: {str(e)}", "danger")
            return redirect(url_for("admin.company_management"))

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.id, c.name, c.status, u.name
        FROM companies c
        LEFT JOIN users u ON c.id = u.company_id AND u.role = 'admin'
        WHERE c.is_deleted = 0
        ORDER BY c.id DESC
    """)
    rows = cur.fetchall()
    cur.close()

    companies = []
    for row in rows:
        companies.append({
            "id": row[0],
            "name": row[1],
            "status": row[2],
            "admin": row[3] if row[3] else "N/A"
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

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    admin_account_type = session.get("account_type", "paid")

    cur = mysql.connection.cursor()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        allowed_roles = ["employee", "qr_employee", "sales"]

        if not name or not email or not password or not role:
            cur.close()
            flash("Please fill all fields.", "danger")
            return redirect(url_for("admin.manage_employees"))

        if role not in allowed_roles:
            cur.close()
            flash("Invalid role selected.", "danger")
            return redirect(url_for("admin.manage_employees"))

        try:
            cur.execute("""
                SELECT id
                FROM users
                WHERE email = %s
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                LIMIT 1
            """, (email,))
            existing_user = cur.fetchone()

            if existing_user:
                cur.close()
                flash("Email already exists. Please use a different email.", "danger")
                return redirect(url_for("admin.manage_employees"))

            hashed_password = generate_password_hash(password)

            cur.execute("""
                INSERT INTO users
                (name, email, password, role, company_id, is_online, is_deleted, account_type, trial_used)
                VALUES (%s, %s, %s, %s, %s, 0, 0, %s, 0)
            """, (
                name,
                email,
                hashed_password,
                role,
                company_id,
                admin_account_type
            ))

            mysql.connection.commit()
            cur.close()

            flash("Employee created successfully!", "success")
            return redirect(url_for("admin.manage_employees"))

        except Exception as e:
            mysql.connection.rollback()
            cur.close()
            flash(f"Error creating employee: {str(e)}", "danger")
            return redirect(url_for("admin.manage_employees"))

    cur.execute("""
        SELECT id, name, email, role
        FROM users
        WHERE company_id = %s
          AND role IN ('employee', 'qr_employee', 'sales')
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY id DESC
    """, (company_id,))
    employees = cur.fetchall()
    cur.close()

    return render_template("manage_employees.html", employees=employees)


@admin_bp.route("/company-admin/employee/delete/<int:employee_id>", methods=["POST"])
def delete_employee(employee_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    expired_redirect = block_if_trial_company_expired()
    if expired_redirect:
        return expired_redirect

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE users
            SET is_deleted = 1,
                deleted_at = NOW(),
                is_online = 0
            WHERE id = %s
              AND company_id = %s
              AND role IN ('employee', 'qr_employee', 'sales')
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (employee_id, company_id))

        mysql.connection.commit()

        if cur.rowcount == 0:
            cur.close()
            flash("Employee not found or delete not allowed.", "danger")
            return redirect(url_for("admin.manage_employees"))

        cur.close()
        flash("Employee removed successfully.", "success")

    except Exception as e:
        flash(f"Error deleting employee: {str(e)}", "danger")

    return redirect(url_for("admin.manage_employees"))


@admin_bp.route("/super-admin/company/edit/<int:company_id>", methods=["GET", "POST"])
def edit_company(company_id):
    if "user_id" not in session or session.get("user_role") != "super_admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        status = request.form.get("status", "").strip()
        admin_name = request.form.get("admin_name", "").strip()

        cur.execute(
            "UPDATE companies SET name = %s, status = %s WHERE id = %s",
            (company_name, status, company_id)
        )

        cur.execute(
            "UPDATE users SET name = %s WHERE company_id = %s AND role = 'admin'",
            (admin_name, company_id)
        )

        mysql.connection.commit()
        cur.close()

        flash("Company updated successfully.", "success")
        return redirect(url_for("admin.company_management"))

    cur.execute("""
        SELECT c.id, c.name, c.status, u.name
        FROM companies c
        LEFT JOIN users u ON c.id = u.company_id AND u.role = 'admin'
        WHERE c.id = %s
        LIMIT 1
    """, (company_id,))
    row = cur.fetchone()
    cur.close()

    if not row:
        flash("Company not found.", "danger")
        return redirect(url_for("admin.company_management"))

    company = {
        "id": row[0],
        "name": row[1],
        "status": row[2],
        "admin_name": row[3] if row[3] else ""
    }

    return render_template("edit_company.html", company=company)


@admin_bp.route("/super-admin/company/delete/<int:company_id>", methods=["POST"])
def delete_company(company_id):
    if "user_id" not in session or session.get("user_role") != "super_admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]

    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "UPDATE companies SET is_deleted = 1, deleted_at = NOW() WHERE id = %s",
            (company_id,)
        )
        mysql.connection.commit()
        cur.close()

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

            qr_data = f"https://192.168.1.13:5000/scan/{code}"
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

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    # Pending redemptions
    cur.execute("""
        SELECT COUNT(*)
        FROM coupons
        WHERE company_id = %s
          AND scanned_at IS NOT NULL
          AND status = 'scanned'
          AND (is_deleted = 0 OR is_deleted IS NULL)
    """, (company_id,))
    pending_redemptions = cur.fetchone()[0] or 0

    # Redeemed coupons
    cur.execute("""
        SELECT COUNT(*)
        FROM coupons
        WHERE company_id = %s
          AND status IN ('redeemed','material_redeemed','credit_note_issued','credit_note')
          AND (is_deleted = 0 OR is_deleted IS NULL)
    """, (company_id,))
    redeemed_count = cur.fetchone()[0] or 0

    # Total dealers
    cur.execute("""
        SELECT COUNT(*)
        FROM distributors
        WHERE company_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
    """, (company_id,))
    total_dealers = cur.fetchone()[0] or 0

    # ✅ FIX: wallet points from wallet table (not coupons)
    cur.execute("""
        SELECT COALESCE(SUM(total_points), 0)
        FROM dealer_wallets
    """)
    total_wallet_points = cur.fetchone()[0] or 0

    # extra stats
    cur.execute("""
        SELECT COUNT(*)
        FROM coupons
        WHERE company_id = %s
          AND scanned_at IS NOT NULL
    """, (company_id,))
    total_scans = cur.fetchone()[0] or 0

    cur.execute("""
        SELECT COUNT(*)
        FROM coupons
        WHERE company_id = %s
    """, (company_id,))
    total_coupons = cur.fetchone()[0] or 0

    cur.close()

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

                qr_data = f"https://192.168.1.13:5000/scan/{code}"
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

@admin_bp.route("/company-admin/employee/edit/<int:employee_id>", methods=["GET", "POST"])
def edit_employee(employee_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        allowed_roles = ["employee", "qr_employee", "sales"]

        if not name or not email or not role:
            cur.close()
            flash("Please fill all required fields.", "danger")
            return redirect(url_for("admin.edit_employee", employee_id=employee_id))

        if role not in allowed_roles:
            cur.close()
            flash("Invalid role selected.", "danger")
            return redirect(url_for("admin.edit_employee", employee_id=employee_id))

        try:
            # same email kisi aur employee ka na ho
            cur.execute("""
                SELECT id
                FROM users
                WHERE email = %s
                  AND id != %s
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                LIMIT 1
            """, (email, employee_id))
            existing_email = cur.fetchone()

            if existing_email:
                cur.close()
                flash("This email is already used by another user.", "danger")
                return redirect(url_for("admin.edit_employee", employee_id=employee_id))

            # password diya hai to password bhi update karo
            if password:
                hashed_password = generate_password_hash(password)

                cur.execute("""
                    UPDATE users
                    SET name = %s,
                        email = %s,
                        password = %s,
                        role = %s
                    WHERE id = %s
                      AND company_id = %s
                      AND role IN ('employee', 'qr_employee', 'sales')
                      AND (is_deleted = 0 OR is_deleted IS NULL)
                """, (name, email, hashed_password, role, employee_id, company_id))
            else:
                cur.execute("""
                    UPDATE users
                    SET name = %s,
                        email = %s,
                        role = %s
                    WHERE id = %s
                      AND company_id = %s
                      AND role IN ('employee', 'qr_employee', 'sales')
                      AND (is_deleted = 0 OR is_deleted IS NULL)
                """, (name, email, role, employee_id, company_id))

            mysql.connection.commit()

            if cur.rowcount == 0:
                cur.close()
                flash("Employee not found or update not allowed.", "danger")
                return redirect(url_for("admin.manage_employees"))

            cur.close()
            flash("Employee updated successfully.", "success")
            return redirect(url_for("admin.manage_employees"))

        except Exception as e:
            mysql.connection.rollback()
            cur.close()
            flash(f"Error updating employee: {str(e)}", "danger")
            return redirect(url_for("admin.edit_employee", employee_id=employee_id))

    # GET request ke liye employee fetch karo
    cur.execute("""
        SELECT id, name, email, role
        FROM users
        WHERE id = %s
          AND company_id = %s
          AND role IN ('employee', 'qr_employee', 'sales')
          AND (is_deleted = 0 OR is_deleted IS NULL)
        LIMIT 1
    """, (employee_id, company_id))
    row = cur.fetchone()
    cur.close()

    if not row:
        flash("Employee not found.", "danger")
        return redirect(url_for("admin.manage_employees"))

    employee = {
        "id": row[0],
        "name": row[1] or "",
        "email": row[2] or "",
        "role": row[3] or ""
    }

    return render_template("edit_employee.html", employee=employee)



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

    # -----------------------------
    # PART NUMBER DROPDOWN
    # -----------------------------
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
        {
            "$sort": {
                "_id": 1
            }
        }
    ]

    parts = []

    for item in db.coupons.aggregate(pipeline):

        parts.append((
            item.get("_id", ""),
            item.get("product_name", "")
        ))

    # -----------------------------
    # FORM SUBMIT
    # -----------------------------
    if request.method == "POST":

        search_text = request.form.get("search_text", "").strip()

        selected_qr_size = request.form.get(
            "qr_size",
            "25x50"
        ).strip()

        brand_name = request.form.get(
            "brand_name",
            ""
        ).strip()

        try:
            count = int(request.form.get("count", 10) or 10)

            if count <= 0:
                count = 1

        except:
            count = 1

        if not search_text:

            flash("Please select part number.", "danger")

            return render_template(
                "coupon_generator.html",
                parts=parts,
                brand_name=brand_name,
                selected_qr_size=selected_qr_size,
                count=count
            )

        # -----------------------------
        # FETCH PRODUCT
        # -----------------------------
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

            return render_template(
                "coupon_generator.html",
                parts=parts,
                brand_name=brand_name,
                selected_qr_size=selected_qr_size,
                count=count
            )

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

                # -----------------------------
                # UNIQUE CODE
                # -----------------------------
                code = generate_code(16)

                while db.coupons.find_one({"code": code}):
                    code = generate_code(16)

                # -----------------------------
                # QR GENERATE
                # -----------------------------
                qr_data = f"https://192.168.1.13:5000/scan/{code}"

                filename = f"{code}.png"

                qr_path = generate_qr(qr_data, filename)

                # -----------------------------
                # SAVE COUPON
                # -----------------------------
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

                # -----------------------------
                # ZPL BUILD
                # -----------------------------
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

            # -----------------------------
            # PRINT
            # -----------------------------
            send_raw_to_usb_printer(zpl_batch)

            flash(
                f"{generated_count} coupons generated & printed!",
                "success"
            )

        except Exception as e:

            flash(
                f"Error: {str(e)}",
                "danger"
            )

        return redirect(url_for("admin.coupon_generator"))

    # -----------------------------
    # PAGE LOAD
    # -----------------------------
    return render_template(
        "coupon_generator.html",
        parts=parts,
        brand_name=brand_name,
        selected_qr_size=selected_qr_size,
        count=count
    )






@admin_bp.route("/company-admin/analytics")
def company_admin_analytics():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(points), 0)
        FROM coupons
        WHERE company_id = %s AND is_deleted = 0
    """, (company_id,))
    row = cur.fetchone()
    total_generated = row[0] or 0
    total_points_generated = row[1] or 0

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(points), 0)
        FROM coupons
        WHERE company_id = %s AND is_deleted = 0 AND scanned_at IS NOT NULL
    """, (company_id,))
    row = cur.fetchone()
    total_scanned = row[0] or 0
    total_points_scanned = row[1] or 0

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(points), 0)
        FROM coupons
        WHERE company_id = %s AND is_deleted = 0 AND status = 'redeemed'
    """, (company_id,))
    row = cur.fetchone()
    total_redeemed = row[0] or 0
    total_points_redeemed = row[1] or 0

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(points), 0)
        FROM coupons
        WHERE company_id = %s
          AND is_deleted = 0
          AND scanned_at IS NOT NULL
          AND status = 'scanned'
    """, (company_id,))
    row = cur.fetchone()
    scanned_not_redeemed = row[0] or 0
    points_scanned_not_redeemed = row[1] or 0

    cur.execute("""
        SELECT COALESCE(u.name, 'Unknown'),
               COUNT(c.id),
               COALESCE(SUM(c.points), 0)
        FROM coupons c
        LEFT JOIN users u ON c.created_by = u.id
        WHERE c.company_id = %s
          AND c.is_deleted = 0
        GROUP BY u.name
        ORDER BY COUNT(c.id) DESC
        LIMIT 15
    """, (company_id,))
    generated_by_user = cur.fetchall()

    # FIXED: scanned by actual distributor/dealer name
    cur.execute("""
        SELECT 
            COALESCE(d.name, 'Unknown') AS scanned_by,
            COUNT(c.id) AS scanned_count,
            COALESCE(SUM(c.points), 0) AS total_points
        FROM coupons c
        LEFT JOIN distributors d ON c.scanned_by = d.id
        WHERE c.company_id = %s
          AND c.is_deleted = 0
          AND c.scanned_at IS NOT NULL
          AND c.status IN ('scanned', 'redeemed')
        GROUP BY c.scanned_by, d.name
        ORDER BY scanned_count DESC
    """, (company_id,))
    scanned_by_user = cur.fetchall()

    cur.close()

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

    
    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT
            id,
            code,
            product_name,
            part_no,
            pack_size,
            points,
            status,
            DATE(created_at) AS created_date,
            DATE(scanned_at) AS scanned_date,
            DATE(redeemed_at) AS redeemed_date
        FROM coupons
        WHERE company_id = %s AND is_deleted = 0
        ORDER BY id DESC
        LIMIT 300
    """, (company_id,))

    history_rows = cur.fetchall()
    cur.close()

    return render_template("company_admin_history.html", history_rows=history_rows)

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

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    employee_count = 0
    distributor_count = 0
    retailer_count = 0
    mechanic_count = 0
    product_count = 0
    catalogue_count = 0
    total_generated = 0
    total_scans = 0
    redeemed_count = 0
    pending_count = 0

    try:
        company_id = session.get("company_id")

        cur.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE company_id = %s
              AND role IN ('employee', 'qr_employee', 'redeem_employee', 'sales')
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (company_id,))
        row = cur.fetchone()
        employee_count = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM distributors
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (company_id,))
        row = cur.fetchone()
        distributor_count = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM retailers
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (company_id,))
        row = cur.fetchone()
        retailer_count = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM mechanics
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (company_id,))
        row = cur.fetchone()
        mechanic_count = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT part_no, product_name, product_type, pack_size, mrp, dlp, points, qr_size
                FROM coupons
                WHERE company_id = %s
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                  AND part_no IS NOT NULL
                  AND product_name IS NOT NULL
                  AND part_no <> ''
                  AND product_name <> ''
                GROUP BY part_no, product_name, product_type, pack_size, mrp, dlp, points, qr_size
            ) x
        """, (company_id,))
        row = cur.fetchone()
        product_count = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM catalogues
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (company_id,))
        row = cur.fetchone()
        catalogue_count = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM coupons
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (company_id,))
        row = cur.fetchone()
        total_generated = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM coupons
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
              AND scanned_at IS NOT NULL
        """, (company_id,))
        row = cur.fetchone()
        total_scans = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM coupons
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
              AND (
                    is_redeemed = 1
                    OR status IN ('redeemed', 'material_redeemed', 'credit_note_issued', 'set_redeemed', 'credit_note')
              )
        """, (company_id,))
        row = cur.fetchone()
        redeemed_count = row[0] if row else 0

        cur.execute("""
            SELECT COUNT(*)
            FROM coupons
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
              AND (
                    status = 'scanned'
                    OR (
                        scanned_at IS NOT NULL
                        AND (is_redeemed = 0 OR is_redeemed IS NULL)
                    )
              )
        """, (company_id,))
        row = cur.fetchone()
        pending_count = row[0] if row else 0

    except Exception as e:
        flash(f"Dashboard error: {str(e)}", "danger")

    finally:
        cur.close()

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
    

@admin_bp.route("/company-admin/retailers")
def company_admin_retailers_page():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

   
    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
        FROM retailers
        WHERE company_id = %s AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY id DESC
    """, (company_id,))
    rows = cur.fetchall()
    cur.close()

    retailers = []
    for row in rows:
        retailers.append({
            "id": row[0],
            "dealer_code": row[1],
            "name": row[2],
            "mobile": row[3],
            "email": row[4],
            "pan": row[5],
            "gst": row[6],
            "city": row[7],
            "state": row[8],
            "address": row[9]
        })

    return render_template("company_admin_retailers.html", retailers=retailers)

@admin_bp.route("/company-admin/retailers/add", methods=["POST"])
def add_retailer():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

   

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    dealer_code = request.form.get("dealer_code")
    name = request.form.get("name")
    mobile = request.form.get("mobile")
    email = request.form.get("email")
    password = request.form.get("password")
    pan = request.form.get("pan")
    gst = request.form.get("gst")
    city = request.form.get("city")
    state = request.form.get("state")
    address = request.form.get("address")

    hashed_password = generate_password_hash(password) if password else None

    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO retailers
        (dealer_code, name, mobile, email, password, pan, gst, city, state, address, company_id, is_deleted)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
    """, (
        dealer_code, name, mobile, email, hashed_password,
        pan, gst, city, state, address, company_id
    ))
    mysql.connection.commit()
    cur.close()

    flash("Retailer added successfully.", "success")
    return redirect(url_for("admin.company_admin_retailers_page"))


@admin_bp.route("/company-admin/mechanics")
def company_admin_mechanics_page():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

   
    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
        FROM mechanics
        WHERE company_id = %s AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY id DESC
    """, (company_id,))
    rows = cur.fetchall()
    cur.close()

    mechanics = []
    for row in rows:
        mechanics.append({
            "id": row[0],
            "dealer_code": row[1],
            "name": row[2],
            "mobile": row[3],
            "email": row[4],
            "pan": row[5],
            "gst": row[6],
            "city": row[7],
            "state": row[8],
            "address": row[9]
        })

    return render_template("company_admin_mechanics.html", mechanics=mechanics)

@admin_bp.route("/company-admin/mechanics/add", methods=["POST"])
def add_mechanic():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

   

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    dealer_code = request.form.get("dealer_code")
    name = request.form.get("name")
    mobile = request.form.get("mobile")
    email = request.form.get("email")
    password = request.form.get("password")
    pan = request.form.get("pan")
    gst = request.form.get("gst")
    city = request.form.get("city")
    state = request.form.get("state")
    address = request.form.get("address")

    hashed_password = generate_password_hash(password) if password else None

    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO mechanics
        (dealer_code, name, mobile, email, password, pan, gst, city, state, address, company_id, is_deleted)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
    """, (
        dealer_code, name, mobile, email, hashed_password,
        pan, gst, city, state, address, company_id
    ))
    mysql.connection.commit()
    cur.close()

    flash("Mechanic added successfully.", "success")
    return redirect(url_for("admin.company_admin_mechanics_page"))

@admin_bp.route("/company-admin/products")
def company_admin_products_page():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT
            MIN(id) AS id,
            part_no,
            product_name,
            product_type,
            pack_size,
            mrp,
            dlp,
            points,
            qr_size,
            COUNT(*) AS total_coupons
        FROM coupons
        WHERE company_id = %s
          AND is_deleted = 0
          AND part_no IS NOT NULL
          AND product_name IS NOT NULL
          AND part_no != ''
          AND product_name != ''
        GROUP BY part_no, product_name, product_type, pack_size, mrp, dlp, points, qr_size
        ORDER BY MAX(id) DESC
    """, (company_id,))
    rows = cur.fetchall()
    cur.close()

    print("SESSION company_id =", company_id)
    print("PRODUCT ROWS =", rows)

    products = []
    for r in rows:
        products.append({
            "id": r[0],
            "part_no": r[1],
            "product_name": r[2],
            "product_type": r[3],
            "pack_size": r[4],
            "mrp": r[5],
            "dlp": r[6],
            "points": r[7],
            "qr_size": r[8],
            "total_coupons": r[9]
        })

    return render_template("company_admin_products.html", products=products)
@admin_bp.route("/company-admin/products/export")
def export_products():
    from flask import send_file
    import pandas as pd
    import io

    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT part_no, product_name, product_type, pack_size, mrp, dlp, points
        FROM products
        WHERE company_id = %s
        ORDER BY id DESC
    """, (company_id,))
    rows = cur.fetchall()
    cur.close()

    df = pd.DataFrame(rows, columns=[
        "part_no", "product_name", "product_type",
        "pack_size", "mrp", "dlp", "points"
    ])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

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

    if not file:
        flash("No file selected", "danger")
        return redirect(url_for("admin.company_admin_products_page"))

    try:
        df = pd.read_excel(file)

        mysql = current_app.config["MYSQL_INSTANCE"]
        company_id = session.get("company_id")

        cur = mysql.connection.cursor()

        for _, row in df.iterrows():
            cur.execute("""
                INSERT INTO products 
                (part_no, product_name, product_type, pack_size, mrp, dlp, points, company_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                row.get("part_no"),
                row.get("product_name"),
                row.get("product_type"),
                row.get("pack_size"),
                row.get("mrp"),
                row.get("dlp"),
                row.get("points"),
                company_id
            ))

        mysql.connection.commit()
        cur.close()

        flash("Products imported successfully", "success")

    except Exception as e:
        flash(f"Import failed: {str(e)}", "danger")

    return redirect(url_for("admin.company_admin_products_page"))

@admin_bp.route("/company-admin/export-all-data")
def export_all_data():
    from flask import send_file
    import pandas as pd
    import io

    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Products
        cur.execute("""
            SELECT part_no, product_name, product_type, pack_size, mrp, dlp, points
            FROM products
            WHERE company_id = %s
            ORDER BY id DESC
        """, (company_id,))
        rows = cur.fetchall()
        pd.DataFrame(rows, columns=[
            "part_no", "product_name", "product_type",
            "pack_size", "mrp", "dlp", "points"
        ]).to_excel(writer, index=False, sheet_name="Products")

        # Distributors
        cur.execute("""
            SELECT dealer_code, name, mobile, email, pan, gst, city, state, address
            FROM distributors
            WHERE company_id = %s AND (is_deleted = 0 OR is_deleted IS NULL)
            ORDER BY id DESC
        """, (company_id,))
        rows = cur.fetchall()
        pd.DataFrame(rows, columns=[
            "dealer_code", "name", "mobile", "email",
            "pan", "gst", "city", "state", "address"
        ]).to_excel(writer, index=False, sheet_name="Distributors")

        # Retailers
        cur.execute("""
            SELECT dealer_code, name, mobile, email, pan, gst, city, state, address
            FROM retailers
            WHERE company_id = %s AND (is_deleted = 0 OR is_deleted IS NULL)
            ORDER BY id DESC
        """, (company_id,))
        rows = cur.fetchall()
        pd.DataFrame(rows, columns=[
            "dealer_code", "name", "mobile", "email",
            "pan", "gst", "city", "state", "address"
        ]).to_excel(writer, index=False, sheet_name="Retailers")

        # Mechanics
        cur.execute("""
            SELECT dealer_code, name, mobile, email, pan, gst, city, state, address
            FROM mechanics
            WHERE company_id = %s AND (is_deleted = 0 OR is_deleted IS NULL)
            ORDER BY id DESC
        """, (company_id,))
        rows = cur.fetchall()
        pd.DataFrame(rows, columns=[
            "dealer_code", "name", "mobile", "email",
            "pan", "gst", "city", "state", "address"
        ]).to_excel(writer, index=False, sheet_name="Mechanics")

        # Coupons
        cur.execute("""
            SELECT *
            FROM coupons
            WHERE company_id = %s
            ORDER BY id DESC
        """, (company_id,))
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        pd.DataFrame(rows, columns=columns).to_excel(writer, index=False, sheet_name="Coupons")

    cur.close()
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="all_company_data.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@admin_bp.route("/company-admin/products/add", methods=["POST"])
def add_product():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))


    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    part_no = request.form.get("part_no")
    product_name = request.form.get("product_name")
    product_type = request.form.get("product_type")
    pack_size = request.form.get("pack_size")
    mrp = request.form.get("mrp")
    dlp = request.form.get("dlp")
    points = request.form.get("points")

    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO products 
        (part_no, product_name, product_type, pack_size, mrp, dlp, points, company_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (part_no, product_name, product_type, pack_size, mrp, dlp, points, company_id))

    mysql.connection.commit()
    cur.close()

    return redirect(url_for("admin.company_admin_products_page"))



@admin_bp.route("/company-admin/banners")
def company_admin_banners_page():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, title, image
        FROM banners
        WHERE company_id = %s
        ORDER BY id DESC
    """, (company_id,))
    banners = cur.fetchall()
    cur.close()

    return render_template("company_admin_banners.html", banners=banners)


@admin_bp.route("/company-admin/banners/add", methods=["POST"])
def add_banner():
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
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

    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO banners (title, image, company_id)
        VALUES (%s, %s, %s)
    """, (title, unique_filename, company_id))
    mysql.connection.commit()
    cur.close()

    flash("Banner added successfully.", "success")
    return redirect(url_for("admin.company_admin_banners_page"))


@admin_bp.route("/company-admin/banners/delete/<int:id>", methods=["POST"])
def delete_banner(id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT image
        FROM banners
        WHERE id = %s AND company_id = %s
    """, (id, company_id))
    row = cur.fetchone()

    if row:
        image_filename = row[0]
        image_path = os.path.join(current_app.root_path, "static", "uploads", image_filename)

        cur.execute("""
            DELETE FROM banners
            WHERE id = %s AND company_id = %s
        """, (id, company_id))
        mysql.connection.commit()

        if image_filename and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception:
                pass

    cur.close()

    flash("Banner deleted successfully.", "success")
    return redirect(url_for("admin.company_admin_banners_page"))


@admin_bp.route("/company-admin/catalogues")
def company_admin_catalogues_page():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, title, file_name, file_path, created_at
        FROM catalogues
        WHERE company_id = %s AND is_deleted = 0
        ORDER BY id DESC
    """, (company_id,))
    rows = cur.fetchall()
    cur.close()

    catalogues = []
    for row in rows:
        catalogues.append({
            "id": row[0],
            "title": row[1],
            "file_name": row[2],
            "file_path": row[3],
            "created_at": row[4]
        })

    return render_template("company_admin_catalogues.html", catalogues=catalogues)

@admin_bp.route("/company-admin/catalogues/add", methods=["POST"])
def add_catalogue():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")

    title = request.form.get("title", "").strip()
    pdf_file = request.files.get("pdf_file")

    if not title or not pdf_file:
        flash("Title and PDF file are required.", "danger")
        return redirect(url_for("admin.company_admin_catalogues_page"))

    if not pdf_file.filename.lower().endswith(".pdf"):
        flash("Only PDF files are allowed.", "danger")
        return redirect(url_for("admin.company_admin_catalogues_page"))

    filename = secure_filename(pdf_file.filename)
    upload_folder = os.path.join("static", "catalogues")

    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)

    file_path = os.path.join(upload_folder, filename)
    pdf_file.save(file_path)

    db_path = f"catalogues/{filename}"

    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO catalogues (title, file_name, file_path, company_id, is_deleted)
        VALUES (%s, %s, %s, %s, 0)
    """, (title, filename, db_path, company_id))
    mysql.connection.commit()
    cur.close()

    flash("Catalogue uploaded successfully.", "success")
    return redirect(url_for("admin.company_admin_catalogues_page"))

@admin_bp.route("/company-admin/catalogues/delete/<int:id>", methods=["POST"])
def delete_catalogue(id):
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE catalogues
        SET is_deleted = 1
        WHERE id = %s
    """, (id,))
    mysql.connection.commit()
    cur.close()

    flash("Catalogue deleted successfully.", "success")
    return redirect(url_for("admin.company_admin_catalogues_page"))

@admin_bp.route("/salesman/dashboard")
def salesman_dashboard():
    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()
    salesman_id = session["user_id"]

    cur.execute("""
        SELECT COUNT(*)
        FROM distributors
        WHERE salesman_id = %s AND (is_deleted = 0 OR is_deleted IS NULL)
    """, (salesman_id,))
    total_dealers = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM dealer_orders
        WHERE salesman_id = %s
    """, (salesman_id,))
    total_orders = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM dealer_orders
        WHERE salesman_id = %s AND order_status = 'pending'
    """, (salesman_id,))
    pending_orders = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM dealer_orders
        WHERE salesman_id = %s AND order_status = 'completed'
    """, (salesman_id,))
    completed_orders = cur.fetchone()[0]

    cur.close()

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

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()
    salesman_id = session["user_id"]

    cur.execute("""
        SELECT id, dealer_code, name, mobile, email, city, state, address
        FROM distributors
        WHERE salesman_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY id DESC
    """, (salesman_id,))
    dealers = cur.fetchall()
    cur.close()

    return render_template("salesman_dealers.html", dealers=dealers)

@admin_bp.route("/salesman/dealers/add", methods=["GET", "POST"])
def salesman_add_dealer():
    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        mysql = current_app.config["MYSQL_INSTANCE"]
        cur = mysql.connection.cursor()

        dealer_code = request.form.get("dealer_code")
        name = request.form.get("name")
        mobile = request.form.get("mobile")
        email = request.form.get("email")
        password = request.form.get("password")
        pan = request.form.get("pan")
        gst = request.form.get("gst")
        city = request.form.get("city")
        state = request.form.get("state")
        address = request.form.get("address")

        hashed_password = generate_password_hash(password) if password else None

        cur.execute("""
            INSERT INTO distributors
            (dealer_code, name, mobile, email, password, pan, gst, city, state, address, company_id, salesman_id, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
        """, (
            dealer_code, name, mobile, email, hashed_password, pan, gst,
            city, state, address, session["company_id"], session["user_id"]
        ))
        mysql.connection.commit()
        cur.close()

        flash("Dealer created successfully.", "success")
        return redirect(url_for("admin.salesman_dealers"))

    return render_template("salesman_add_dealer.html")

@admin_bp.route("/salesman/orders")
def salesman_orders():
    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT
            o.id,
            o.order_no,
            d.name AS dealer_name,
            o.part_no,
            o.part_name,
            o.order_status,
            o.total_amount,
            o.created_at
        FROM dealer_orders o
        JOIN distributors d ON o.dealer_id = d.id
        WHERE o.salesman_id = %s
        ORDER BY o.id DESC
    """, (session["user_id"],))

    orders = cur.fetchall()
    cur.close()

    return render_template("salesman_orders.html", orders=orders)


import random
import string

def generate_order_no():
    return "ORD-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


@admin_bp.route("/salesman/orders/create", methods=["GET", "POST"])
def salesman_create_order():
    if "user_id" not in session or session.get("user_role") != "sales":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    if request.method == "POST":
        dealer_id = request.form.get("dealer_id")
        product_part_no = request.form.get("product_part_no", "").strip()
        product_name = request.form.get("product_name", "").strip()
        qty = int(request.form.get("qty", 1) or 1)
        rate = float(request.form.get("rate", 0) or 0)
        amount = float(request.form.get("amount", 0) or 0)
        remarks = request.form.get("remarks", "").strip()

        if not dealer_id:
            cur.close()
            flash("Dealer is required.", "danger")
            return redirect(url_for("admin.salesman_create_order"))

        if not product_part_no:
            cur.close()
            flash("Part number is required.", "danger")
            return redirect(url_for("admin.salesman_create_order"))

        if not product_name:
            cur.close()
            flash("Part name is required.", "danger")
            return redirect(url_for("admin.salesman_create_order"))

        order_no = generate_order_no()

        cur.execute("""
            INSERT INTO dealer_orders
            (dealer_id, salesman_id, order_no, part_no, part_name, order_status, total_amount, remarks)
            VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s)
        """, (
            dealer_id,
            session["user_id"],
            order_no,
            product_part_no,
            product_name,
            amount,
            remarks
        ))
        order_id = cur.lastrowid

        cur.execute("""
            INSERT INTO dealer_order_items
            (order_id, product_part_no, product_name, qty, rate, amount)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            order_id,
            product_part_no,
            product_name,
            qty,
            rate,
            amount
        ))

        mysql.connection.commit()
        cur.close()

        flash("Order created successfully.", "success")
        return redirect(url_for("admin.salesman_orders"))

    cur.execute("""
        SELECT id, name
        FROM distributors
        WHERE salesman_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY name ASC
    """, (session["user_id"],))
    dealers = cur.fetchall()
    cur.close()

    return render_template("salesman_create_order.html", dealers=dealers)






def column_exists(cursor, table_name, column_name):
    cursor.execute("""
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
    """, (table_name, column_name))
    return cursor.fetchone()[0] > 0


def first_existing_column(cursor, table_name, candidates):
    for col in candidates:
        if column_exists(cursor, table_name, col):
            return col
    return None






@admin_bp.route("/redeem-coupon/<int:coupon_id>", methods=["POST"])
def redeem_coupon(coupon_id):
    if "user_id" not in session:
        flash("Login first", "danger")
        return redirect(url_for("auth.login"))

    manual_reason = request.form.get("manual_reason", "").strip()

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        company_id = session.get("company_id")

        # Coupon details lo
        cur.execute("""
            SELECT id, code, points
            FROM coupons
            WHERE id = %s AND company_id = %s
        """, (coupon_id, company_id))
        coupon = cur.fetchone()

        if not coupon:
            flash("Invalid coupon", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        # Coupon redeem mark karo
        cur.execute("""
            UPDATE coupons
            SET is_redeemed = 1
            WHERE id = %s
        """, (coupon_id,))

        # 🔥 IMPORTANT: dealer_redemptions me entry insert karo
        cur.execute("""
            INSERT INTO dealer_redemptions
            (dealer_id, redemption_type, part_no, product_name, coupons_count, redeemed_points, remarks, redeemed_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            session.get("user_id"),      # dealer_id (ya jis user ne redeem kiya)
            "manual",
            None,
            None,
            1,
            coupon[2] if coupon[2] else 0,
            manual_reason,
            session.get("user_id")
        ))

        mysql.connection.commit()
        flash("Redeemed successfully", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash(str(e), "danger")

    finally:
        cur.close()

    return redirect(url_for("admin.pending_redemptions"))
@admin_bp.route("/employee/pending-redemptions")
def pending_redemptions():
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    if session.get("user_role") not in ["employee", "admin"]:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()
    company_id = session.get("company_id")

    try:
        cur.execute("""
            SELECT
                c.id,
                c.code,
                c.product_name,
                c.part_no,
                c.points,
                c.scanned_at,
                d.name AS dealer_name
            FROM coupons c
            LEFT JOIN distributors d ON c.scanned_by = d.id
            WHERE c.company_id = %s
              AND (c.is_deleted = 0 OR c.is_deleted IS NULL)
              AND c.scanned_at IS NOT NULL
              AND (c.is_redeemed = 0 OR c.is_redeemed IS NULL)
              AND (
                    c.status IS NULL
                    OR c.status = ''
                    OR c.status = 'scanned'
                    OR c.status = 'pending'
                  )
            ORDER BY c.id DESC
        """, (company_id,))
        coupons = cur.fetchall()

    except Exception as e:
        coupons = []
        flash(f"Pending redemptions error: {str(e)}", "danger")

    finally:
        cur.close()

    return render_template("pending_redemptions.html", coupons=coupons)

@admin_bp.route("/redeem-by-invoice", methods=["POST"])
def redeem_by_invoice():

    if "user_id" not in session:
        flash("Login first", "danger")
        return redirect(url_for("auth.login"))

    invoice_no = request.form.get("invoice_no")
    dealer_id = request.form.get("dealer_id")

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        # total coupons count
        cur.execute("""
            SELECT COUNT(*), SUM(points)
            FROM coupons
            WHERE invoice_no = %s AND is_redeemed = 0
        """, (invoice_no,))
        data = cur.fetchone()

        if not data or data[0] == 0:
            flash("No coupons found for invoice", "warning")
            return redirect(url_for("admin.pending_redemptions"))

        count = data[0]
        total_points = data[1] if data[1] else 0

        # coupons mark redeemed
        cur.execute("""
            UPDATE coupons
            SET is_redeemed = 1
            WHERE invoice_no = %s
        """, (invoice_no,))

        # entry in redemption table
        cur.execute("""
            INSERT INTO dealer_redemptions
            (dealer_id, invoice_no, redemption_type, coupons_count, redeemed_points, redeemed_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (
            dealer_id,
            invoice_no,
            "invoice",
            count,
            total_points,
            session["user_id"]
        ))

        mysql.connection.commit()
        flash("Invoice redeemed successfully", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash(str(e), "danger")

    finally:
        cur.close()

    return redirect(url_for("admin.pending_redemptions"))

@admin_bp.route("/employee/dealer-wallets")
def dealer_wallets():
    if "user_id" not in session or session.get("user_role") != "employee":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT
            d.id,
            d.name,
            d.mobile,
            COALESCE(SUM(CASE
                WHEN c.status IN ('scanned', 'redeemed') THEN c.points
                ELSE 0
            END), 0) AS total_points,
            MAX(c.scanned_at) AS updated_at
        FROM distributors d
        LEFT JOIN coupons c ON c.scanned_by = d.id
        WHERE d.company_id = %s
          AND (d.is_deleted = 0 OR d.is_deleted IS NULL)
        GROUP BY d.id, d.name, d.mobile
        ORDER BY d.id DESC
    """, (session.get("company_id"),))

    wallets = cur.fetchall()
    cur.close()

    return render_template("dealer_wallets.html", wallets=wallets)

@admin_bp.route("/employee/wallet-transactions")
def wallet_transactions():
    if "user_id" not in session or session.get("user_role") != "employee":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT *
        FROM (
            SELECT
                wt.id AS sort_id,
                d.name AS dealer_name,
                wt.coupon_id,
                wt.points,
                wt.transaction_type,
                wt.remarks,
                wt.created_at
            FROM wallet_transactions wt
            JOIN distributors d ON wt.dealer_id = d.id
            WHERE d.company_id = %s

            UNION ALL

            SELECT
                c.id AS sort_id,
                d.name AS dealer_name,
                c.id AS coupon_id,
                c.points,
                'scan' AS transaction_type,
                CONCAT('Coupon scanned: ', c.code) AS remarks,
                c.scanned_at AS created_at
            FROM coupons c
            JOIN distributors d ON c.scanned_by = d.id
            WHERE c.company_id = %s
              AND c.scanned_at IS NOT NULL
        ) x
        ORDER BY created_at DESC
    """, (company_id, company_id))

    transactions = cur.fetchall()
    cur.close()

    return render_template("wallet_transactions.html", transactions=transactions)

@admin_bp.route("/scan/<code>")
def scan_coupon(code):

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    # find coupon
    cur.execute("""
        SELECT id, points, status
        FROM coupons
        WHERE code = %s
        LIMIT 1
    """, (code,))
    coupon = cur.fetchone()

    if not coupon:
        cur.close()
        return render_template("scan_result.html", status="invalid")

    coupon_id, points, status = coupon

    # already used
    if status == "redeemed":
        cur.close()
        return render_template("scan_result.html", status="already")

    # mark scanned
    cur.execute("""
        UPDATE coupons
        SET status = 'redeemed',
            scanned_at = NOW()
        WHERE id = %s
    """, (coupon_id,))

    mysql.connection.commit()
    cur.close()

    return render_template("scan_result.html", status="success", points=points)

from flask import jsonify

@admin_bp.route("/api/scan/<code>")
def api_scan_coupon(code):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT id, points, status
        FROM coupons
        WHERE code = %s
        LIMIT 1
    """, (code,))
    coupon = cur.fetchone()

    if not coupon:
        cur.close()
        return jsonify({
            "success": False,
            "status": "invalid",
            "message": "Coupon not found"
        }), 404

    coupon_id, points, status = coupon

    if status == "redeemed":
        cur.close()
        return jsonify({
            "success": False,
            "status": "already",
            "message": "Coupon already redeemed",
            "points": points
        }), 200

    cur.execute("""
        UPDATE coupons
        SET status = 'redeemed',
            scanned_at = NOW()
        WHERE id = %s
    """, (coupon_id,))
    mysql.connection.commit()
    cur.close()

    return jsonify({
        "success": True,
        "status": "success",
        "message": "Coupon applied successfully",
        "points": points
    }), 200


@admin_bp.route("/salesman/products/search")
def salesman_product_search():
    if "user_id" not in session or session.get("user_role") != "sales":
        return {"items": []}

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    q = request.args.get("q", "").strip()

    cur = mysql.connection.cursor()

    if not q:
        cur.execute("""
            SELECT
                part_no,
                product_name,
                product_type,
                pack_size,
                mrp,
                dlp,
                points
            FROM coupons
            WHERE company_id = %s
              AND is_deleted = 0
              AND part_no IS NOT NULL
              AND product_name IS NOT NULL
            GROUP BY part_no, product_name, product_type, pack_size, mrp, dlp, points
            ORDER BY MAX(id) DESC
            LIMIT 20
        """, (company_id,))
    else:
        cur.execute("""
            SELECT
                part_no,
                product_name,
                product_type,
                pack_size,
                mrp,
                dlp,
                points
            FROM coupons
            WHERE company_id = %s
              AND is_deleted = 0
              AND (
                    part_no LIKE %s
                    OR product_name LIKE %s
                  )
            GROUP BY part_no, product_name, product_type, pack_size, mrp, dlp, points
            ORDER BY MAX(id) DESC
            LIMIT 20
        """, (company_id, f"%{q}%", f"%{q}%"))

    rows = cur.fetchall()
    cur.close()

    items = []
    for r in rows:
        items.append({
            "part_no": r[0] or "",
            "product_name": r[1] or "",
            "product_type": r[2] or "",
            "pack_size": r[3] or "",
            "mrp": float(r[4] or 0),
            "dlp": float(r[5] or 0),
            "points": int(r[6] or 0)
        })

    return {"items": items}




@admin_bp.route("/employee/orders")
def general_employee_orders():
    if "user_id" not in session or session.get("user_role") not in ["employee", "admin"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT
            o.id,
            o.order_no,
            d.name AS dealer_name,
            u.name AS salesman_name,
            o.part_no,
            o.part_name,
            o.order_status,
            o.total_amount,
            o.created_at
        FROM dealer_orders o
        JOIN distributors d ON o.dealer_id = d.id
        JOIN users u ON o.salesman_id = u.id
        WHERE d.company_id = %s
        ORDER BY o.id DESC
    """, (company_id,))

    orders = cur.fetchall()
    cur.close()

    return render_template("general_employee_orders.html", orders=orders)

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
        data = request.get_json()
        dealer_id = data.get("dealer_id")

        if not dealer_id:
            return jsonify({
                "success": False,
                "message": "Dealer ID is required"
            }), 400

        mysql = current_app.config["MYSQL_INSTANCE"]
        cur = mysql.connection.cursor()

        cur.execute("""
            UPDATE distributors
            SET active_token = NULL
            WHERE id = %s
        """, (dealer_id,))
        mysql.connection.commit()
        cur.close()

        return jsonify({
            "success": True,
            "message": "Logged out successfully"
        }), 200

    except Exception as e:
        current_app.logger.exception("Dealer logout API error")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500
    
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
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()

    query = """
        SELECT
            code,
            part_no,
            product_name,
            points,
            scanned_at,
            status
        FROM coupons
        WHERE dealer_id = %s
          AND status IN ('scanned', 'redeemed')
    """
    params = [dealer_id]

    if from_date:
        query += " AND DATE(scanned_at) >= %s"
        params.append(from_date)

    if to_date:
        query += " AND DATE(scanned_at) <= %s"
        params.append(to_date)

    query += " ORDER BY scanned_at DESC, id DESC"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    cur.close()

    history = []
    for r in rows:
        history.append({
            "code": r[0],
            "part_no": r[1],
            "product_name": r[2],
            "points": int(r[3] or 0),
            "scanned_at": str(r[4] or ""),
            "status": r[5]
        })

    return jsonify({
        "success": True,
        "history": history
    })

from flask import jsonify, current_app

@admin_bp.route("/api/dealer/sets/<dealer_id>", methods=["GET"])
def dealer_sets_api(dealer_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT
            part_no,
            set_size,
            total_scans,
            completed_sets,
            remaining_scans,
            total_points
        FROM dealer_coupon_sets
        WHERE dealer_id = %s
        ORDER BY id ASC
    """, (dealer_id,))

    rows = cur.fetchall()
    cur.close()

    sets = []
    for r in rows:
        part_no = r[0] or "-"
        set_size = int(r[1] or 10)
        total_scans = int(r[2] or 0)
        completed_sets = int(r[3] or 0)
        total_points = int(r[5] or 0)

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

    dealer_id = request.form.get("dealer_id")
    part_no = request.form.get("part_no")
    remarks = request.form.get("remarks", "").strip()

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    # take first 10 scanned coupons of same part
    cur.execute("""
        SELECT id, product_name, points
        FROM coupons
        WHERE dealer_id = %s
          AND part_no = %s
          AND status = 'scanned'
        ORDER BY scanned_at ASC, id ASC
        LIMIT 10
    """, (dealer_id, part_no))
    coupons = cur.fetchall()

    if len(coupons) < 10:
        cur.close()
        flash("At least 10 scanned coupons are required for settlement.", "danger")
        return redirect(url_for("admin.pending_redemptions"))

    coupon_ids = [str(c[0]) for c in coupons]
    product_name = coupons[0][1]
    total_points = sum(int(c[2] or 0) for c in coupons)

    # redeem these 10
    cur.execute(f"""
        UPDATE coupons
        SET status = 'redeemed',
            redeemed_by = %s,
            redeemed_at = NOW()
        WHERE id IN ({",".join(coupon_ids)})
    """, (session["user_id"],))

    # wallet update
    cur.execute("""
        SELECT id
        FROM dealer_wallets
        WHERE dealer_id = %s
        LIMIT 1
    """, (dealer_id,))
    wallet = cur.fetchone()

    if wallet:
        cur.execute("""
            UPDATE dealer_wallets
            SET total_points = total_points + %s
            WHERE dealer_id = %s
        """, (total_points, dealer_id))
    else:
        cur.execute("""
            INSERT INTO dealer_wallets (dealer_id, total_points)
            VALUES (%s, %s)
        """, (dealer_id, total_points))

    # transaction entry
    cur.execute("""
        INSERT INTO wallet_transactions
        (dealer_id, coupon_id, points, transaction_type, remarks, created_by)
        VALUES (%s, NULL, %s, 'credit', %s, %s)
    """, (dealer_id, total_points, f"Settlement for part {part_no}", session["user_id"]))

    # settlement history
    cur.execute("""
        INSERT INTO dealer_settlements
        (dealer_id, part_no, product_name, settled_sets, coupons_count, total_points, settlement_type, remarks, settled_by)
        VALUES (%s, %s, %s, 1, 10, %s, 'manual', %s, %s)
    """, (dealer_id, part_no, product_name, total_points, remarks, session["user_id"]))

    # refresh summary table
    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(points), 0)
        FROM coupons
        WHERE dealer_id = %s
          AND part_no = %s
          AND status = 'scanned'
    """, (dealer_id, part_no))
    scanned_count, scanned_points = cur.fetchone()

    completed_sets = scanned_count // 10
    remaining_scans = scanned_count % 10

    cur.execute("""
        UPDATE dealer_coupon_sets
        SET total_scans = %s,
            completed_sets = %s,
            remaining_scans = %s,
            total_points = %s
        WHERE dealer_id = %s AND part_no = %s
    """, (
        scanned_count,
        completed_sets,
        remaining_scans,
        scanned_points,
        dealer_id,
        part_no
    ))

    mysql.connection.commit()
    cur.close()

    flash("Manual settlement completed successfully.", "success")
    return redirect(url_for("admin.pending_redemptions"))










from flask import jsonify, current_app

@admin_bp.route("/api/dealer/wallet/<dealer_id>", methods=["GET"])
def dealer_wallet_api(dealer_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    # total points
    cur.execute("""
        SELECT COALESCE(SUM(points), 0)
        FROM coupons
        WHERE dealer_id = %s
          AND status IN ('scanned', 'redeemed')
    """, (dealer_id,))
    total_row = cur.fetchone()
    total_points = int(total_row[0] or 0) if total_row else 0

    # part-wise points
    cur.execute("""
        SELECT
            part_no,
            COALESCE(SUM(points), 0) AS total_points
        FROM coupons
        WHERE dealer_id = %s
          AND status IN ('scanned', 'redeemed')
          AND part_no IS NOT NULL
          AND part_no <> ''
        GROUP BY part_no
        HAVING SUM(points) > 0
        ORDER BY part_no ASC
    """, (dealer_id,))
    rows = cur.fetchall()
    cur.close()

    part_points = []
    for r in rows:
        part_points.append({
            "part_no": r[0],
            "points": int(r[1] or 0)
        })

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

    dealer_id = request.form.get("dealer_id")
    invoice_no = request.form.get("invoice_no", "").strip()
    redemption_type = request.form.get("redemption_type", "manual").strip()
    part_no = request.form.get("part_no", "").strip()
    product_name = request.form.get("product_name", "").strip()
    sets_count = int(request.form.get("sets_count", 0) or 0)
    manual_points = int(request.form.get("manual_points", 0) or 0)
    remarks = request.form.get("remarks", "").strip()

    if not dealer_id or not invoice_no:
        flash("Dealer and invoice number are required.", "danger")
        return redirect(url_for("admin.redemptions_page"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT earned_points, redeemed_points, available_points
        FROM dealer_wallets
        WHERE dealer_id = %s
        LIMIT 1
    """, (dealer_id,))
    wallet = cur.fetchone()

    if not wallet:
        cur.close()
        flash("Wallet not found for dealer.", "danger")
        return redirect(url_for("admin.redemptions_page"))

    earned_points = int(wallet[0] or 0)
    redeemed_points = int(wallet[1] or 0)
    available_points = int(wallet[2] or 0)

    redeem_points_value = 0
    coupons_count = 0

    if redemption_type == "set":
        if not part_no or sets_count <= 0:
            cur.close()
            flash("Part no and set count are required for set redemption.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        cur.execute("""
            SELECT total_points, completed_sets, product_name
            FROM dealer_coupon_sets
            WHERE dealer_id = %s AND part_no = %s
            LIMIT 1
        """, (dealer_id, part_no))
        set_row = cur.fetchone()

        if not set_row:
            cur.close()
            flash("No set summary found for this part.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        total_points_for_part = int(set_row[0] or 0)
        completed_sets = int(set_row[1] or 0)
        if not product_name:
            product_name = set_row[2] or ""

        if completed_sets < sets_count:
            cur.close()
            flash("Requested set count is higher than available completed sets.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        # points from first 10 * set_count scanned coupons of same part
        cur.execute("""
            SELECT COALESCE(SUM(points), 0)
            FROM (
                SELECT points
                FROM coupons
                WHERE dealer_id = %s
                  AND part_no = %s
                  AND status = 'scanned'
                ORDER BY scanned_at ASC, id ASC
                LIMIT %s
            ) t
        """, (dealer_id, part_no, sets_count * 10))
        redeem_points_value = int(cur.fetchone()[0] or 0)
        coupons_count = sets_count * 10

        if redeem_points_value <= 0:
            cur.close()
            flash("No redeemable scanned coupons found for this part.", "danger")
            return redirect(url_for("admin.redemptions_page"))

        # mark those coupons redeemed
        cur.execute("""
            SELECT id
            FROM coupons
            WHERE dealer_id = %s
              AND part_no = %s
              AND status = 'scanned'
            ORDER BY scanned_at ASC, id ASC
            LIMIT %s
        """, (dealer_id, part_no, coupons_count))
        coupon_ids = [str(r[0]) for r in cur.fetchall()]

        if coupon_ids:
            cur.execute(f"""
                UPDATE coupons
                SET status = 'redeemed',
                    redeemed_by = %s,
                    redeemed_at = NOW()
                WHERE id IN ({",".join(coupon_ids)})
            """, (session["user_id"],))

        # refresh set summary
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(points), 0)
            FROM coupons
            WHERE dealer_id = %s
              AND part_no = %s
              AND status = 'scanned'
        """, (dealer_id, part_no))
        scanned_count, scanned_points = cur.fetchone()

        new_completed_sets = scanned_count // 10
        remaining_scans = scanned_count % 10

        cur.execute("""
            UPDATE dealer_coupon_sets
            SET total_scans = %s,
                completed_sets = %s,
                remaining_scans = %s,
                total_points = %s
            WHERE dealer_id = %s AND part_no = %s
        """, (
            scanned_count,
            new_completed_sets,
            remaining_scans,
            scanned_points,
            dealer_id,
            part_no
        ))

    else:
        redeem_points_value = manual_points
        coupons_count = 0

        if redeem_points_value <= 0:
            cur.close()
            flash("Manual points must be greater than zero.", "danger")
            return redirect(url_for("admin.redemptions_page"))

    if available_points < redeem_points_value:
        cur.close()
        flash("Not enough available points.", "danger")
        return redirect(url_for("admin.redemptions_page"))

    new_redeemed_points = redeemed_points + redeem_points_value
    new_available_points = earned_points - new_redeemed_points

    cur.execute("""
        UPDATE dealer_wallets
        SET redeemed_points = %s,
            available_points = %s
        WHERE dealer_id = %s
    """, (new_redeemed_points, new_available_points, dealer_id))

    cur.execute("""
        INSERT INTO dealer_redemptions
        (dealer_id, invoice_no, redemption_type, part_no, product_name, sets_count, coupons_count, redeemed_points, remarks, redeemed_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        dealer_id,
        invoice_no,
        redemption_type,
        part_no if part_no else None,
        product_name if product_name else None,
        sets_count,
        coupons_count,
        redeem_points_value,
        remarks,
        session["user_id"]
    ))

    cur.execute("""
        INSERT INTO wallet_transactions
        (dealer_id, coupon_id, points, transaction_type, remarks, created_by)
        VALUES (%s, NULL, %s, 'redeem_invoice', %s, %s)
    """, (
        dealer_id,
        redeem_points_value,
        f"Invoice {invoice_no}",
        session["user_id"]
    ))

    mysql.connection.commit()
    cur.close()

    flash("Points redeemed successfully.", "success")
    return redirect(url_for("admin.redemptions_page"))

@admin_bp.route("/employee/redemption-history")
def redemption_history():
    if "user_id" not in session or session.get("user_role") not in ["employee", "admin"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT
            r.id,
            d.name,
            r.invoice_no,
            r.redemption_type,
            r.part_no,
            r.product_name,
            r.sets_count,
            r.coupons_count,
            r.redeemed_points,
            r.remarks,
            r.created_at
        FROM dealer_redemptions r
        JOIN distributors d ON r.dealer_id = d.id
        WHERE d.company_id = %s
        ORDER BY r.id DESC
    """, (company_id,))
    rows = cur.fetchall()
    cur.close()

    return render_template("redemption_history.html", redemptions=rows)

@admin_bp.route("/api/dealer/redemption-history/<dealer_id>", methods=["GET"])
def dealer_redemption_history_api(dealer_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT
            r.invoice_no,
            r.redemption_type,
            r.part_no,
            r.product_name,
            r.sets_count,
            r.coupons_count,
            r.redeemed_points,
            r.remarks,
            r.created_at,
            COALESCE(u.name, '-') AS redeemed_by
        FROM dealer_redemptions r
        LEFT JOIN users u ON r.redeemed_by = u.id
        WHERE r.dealer_id = %s
        ORDER BY r.id DESC
        LIMIT 100
    """, (dealer_id,))
    rows = cur.fetchall()
    cur.close()

    history = []
    for r in rows:
        history.append({
            "invoice_no": r[0] or "",
            "type": r[1] or "",
            "part_no": r[2] or "-",
            "product_name": r[3] or "-",
            "sets": int(r[4] or 0),
            "coupons": int(r[5] or 0),
            "points": int(r[6] or 0),
            "remarks": r[7] or "",
            "redeemed_at": str(r[8] or ""),
            "redeemed_by": r[9] or "-"
        })

    return jsonify({
        "success": True,
        "history": history
    })



from flask import jsonify

@admin_bp.route("/api/dealer/banners/<dealer_id>", methods=["GET"])
def dealer_banners_api(dealer_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    # Get dealer's company
    cur.execute("""
        SELECT company_id
        FROM distributors
        WHERE id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        LIMIT 1
    """, (dealer_id,))
    dealer = cur.fetchone()

    if not dealer:
        cur.close()
        return jsonify({
            "success": False,
            "message": "Dealer not found",
            "banners": []
        }), 404

    company_id = dealer[0]

    # Get only the latest active banner
    cur.execute("""
        SELECT id, title, image
        FROM banners
        WHERE company_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
          AND (is_active = 1 OR is_active IS NULL)
        ORDER BY id DESC
        LIMIT 1
    """, (company_id,))
    row = cur.fetchone()
    cur.close()

    if not row:
        return jsonify({
            "success": True,
            "message": "No banner found",
            "banners": []
        }), 200

    banner = {
        "id": row[0],
        "title": row[1] or "",
        "image_url": f"http://192.168.1.17:5000/static/uploads/{row[2]}" if row[2] else ""
    }

    return jsonify({
        "success": True,
        "banners": [banner]
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

        ext = image.filename.rsplit(".", 1)[-1].lower()

        filename = f"dealer_{dealer_id}_{int(time.time())}.{ext}"

        folder = os.path.join(current_app.root_path, "static/uploads/profiles")
        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, filename)
        image.save(path)

        db_path = f"profiles/{filename}"

        mysql = current_app.config["MYSQL_INSTANCE"]
        cur = mysql.connection.cursor()

        cur.execute("""
            UPDATE distributors
            SET profile_image=%s
            WHERE id=%s
        """, (db_path, dealer_id))

        mysql.connection.commit()
        cur.close()

        image_url = request.host_url.rstrip("/") + "/static/uploads/" + db_path

        return jsonify({
            "success": True,
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


@admin_bp.route("/company-admin/retailers", methods=["GET"])
def company_admin_retailers_CRUD_page():
    if not _check_company_admin():
        return redirect(url_for("auth.login"))

    company_id = session.get("company_id")
    retailers = _fetch_entities("retailers", company_id)

    return render_template(
        "company_admin_retailers.html",
        retailers=retailers,
        edit_item=None
    )


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

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    label = _get_entity_label(entity_type)

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
        return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

    cur = mysql.connection.cursor()

    try:
        cur.execute(f"""
            SELECT id
            FROM {entity_type}
            WHERE company_id = %s
              AND dealer_code = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
            LIMIT 1
        """, (company_id, dealer_code))
        existing_code = cur.fetchone()

        if existing_code:
            cur.close()
            flash(f"{label} code already exists.", "danger")
            return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

        if email:
            cur.execute(f"""
                SELECT id
                FROM {entity_type}
                WHERE company_id = %s
                  AND email = %s
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                LIMIT 1
            """, (company_id, email))
            existing_email = cur.fetchone()

            if existing_email:
                cur.close()
                flash(f"{label} email already exists.", "danger")
                return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

        cur.execute(f"""
            INSERT INTO {entity_type}
            (
                dealer_code,
                name,
                mobile,
                email,
                pan,
                gst,
                city,
                state,
                address,
                company_id,
                is_deleted
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
        """, (
            dealer_code,
            name,
            mobile,
            email,
            pan,
            gst,
            city,
            state,
            address,
            company_id
        ))

        mysql.connection.commit()
        cur.close()

        flash(f"{label} added successfully.", "success")
    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        flash(f"Error adding {label.lower()}: {str(e)}", "danger")

    return redirect(url_for(f"admin.company_admin_{entity_type}_page"))


@admin_bp.route("/company-admin/<entity_type>/edit/<record_id>", methods=["GET", "POST"])
def edit_entity(entity_type, record_id):
    if not _check_company_admin():
        return redirect(url_for("auth.login"))

    if entity_type not in ["distributors", "retailers", "mechanics"]:
        flash("Invalid entity type.", "danger")
        return redirect(url_for("admin.company_admin_dashboard"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    label = _get_entity_label(entity_type)
    template_name = _get_entity_template(entity_type)

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

        cur = mysql.connection.cursor()

        try:
            cur.execute(f"""
                SELECT id
                FROM {entity_type}
                WHERE company_id = %s
                  AND dealer_code = %s
                  AND id != %s
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                LIMIT 1
            """, (company_id, dealer_code, record_id))
            existing_code = cur.fetchone()

            if existing_code:
                cur.close()
                flash(f"{label} code already exists.", "danger")
                return redirect(url_for("admin.edit_entity", entity_type=entity_type, record_id=record_id))

            if email:
                cur.execute(f"""
                    SELECT id
                    FROM {entity_type}
                    WHERE company_id = %s
                      AND email = %s
                      AND id != %s
                      AND (is_deleted = 0 OR is_deleted IS NULL)
                    LIMIT 1
                """, (company_id, email, record_id))
                existing_email = cur.fetchone()

                if existing_email:
                    cur.close()
                    flash(f"{label} email already exists.", "danger")
                    return redirect(url_for("admin.edit_entity", entity_type=entity_type, record_id=record_id))

            cur.execute(f"""
                UPDATE {entity_type}
                SET
                    dealer_code = %s,
                    name = %s,
                    mobile = %s,
                    email = %s,
                    pan = %s,
                    gst = %s,
                    city = %s,
                    state = %s,
                    address = %s
                WHERE id = %s
                  AND company_id = %s
                  AND (is_deleted = 0 OR is_deleted IS NULL)
            """, (
                dealer_code,
                name,
                mobile,
                email,
                pan,
                gst,
                city,
                state,
                address,
                record_id,
                company_id
            ))

            mysql.connection.commit()
            cur.close()

            flash(f"{label} updated successfully.", "success")
            return redirect(url_for(f"admin.company_admin_{entity_type}_page"))

        except Exception as e:
            mysql.connection.rollback()
            cur.close()
            flash(f"Error updating {label.lower()}: {str(e)}", "danger")
            return redirect(url_for("admin.edit_entity", entity_type=entity_type, record_id=record_id))

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

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    label = _get_entity_label(entity_type)

    cur = mysql.connection.cursor()
    try:
        cur.execute(f"""
            UPDATE {entity_type}
            SET is_deleted = 1
            WHERE id = %s
              AND company_id = %s
        """, (record_id, company_id))

        mysql.connection.commit()
        cur.close()

        flash(f"{label} deleted successfully.", "success")
    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        flash(f"Error deleting {label.lower()}: {str(e)}", "danger")

    return redirect(url_for(f"admin.company_admin_{entity_type}_page"))


@admin_bp.route("/company-admin/distributors/edit/<distributor_id>", methods=["GET", "POST"])
def edit_distributor(distributor_id):
    if "user_id" not in session or session.get("user_role") not in ["admin", "sales"]:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    cur = mysql.connection.cursor()

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
            cur.close()
            flash("Dealer code and name are required.", "danger")
            return redirect(url_for("admin.edit_distributor", distributor_id=distributor_id))

        try:
            cur.execute("""
                SELECT id
                FROM distributors
                WHERE dealer_code = %s
                  AND company_id = %s
                  AND id != %s
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                LIMIT 1
            """, (dealer_code, company_id, distributor_id))
            existing_code = cur.fetchone()

            if existing_code:
                cur.close()
                flash("Dealer code already exists.", "danger")
                return redirect(url_for("admin.edit_distributor", distributor_id=distributor_id))

            if email:
                cur.execute("""
                    SELECT id
                    FROM distributors
                    WHERE email = %s
                      AND company_id = %s
                      AND id != %s
                      AND (is_deleted = 0 OR is_deleted IS NULL)
                    LIMIT 1
                """, (email, company_id, distributor_id))
                existing_email = cur.fetchone()

                if existing_email:
                    cur.close()
                    flash("Email already exists.", "danger")
                    return redirect(url_for("admin.edit_distributor", distributor_id=distributor_id))

            if user_role == "sales":
                cur.execute("""
                    UPDATE distributors
                    SET dealer_code=%s, name=%s, mobile=%s, email=%s, pan=%s, gst=%s,
                        city=%s, state=%s, address=%s
                    WHERE id=%s AND company_id=%s AND salesman_id=%s
                """, (
                    dealer_code, name, mobile, email, pan, gst,
                    city, state, address,
                    distributor_id, company_id, user_id
                ))
            else:
                cur.execute("""
                    UPDATE distributors
                    SET dealer_code=%s, name=%s, mobile=%s, email=%s, pan=%s, gst=%s,
                        city=%s, state=%s, address=%s
                    WHERE id=%s AND company_id=%s
                """, (
                    dealer_code, name, mobile, email, pan, gst,
                    city, state, address,
                    distributor_id, company_id
                ))

            mysql.connection.commit()
            cur.close()
            flash("Distributor updated successfully.", "success")
            return redirect(url_for("admin.company_admin_distributors_page"))

        except Exception as e:
            mysql.connection.rollback()
            cur.close()
            flash(f"Error updating distributor: {str(e)}", "danger")
            return redirect(url_for("admin.edit_distributor", distributor_id=distributor_id))

    if user_role == "sales":
        cur.execute("""
            SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
            FROM distributors
            WHERE id = %s
              AND company_id = %s
              AND salesman_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
            LIMIT 1
        """, (distributor_id, company_id, user_id))
    else:
        cur.execute("""
            SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
            FROM distributors
            WHERE id = %s
              AND company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
            LIMIT 1
        """, (distributor_id, company_id))

    row = cur.fetchone()
    if not row:
        cur.close()
        flash("Distributor not found.", "danger")
        return redirect(url_for("admin.company_admin_distributors_page"))

    distributor = {
        "id": row[0],
        "dealer_code": row[1] or "",
        "name": row[2] or "",
        "mobile": row[3] or "",
        "email": row[4] or "",
        "pan": row[5] or "",
        "gst": row[6] or "",
        "city": row[7] or "",
        "state": row[8] or "",
        "address": row[9] or "",
    }

    if user_role == "sales":
        cur.execute("""
            SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
            FROM distributors
            WHERE company_id = %s
              AND salesman_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
            ORDER BY id DESC
        """, (company_id, user_id))
    else:
        cur.execute("""
            SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
            FROM distributors
            WHERE company_id = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
            ORDER BY id DESC
        """, (company_id,))

    rows = cur.fetchall()
    cur.close()

    distributors = []
    for r in rows:
        distributors.append({
            "id": r[0],
            "dealer_code": r[1],
            "name": r[2],
            "mobile": r[3],
            "email": r[4],
            "pan": r[5],
            "gst": r[6],
            "city": r[7],
            "state": r[8],
            "address": r[9]
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

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

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
            cur.execute("""
                UPDATE retailers
                SET dealer_code=%s, name=%s, mobile=%s, email=%s, pan=%s, gst=%s,
                    city=%s, state=%s, address=%s
                WHERE id=%s AND company_id=%s
            """, (
                dealer_code, name, mobile, email, pan, gst,
                city, state, address,
                retailer_id, company_id
            ))
            mysql.connection.commit()
            cur.close()
            flash("Retailer updated successfully.", "success")
            return redirect(url_for("admin.company_admin_retailers_page"))
        except Exception as e:
            mysql.connection.rollback()
            cur.close()
            flash(f"Error updating retailer: {str(e)}", "danger")
            return redirect(url_for("admin.edit_retailer", retailer_id=retailer_id))

    cur.execute("""
        SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
        FROM retailers
        WHERE id = %s
          AND company_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        LIMIT 1
    """, (retailer_id, company_id))
    row = cur.fetchone()

    if not row:
        cur.close()
        flash("Retailer not found.", "danger")
        return redirect(url_for("admin.company_admin_retailers_page"))

    retailer = {
        "id": row[0],
        "dealer_code": row[1] or "",
        "name": row[2] or "",
        "mobile": row[3] or "",
        "email": row[4] or "",
        "pan": row[5] or "",
        "gst": row[6] or "",
        "city": row[7] or "",
        "state": row[8] or "",
        "address": row[9] or "",
    }

    cur.execute("""
        SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
        FROM retailers
        WHERE company_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY id DESC
    """, (company_id,))
    rows = cur.fetchall()
    cur.close()

    retailers = []
    for r in rows:
        retailers.append({
            "id": r[0],
            "dealer_code": r[1],
            "name": r[2],
            "mobile": r[3],
            "email": r[4],
            "pan": r[5],
            "gst": r[6],
            "city": r[7],
            "state": r[8],
            "address": r[9]
        })

    return render_template(
        "company_admin_retailers.html",
        retailers=retailers,
        edit_retailer=retailer
    )

@admin_bp.route("/company-admin/mechanics/edit/<int:mechanic_id>", methods=["GET", "POST"])
def edit_mechanic(mechanic_id):
    if "user_id" not in session or session.get("user_role") != "admin":
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    company_id = session.get("company_id")
    cur = mysql.connection.cursor()

    # ================= POST (UPDATE)
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
            cur.execute("""
                UPDATE mechanics
                SET dealer_code=%s, name=%s, mobile=%s, email=%s,
                    pan=%s, gst=%s, city=%s, state=%s, address=%s
                WHERE id=%s AND company_id=%s
            """, (
                dealer_code, name, mobile, email,
                pan, gst, city, state, address,
                mechanic_id, company_id
            ))

            mysql.connection.commit()
            cur.close()

            flash("Mechanic updated successfully.", "success")
            return redirect(url_for("admin.company_admin_mechanics_page"))

        except Exception as e:
            mysql.connection.rollback()
            cur.close()
            flash(f"Error updating mechanic: {str(e)}", "danger")
            return redirect(url_for("admin.edit_mechanic", mechanic_id=mechanic_id))

    # ================= GET (LOAD DATA)
    cur.execute("""
        SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
        FROM mechanics
        WHERE id = %s
          AND company_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        LIMIT 1
    """, (mechanic_id, company_id))

    row = cur.fetchone()

    if not row:
        cur.close()
        flash("Mechanic not found.", "danger")
        return redirect(url_for("admin.company_admin_mechanics_page"))

    edit_mechanic = {
        "id": row[0],
        "dealer_code": row[1] or "",
        "name": row[2] or "",
        "mobile": row[3] or "",
        "email": row[4] or "",
        "pan": row[5] or "",
        "gst": row[6] or "",
        "city": row[7] or "",
        "state": row[8] or "",
        "address": row[9] or "",
    }

    # reload list
    cur.execute("""
        SELECT id, dealer_code, name, mobile, email, pan, gst, city, state, address
        FROM mechanics
        WHERE company_id = %s
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY id DESC
    """, (company_id,))

    rows = cur.fetchall()
    cur.close()

    mechanics = []
    for r in rows:
        mechanics.append({
            "id": r[0],
            "dealer_code": r[1],
            "name": r[2],
            "mobile": r[3],
            "email": r[4],
            "pan": r[5],
            "gst": r[6],
            "city": r[7],
            "state": r[8],
            "address": r[9]
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

    coupon_code = request.form.get("coupon_code", "").strip()
    reason = request.form.get("reason", "").strip()

    if not coupon_code:
        flash("Coupon code is required.", "danger")
        return redirect(url_for("admin.general_employee_dashboard"))

    if not reason:
        flash("Reason is required for manual redeem.", "danger")
        return redirect(url_for("admin.general_employee_dashboard"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        company_id = session.get("company_id")

        cur.execute("""
            SELECT id, code, points, company_id, is_redeemed
            FROM coupons
            WHERE code = %s AND company_id = %s
            LIMIT 1
        """, (coupon_code, company_id))
        coupon = cur.fetchone()

        if not coupon:
            flash("Invalid coupon code.", "danger")
            return redirect(url_for("admin.general_employee_dashboard"))

        coupon_id = coupon[0]
        coupon_code_db = coupon[1]
        points = coupon[2] if coupon[2] else 0
        coupon_company_id = coupon[3]
        is_redeemed = coupon[4]

        if is_redeemed == 1:
            flash("This coupon is already redeemed.", "warning")
            return redirect(url_for("admin.general_employee_dashboard"))

        cur.execute("""
            UPDATE coupons
            SET is_redeemed = 1
            WHERE id = %s
        """, (coupon_id,))

        cur.execute("""
            INSERT INTO dealer_redemptions
            (coupon_id, coupon_code, redeemed_by, points, manual_reason, is_manual, company_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            coupon_id,
            coupon_code_db,
            session["user_id"],
            points,
            reason,
            1,
            coupon_company_id
        ))

        mysql.connection.commit()
        flash("Coupon redeemed manually successfully.", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash(f"Error: {str(e)}", "danger")

    finally:
        cur.close()

    return redirect(url_for("admin.general_employee_dashboard"))








@admin_bp.route("/redeem-set/<int:coupon_id>", methods=["POST"])
def redeem_set(coupon_id):
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    if session.get("user_role") not in ["employee", "admin"]:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    remarks = request.form.get("set_reason", "").strip()

    if not remarks:
        flash("Set remark is required.", "danger")
        return redirect(url_for("admin.pending_redemptions"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()
    company_id = session.get("company_id")

    try:
        cur.execute("""
            SELECT id, code, product_name, part_no, points, invoice_no, dealer_id, redemption_status
            FROM coupons
            WHERE id = %s AND company_id = %s
            LIMIT 1
        """, (coupon_id, company_id))
        coupon = cur.fetchone()

        if not coupon:
            flash("Coupon not found.", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        coupon_id_db = coupon[0]
        coupon_code = coupon[1]
        product_name = coupon[2]
        part_no = coupon[3]
        points = coupon[4] or 0
        invoice_no = coupon[5]
        dealer_id = coupon[6]
        redemption_status = coupon[7]

        if not invoice_no:
            flash("Invoice number is required.", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        if redemption_status != "pending":
            flash("This coupon is already processed.", "warning")
            return redirect(url_for("admin.pending_redemptions"))

        cur.execute("""
            INSERT INTO dealer_coupon_sets
            (dealer_id, coupon_id, coupon_code, invoice_no, part_no, product_name, points, set_size, remarks, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            dealer_id,
            coupon_id_db,
            coupon_code,
            invoice_no,
            part_no,
            product_name,
            points,
            10,
            remarks,
            session["user_id"]
        ))

        cur.execute("""
            UPDATE coupons
            SET redemption_status = 'set_redeemed'
            WHERE id = %s
        """, (coupon_id_db,))

        mysql.connection.commit()
        flash("Coupon moved to set redemption successfully.", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash(f"Set redeem error: {str(e)}", "danger")

    finally:
        cur.close()

    return redirect(url_for("admin.pending_redemptions"))

from flask import jsonify, request

@admin_bp.route("/api/states", methods=["GET"])
def api_states():
    states = [
        "Andhra Pradesh",
        "Arunachal Pradesh",
        "Assam",
        "Bihar",
        "Chhattisgarh",
        "Delhi",
        "Goa",
        "Gujarat",
        "Haryana",
        "Himachal Pradesh",
        "Jharkhand",
        "Karnataka",
        "Kerala",
        "Madhya Pradesh",
        "Maharashtra",
        "Manipur",
        "Meghalaya",
        "Mizoram",
        "Nagaland",
        "Odisha",
        "Punjab",
        "Rajasthan",
        "Sikkim",
        "Tamil Nadu",
        "Telangana",
        "Tripura",
        "Uttar Pradesh",
        "Uttarakhand",
        "West Bengal"
    ]
    return jsonify({"states": states})


@admin_bp.route("/api/cities", methods=["GET"])
def api_cities():
    state = request.args.get("state", "").strip()

    state_city_map = {
        "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Guntur", "Nellore"],
        "Arunachal Pradesh": ["Itanagar", "Naharlagun", "Pasighat"],
        "Assam": ["Guwahati", "Silchar", "Dibrugarh"],
        "Bihar": ["Patna", "Gaya", "Muzaffarpur"],
        "Chhattisgarh": ["Raipur", "Bhilai", "Durg", "Bilaspur", "Korba"],
        "Delhi": ["New Delhi", "North Delhi", "South Delhi", "East Delhi", "West Delhi"],
        "Goa": ["Panaji", "Margao", "Vasco da Gama"],
        "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot"],
        "Haryana": ["Gurugram", "Faridabad", "Panipat"],
        "Himachal Pradesh": ["Shimla", "Mandi", "Solan"],
        "Jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad"],
        "Karnataka": ["Bengaluru", "Mysuru", "Mangaluru"],
        "Kerala": ["Thiruvananthapuram", "Kochi", "Kozhikode"],
        "Madhya Pradesh": ["Bhopal", "Indore", "Jabalpur", "Gwalior"],
        "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik", "Aurangabad"],
        "Manipur": ["Imphal", "Thoubal"],
        "Meghalaya": ["Shillong", "Tura"],
        "Mizoram": ["Aizawl", "Lunglei"],
        "Nagaland": ["Kohima", "Dimapur"],
        "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela"],
        "Punjab": ["Ludhiana", "Amritsar", "Jalandhar"],
        "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur", "Kota"],
        "Sikkim": ["Gangtok", "Namchi"],
        "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Salem"],
        "Telangana": ["Hyderabad", "Warangal", "Karimnagar"],
        "Tripura": ["Agartala", "Udaipur"],
        "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra", "Prayagraj"],
        "Uttarakhand": ["Dehradun", "Haridwar", "Haldwani"],
        "West Bengal": ["Kolkata", "Howrah", "Siliguri", "Asansol"]
    }

    return jsonify({"cities": state_city_map.get(state, [])})

@admin_bp.route("/redeem/material/<int:coupon_id>", methods=["POST"])
def redeem_material(coupon_id):
    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        invoice_no = request.form.get("invoice_no", "").strip()
        remarks = request.form.get("remarks", "").strip()

        if not invoice_no:
            flash("Invoice number is required.", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        # ✅ Coupon + Dealer fetch
        cur.execute("""
            SELECT 
                c.id,
                c.code,
                c.part_no,
                c.product_name,
                c.points,
                c.scanned_by,
                d.name,
                d.email
            FROM coupons c
            LEFT JOIN distributors d ON c.scanned_by = d.id
            WHERE c.id = %s
            LIMIT 1
        """, (coupon_id,))
        row = cur.fetchone()

        if not row:
            flash("Coupon not found.", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        coupon_id_db = row[0]
        coupon_code = row[1]
        part_no = row[2] or "-"
        product_name = row[3] or "-"
        points = row[4] or 0
        dealer_id = row[5]
        dealer_name = row[6] or "User"
        dealer_email = row[7]

        # ❌ Already redeemed check
        cur.execute("""
            SELECT id FROM dealer_redemptions
            WHERE coupon_id = %s
            LIMIT 1
        """, (coupon_id_db,))
        already = cur.fetchone()

        if already:
            flash("Already redeemed.", "warning")
            return redirect(url_for("admin.pending_redemptions"))

        # ✅ Insert redemption
        cur.execute("""
            INSERT INTO dealer_redemptions
            (
                dealer_id,
                coupon_id,
                coupon_code,
                invoice_no,
                redemption_type,
                part_no,
                product_name,
                coupons_count,
                redeemed_points,
                remarks,
                redeemed_by
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            dealer_id,
            coupon_id_db,
            coupon_code,
            invoice_no,
            "material",
            part_no,
            product_name,
            1,
            points,
            remarks,
            session.get("user_id")
        ))

        # ✅ Update coupon
        cur.execute("""
            UPDATE coupons
            SET is_redeemed = 1,
                status = 'redeemed'
            WHERE id = %s
        """, (coupon_id_db,))

        mysql.connection.commit()   # 🔥 IMPORTANT

        # ✅ EMAIL SEND
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
        mysql.connection.rollback()
        flash(f"Error: {str(e)}", "danger")

    finally:
        cur.close()

    return redirect(url_for("admin.pending_redemptions"))

@admin_bp.route("/redeem/cn/<int:coupon_id>", methods=["POST"])
def redeem_cn(coupon_id):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        remarks = request.form.get("remarks", "").strip()

        cur.execute("""
            SELECT 
                c.id, c.code, c.part_no, c.product_name, c.points,
                c.scanned_by, d.name, d.email
            FROM coupons c
            LEFT JOIN distributors d ON c.scanned_by = d.id
            WHERE c.id = %s
        """, (coupon_id,))
        row = cur.fetchone()

        if not row:
            flash("Coupon not found", "danger")
            return redirect(url_for("admin.pending_redemptions"))

        coupon_id_db, coupon_code, part_no, product_name, points, dealer_id, dealer_name, dealer_email = row

        # insert
        cur.execute("""
            INSERT INTO dealer_redemptions
            (dealer_id, coupon_id, coupon_code, redemption_type, part_no, product_name, coupons_count, redeemed_points, remarks, redeemed_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            dealer_id,
            coupon_id_db,
            coupon_code,
            "credit_note",
            part_no,
            product_name,
            1,
            points,
            remarks,
            session.get("user_id")
        ))

        # update coupon
        cur.execute("""
            UPDATE coupons
            SET is_redeemed = 1,
                status = 'redeemed'
            WHERE id = %s
        """, (coupon_id_db,))

        mysql.connection.commit()

        # EMAIL
        if dealer_email:
            send_redemption_email(
                dealer_email,
                dealer_name,
                coupon_code,
                points,
                "Credit Note"
            )

        flash("Credit note redeemed", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash(str(e), "danger")

    finally:
        cur.close()

    return redirect(url_for("admin.pending_redemptions"))