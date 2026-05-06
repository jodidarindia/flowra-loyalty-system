import secrets
import random
import string
import csv
import io
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
#import razorpay
import os
import config
from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app,
    Response,
)
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from flask_mail import Message
from extensions import mail

# razorpay_client = razorpay.Client(
#     auth=(config.RAZORPAY_KEY, config.RAZORPAY_SECRET)
# )

print("RAZORPAY KEY:", config.RAZORPAY_KEY)
print("RAZORPAY SECRET:", config.RAZORPAY_SECRET)

auth_bp = Blueprint("auth", __name__)


# ------------------------------
# Helpers
# ------------------------------
def table_columns(table_name):
    """
    Returns a set of column names for the given table.
    Prevents crashes when code expects columns that are missing in DB.
    """
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()
    try:
        cur.execute(f"SHOW COLUMNS FROM {table_name}")
        rows = cur.fetchall()
        return {row[0] for row in rows}
    except Exception:
        return set()
    finally:
        cur.close()


def has_column(table_name, column_name):
    return column_name in table_columns(table_name)


def build_select_query(table_name, wanted_columns, order_by=None, where_clause=None, limit_clause=None):
    """
    Build a safe SELECT query:
    - existing columns are selected normally
    - missing columns are selected as NULL AS col_name
    """
    existing = table_columns(table_name)
    select_parts = []

    for col in wanted_columns:
        if col in existing:
            select_parts.append(col)
        else:
            select_parts.append(f"NULL AS {col}")

    query = f"SELECT {', '.join(select_parts)} FROM {table_name}"

    if where_clause:
        query += f" {where_clause}"
    if order_by:
        query += f" ORDER BY {order_by}"
    if limit_clause:
        query += f" LIMIT {limit_clause}"

    return query


def safe_insert_subscription(user_id, plan, billing_cycle, days, is_trial, payment_status="paid", status_value="active"):
    """
    Insert into subscriptions table while handling old DB schemas gracefully.
    """
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cols = table_columns("subscriptions")

    insert_cols = ["user_id", "plan", "start_date", "end_date"]
    insert_vals = ["%s", "%s", "NOW()", f"DATE_ADD(NOW(), INTERVAL {days} DAY)"]
    params = [user_id, plan]

    if "billing_cycle" in cols:
        insert_cols.append("billing_cycle")
        insert_vals.append("%s")
        params.append(billing_cycle)

    if "is_trial" in cols:
        insert_cols.append("is_trial")
        insert_vals.append("%s")
        params.append(1 if is_trial else 0)

    if "payment_status" in cols:
        insert_cols.append("payment_status")
        insert_vals.append("%s")
        params.append(payment_status)

    if "status" in cols:
        insert_cols.append("status")
        insert_vals.append("%s")
        params.append(status_value)

    query = f"""
        INSERT INTO subscriptions
        ({', '.join(insert_cols)})
        VALUES ({', '.join(insert_vals)})
    """
    cur.execute(query, tuple(params))
    cur.close()


def is_active(user_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    subs_cols = table_columns("subscriptions")

    where_conditions = ["user_id=%s", "end_date > NOW()"]
    params = [user_id]

    if "status" in subs_cols:
        where_conditions.append("status='active'")

    cur.execute(f"""
        SELECT id FROM subscriptions
        WHERE {' AND '.join(where_conditions)}
        LIMIT 1
    """, tuple(params))

    result = cur.fetchone()
    cur.close()

    return bool(result)


def generate_temp_password(length=8):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def get_latest_active_subscription(user_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    wanted = ["id", "plan", "billing_cycle", "start_date", "end_date", "is_trial", "status"]
    subs_cols = table_columns("subscriptions")

    where_conditions = ["user_id = %s", "end_date > NOW()"]
    params = [user_id]

    if "status" in subs_cols:
        where_conditions.append("status = 'active'")

    query = build_select_query(
        "subscriptions",
        wanted,
        order_by="id DESC",
        where_clause=f"WHERE {' AND '.join(where_conditions)}",
        limit_clause="1"
    )

    cur.execute(query, tuple(params))
    row = cur.fetchone()
    cur.close()
    return row


def is_subscription_active(user_id):
    row = get_latest_active_subscription(user_id)
    return bool(row)


def send_company_credentials_email(to_email, contact_name, company_name, login_email, temp_password):
    msg = Message(
        subject="FLOWRA Company Admin Credentials",
        recipients=[to_email]
    )

    msg.body = f"""
Hello {contact_name},

Your company onboarding has been completed successfully.

Company Name: {company_name}
Login Email : {login_email}
Password    : {temp_password}

Please login to FLOWRA and change your password after first login.

Thank you,
FLOWRA Team
"""
    mail.send(msg)


# ------------------------------
# Decorators
# ------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("auth.login"))

        session_token = session.get("session_token")
        user_id = session.get("user_id")

        if not session_token or not user_id:
            session.clear()
            flash("Session expired. Please login again.", "warning")
            return redirect(url_for("auth.login"))

        mysql = current_app.config["MYSQL_INSTANCE"]
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT active_session_token
            FROM users
            WHERE id = %s
            LIMIT 1
        """, (user_id,))
        row = cur.fetchone()
        cur.close()

        db_token = row[0] if row else None

        if not db_token or db_token != session_token:
            session.clear()
            flash("Your account was logged in on another device.", "danger")
            return redirect(url_for("auth.login"))

        return f(*args, **kwargs)
    return wrapper


def has_active_subscription(user_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    subs_cols = table_columns("subscriptions")

    where_conditions = ["user_id = %s", "end_date > NOW()"]
    params = [user_id]

    if "status" in subs_cols:
        where_conditions.append("status = 'active'")

    cur.execute(f"""
        SELECT id
        FROM subscriptions
        WHERE {' AND '.join(where_conditions)}
        LIMIT 1
    """, tuple(params))
    row = cur.fetchone()
    cur.close()

    return bool(row)


def check_trial_access(user):
    if user["account_status"] == "trial":
        if datetime.now() > user["trial_end"]:
            return False
    return True


def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash("Please login first.", "warning")
                return redirect(url_for("auth.login"))

            session_token = session.get("session_token")
            user_id = session.get("user_id")

            if not session_token or not user_id:
                session.clear()
                flash("Session expired. Please login again.", "warning")
                return redirect(url_for("auth.login"))

            mysql = current_app.config["MYSQL_INSTANCE"]
            cur = mysql.connection.cursor()
            cur.execute("""
                SELECT active_session_token, role
                FROM users
                WHERE id = %s
                LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            cur.close()

            if not row:
                session.clear()
                flash("User not found. Please login again.", "danger")
                return redirect(url_for("auth.login"))

            db_token = row[0]
            db_role = (row[1] or "").strip().lower()

            if db_token != session_token:
                session.clear()
                flash("Your account was logged in on another device.", "danger")
                return redirect(url_for("auth.login"))

            allowed = [r.strip().lower() for r in allowed_roles]
            if db_role not in allowed:
                flash("Unauthorized access.", "danger")
                return redirect(url_for("auth.login"))

            return f(*args, **kwargs)
        return wrapper
    return decorator


# ------------------------------
# Pricing / Home
# ------------------------------
@auth_bp.route("/pricing")
def pricing():
    return render_template("home.html")


# ------------------------------
# Email Signup (simple user signup)
# ------------------------------
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        if not name or not email or not password:
            flash("Please fill all required fields.", "danger")
            return redirect(url_for("auth.register"))

        mysql = current_app.config["MYSQL_INSTANCE"]
        cur = mysql.connection.cursor()

        cur.execute("""
            SELECT id
            FROM users
            WHERE email = %s
              AND (is_deleted = 0 OR is_deleted IS NULL)
            LIMIT 1
        """, (email,))
        existing = cur.fetchone()

        if existing:
            cur.close()
            flash("Email already registered. Please login.", "warning")
            return redirect(url_for("auth.login"))

        try:
            hashed_password = generate_password_hash(password)

            cur.execute("""
                INSERT INTO users
                (name, email, phone, password, role, company_id, is_online, is_deleted, trial_used, account_type)
                VALUES (%s, %s, %s, %s, %s, NULL, 0, 0, 0, %s)
            """, (name, email, phone, hashed_password, "user", "paid"))

            mysql.connection.commit()
            cur.close()

            flash("Signup successful. Please login.", "success")
            return redirect(url_for("auth.login"))

        except Exception as e:
            mysql.connection.rollback()
            cur.close()
            flash(f"Registration failed: {str(e)}", "danger")
            return redirect(url_for("auth.register"))

    return render_template("register.html")


# ------------------------------
# Login
# ------------------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("Please enter email and password.", "danger")
            return redirect(url_for("auth.login"))

        mysql = current_app.config["MYSQL_INSTANCE"]
        cur = mysql.connection.cursor()

        cur.execute("""
            SELECT 
                u.id,
                u.name,
                u.email,
                u.password,
                u.role,
                u.company_id,
                c.name,
                u.account_type
            FROM users u
            LEFT JOIN companies c ON u.company_id = c.id
            WHERE LOWER(u.email) = LOWER(%s)
              AND (u.is_deleted = 0 OR u.is_deleted IS NULL)
            ORDER BY u.id DESC
            LIMIT 1
        """, (email,))
        user = cur.fetchone()

        if not user:
            cur.close()
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login"))

        user_id = user[0]
        user_name = user[1]
        user_email = user[2]
        user_password = user[3]
        user_role = (user[4] or "").strip().lower()
        company_id = user[5]
        company_name = user[6]
        account_type = (user[7] or "paid").strip().lower()

        if not check_password_hash(user_password, password):
            cur.close()
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login"))

        new_session_token = secrets.token_hex(32)

        cur.execute("""
            UPDATE users
            SET last_login = NOW(),
                is_online = 1,
                active_session_token = %s
            WHERE id = %s
        """, (new_session_token, user_id))

        mysql.connection.commit()
        cur.close()

        session.clear()
        session.permanent = True

        session["user_id"] = user_id
        session["user_name"] = user_name
        session["user_email"] = user_email
        session["user_role"] = user_role
        session["company_id"] = company_id
        session["company_name"] = company_name
        session["session_token"] = new_session_token
        session["account_type"] = account_type

        latest_sub = get_latest_active_subscription(user_id)
        if latest_sub:
            session["plan"] = latest_sub[1]
            session["billing_cycle"] = latest_sub[2] if len(latest_sub) > 2 else None
            session["subscription_end_date"] = str(latest_sub[4]) if len(latest_sub) > 4 else None
            session["is_trial"] = bool(latest_sub[5]) if len(latest_sub) > 5 and latest_sub[5] is not None else False
        else:
            session["is_trial"] = False

        if user_role == "super_admin":
            return redirect(url_for("auth.super_admin_dashboard"))
        elif user_role == "admin":
            return redirect(url_for("admin.company_admin_dashboard"))
        elif user_role == "qr_employee":
            return redirect(url_for("admin.qr_employee_dashboard"))
        elif user_role == "employee":
            return redirect(url_for("admin.general_employee_dashboard"))
        elif user_role == "sales":
            return redirect(url_for("admin.salesman_dashboard"))
        elif user_role == "user":
            return redirect(url_for("auth.pricing"))

        session.clear()
        flash("Invalid role.", "danger")
        return redirect(url_for("auth.login"))

    return render_template("login.html")


# ------------------------------
# Start Free Trial (only once, 24 hrs)
# User can take trial any time after signup
# ------------------------------
from datetime import timedelta
import secrets

@auth_bp.route("/start-free-trial", methods=["POST"])
@login_required
def start_free_trial():
    base_user_id = session.get("user_id")
    base_user_role = (session.get("user_role") or "").strip().lower()

    if not base_user_id:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    if base_user_role not in ["user", "admin"]:
        flash("Invalid account for free trial.", "warning")
        return redirect(url_for("auth.pricing"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        # original/base user fetch
        cur.execute("""
            SELECT id, name, email, phone, password, trial_used
            FROM users
            WHERE id = %s
            LIMIT 1
        """, (base_user_id,))
        row = cur.fetchone()

        if not row:
            cur.close()
            flash("User not found.", "danger")
            return redirect(url_for("auth.login"))

        base_name = (row[1] or "").strip() or "Trial User"
        base_email = (row[2] or "").strip().lower()
        base_phone = row[3] or ""
        hashed_password = row[4]
        trial_used = int(row[5] or 0)

        # ---------------------------------------------------
        # STEP 1: If already used, check if active trial admin exists
        # ---------------------------------------------------
        if trial_used == 1:
            trial_admin_email = f"trial_{base_user_id}_{base_email}"

            cur.execute("""
                SELECT id, company_id
                FROM users
                WHERE email = %s
                  AND role = 'admin'
                  AND account_type = 'trial'
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                LIMIT 1
            """, (trial_admin_email,))
            trial_admin = cur.fetchone()

            if trial_admin:
                trial_admin_user_id = trial_admin[0]
                company_id = trial_admin[1]

                cur.execute("""
                    SELECT name
                    FROM companies
                    WHERE id = %s
                    LIMIT 1
                """, (company_id,))
                company_row = cur.fetchone()
                company_name = company_row[0] if company_row else f"{base_name} Trial Company"

                # active subscription check
                cur.execute("""
                    SELECT id
                    FROM subscriptions
                    WHERE user_id = %s
                      AND end_date > NOW()
                      AND status = 'active'
                    LIMIT 1
                """, (trial_admin_user_id,))
                active_trial = cur.fetchone()

                if active_trial:
                    new_session_token = secrets.token_hex(32)

                    cur.execute("""
                        UPDATE users
                        SET last_login = NOW(),
                            is_online = 1,
                            active_session_token = %s
                        WHERE id = %s
                    """, (new_session_token, trial_admin_user_id))

                    mysql.connection.commit()
                    cur.close()

                    session.clear()
                    session.permanent = True
                    session["user_id"] = trial_admin_user_id
                    session["user_name"] = base_name
                    session["user_email"] = trial_admin_email
                    session["user_role"] = "admin"
                    session["company_id"] = company_id
                    session["company_name"] = company_name
                    session["session_token"] = new_session_token
                    session["account_type"] = "trial"
                    session["plan"] = "starter"
                    session["billing_cycle"] = "trial"
                    session["is_trial"] = True

                    flash("Your free trial is still active.", "success")
                    return redirect(url_for("admin.company_admin_dashboard"))

            cur.close()
            flash("Free trial already used.", "warning")
            return redirect(url_for("auth.pricing"))

        # ---------------------------------------------------
        # STEP 2: No trial used yet → create new clean trial admin
        # ---------------------------------------------------
        company_name = f"{base_name} Trial Company"
        cur.execute("""
            INSERT INTO companies (name, status)
            VALUES (%s, %s)
        """, (company_name, "Active"))
        company_id = cur.lastrowid

        trial_admin_email = f"trial_{base_user_id}_{base_email}"

        cur.execute("""
            INSERT INTO users
            (name, email, phone, password, role, company_id, is_online, is_deleted, trial_used, account_type)
            VALUES (%s, %s, %s, %s, %s, %s, 0, 0, 1, %s)
        """, (
            base_name,
            trial_admin_email,
            base_phone,
            hashed_password,
            "admin",
            company_id,
            "trial"
        ))
        trial_admin_user_id = cur.lastrowid

        safe_insert_subscription(
            user_id=trial_admin_user_id,
            plan="starter",
            billing_cycle="trial",
            days=1,
            is_trial=True,
            payment_status="free",
            status_value="active"
        )

        cur.execute("""
            UPDATE users
            SET trial_used = 1
            WHERE id = %s
        """, (base_user_id,))

        new_session_token = secrets.token_hex(32)
        cur.execute("""
            UPDATE users
            SET last_login = NOW(),
                is_online = 1,
                active_session_token = %s
            WHERE id = %s
        """, (new_session_token, trial_admin_user_id))

        mysql.connection.commit()
        cur.close()

        session.clear()
        session.permanent = True
        session["user_id"] = trial_admin_user_id
        session["user_name"] = base_name
        session["user_email"] = trial_admin_email
        session["user_role"] = "admin"
        session["company_id"] = company_id
        session["company_name"] = company_name
        session["session_token"] = new_session_token
        session["account_type"] = "trial"
        session["plan"] = "starter"
        session["billing_cycle"] = "trial"
        session["is_trial"] = True

        flash("Your 24-hour free trial has started.", "success")
        return redirect(url_for("admin.company_admin_dashboard"))

    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        flash(f"Could not start free trial: {str(e)}", "danger")
        return redirect(url_for("auth.pricing"))


# ------------------------------
# Paid Plan Form
# ------------------------------
@auth_bp.route("/subscription", methods=["GET", "POST"])
def subscription():
    from flask import request, render_template, flash, redirect, url_for, current_app
    import os, secrets
    from werkzeug.utils import secure_filename

    mysql = current_app.config["MYSQL_INSTANCE"]

    # GET → form open
    if request.method == "GET":
        plan = request.args.get("plan", "starter")
        cycle = request.args.get("cycle", "monthly")

        return render_template(
            "subscription.html",
            selected_plan=plan,
            selected_cycle=cycle
        )

    # POST → form submit
    company_name = request.form.get("company_name")
    contact_person = request.form.get("contact_person")
    email = request.form.get("email")
    phone = request.form.get("phone")
    gst_number = request.form.get("gst_number")
    address = request.form.get("address")
    preferred_plan = request.form.get("preferred_plan")
    billing_cycle = request.form.get("billing_cycle")
    message = request.form.get("message")

    # 🔥 FILE UPLOAD
    payment_file = request.files.get("payment_screenshot")

    if not payment_file or payment_file.filename == "":
        flash("Upload payment screenshot", "danger")
        return redirect(request.url)

    upload_folder = os.path.join(
        current_app.root_path,
        "static/uploads/payment_screenshots"
    )
    os.makedirs(upload_folder, exist_ok=True)

    filename = secure_filename(payment_file.filename)
    unique_name = f"{secrets.token_hex(8)}_{filename}"
    payment_file.save(os.path.join(upload_folder, unique_name))

    # 🔥 INSERT DB
    cur = mysql.connection.cursor()

    cur.execute("""
        INSERT INTO subscription_enquiries
        (
            company_name,
            contact_person,
            email,
            phone,
            gst_number,
            address,
            preferred_plan,
            billing_cycle,
            message,
            payment_status,
            status,
            payment_screenshot,
            created_at
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
    """, (
        company_name,
        contact_person,
        email,
        phone,
        gst_number,
        address,
        preferred_plan,
        billing_cycle,
        message,
        "pending",
        "pending",
        unique_name
    ))

    mysql.connection.commit()
    cur.close()

    flash("Subscription request submitted successfully!", "success")
    return redirect(url_for("auth.pricing"))


@auth_bp.route("/subscription-success")
@login_required
def subscription_success():
    return render_template("subscription_success.html")


# ------------------------------
# Super Admin Dashboard
# ------------------------------
@auth_bp.route("/super-admin/dashboard")
@login_required
def super_admin_dashboard():
    if session.get("user_role") != "super_admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        cur.execute("""
            SELECT COUNT(*)
            FROM companies
            WHERE is_deleted = 0 OR is_deleted IS NULL
        """)
        total_companies = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM companies
            WHERE (is_deleted = 0 OR is_deleted IS NULL)
              AND status = 'Active'
        """)
        active_companies = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM subscription_enquiries
            WHERE status = 'pending' OR status IS NULL
        """)
        pending_enquiries = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM subscriptions
            WHERE status = 'active'
              AND payment_status = 'paid'
              AND end_date > NOW()
        """)
        total_paid_subscriptions = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE role = 'admin'
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """)
        total_admins = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM subscription_enquiries
            WHERE status IN ('approved', 'converted')
        """)
        converted_enquiries = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE account_type = 'trial'
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """)
        total_trial_accounts = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM subscriptions
            WHERE plan = 'starter'
              AND status = 'active'
              AND end_date > NOW()
        """)
        starter_count = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM subscriptions
            WHERE plan = 'professional'
              AND status = 'active'
              AND end_date > NOW()
        """)
        professional_count = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(*)
            FROM subscriptions
            WHERE plan = 'enterprise'
              AND status = 'active'
              AND end_date > NOW()
        """)
        enterprise_count = cur.fetchone()[0] or 0

        cur.close()

    except Exception as e:
        cur.close()
        flash(f"Dashboard error: {str(e)}", "danger")

        total_companies = 0
        active_companies = 0
        pending_enquiries = 0
        total_paid_subscriptions = 0
        total_admins = 0
        converted_enquiries = 0
        total_trial_accounts = 0
        starter_count = 0
        professional_count = 0
        enterprise_count = 0

    return render_template(
        "super_admin_dashboard.html",
        total_companies=total_companies,
        active_companies=active_companies,
        pending_enquiries=pending_enquiries,
        total_paid_subscriptions=total_paid_subscriptions,
        total_admins=total_admins,
        converted_enquiries=converted_enquiries,
        total_trial_accounts=total_trial_accounts,
        starter_count=starter_count,
        professional_count=professional_count,
        enterprise_count=enterprise_count
    )

@auth_bp.route("/super-admin/payment-review")
@login_required
def super_admin_payment_review():
    if session.get("user_role") != "super_admin":
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT id, company_name, contact_person, email, phone,
               preferred_plan, billing_cycle, payment_screenshot,
               payment_status, status, created_at
        FROM subscription_enquiries
        WHERE status = 'pending' OR status IS NULL
        ORDER BY id DESC
    """)
    enquiries = cur.fetchall()
    cur.close()

    return render_template("payment_review.html", enquiries=enquiries)



@auth_bp.route("/approve-enquiry/<int:enquiry_id>", methods=["POST"])
@login_required
def approve_enquiry(enquiry_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        UPDATE subscription_enquiries
        SET status = 'approved',
            payment_status = 'paid'
        WHERE id = %s
    """, (enquiry_id,))

    mysql.connection.commit()
    cur.close()

    flash("Payment Approved!", "success")
    return redirect(url_for("auth.super_admin_payment_review"))

@auth_bp.route("/reject-enquiry/<int:enquiry_id>", methods=["POST"])
@login_required
def reject_enquiry(enquiry_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        UPDATE subscription_enquiries
        SET status = 'rejected'
        WHERE id = %s
    """, (enquiry_id,))

    mysql.connection.commit()
    cur.close()

    flash("Enquiry Rejected!", "danger")
    return redirect(url_for("auth.super_admin_payment_review"))

@auth_bp.route("/super-admin/dispatch")
@login_required
def super_admin_dispatch():
    if session.get("user_role") != "super_admin":
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT id, company_name, contact_person, email, phone,
               preferred_plan, billing_cycle, payment_status, status, created_at
        FROM subscription_enquiries
        WHERE status = 'approved'
        ORDER BY id DESC
    """)
    enquiries = cur.fetchall()
    cur.close()

    return render_template("dispatch.html", enquiries=enquiries)

@auth_bp.route("/send-credentials/<int:enquiry_id>", methods=["POST"])
@login_required
def send_credentials(enquiry_id):
    import random, string
    from werkzeug.security import generate_password_hash

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    # 🔥 enquiry data
    cur.execute("""
        SELECT company_name, contact_person, email
        FROM subscription_enquiries
        WHERE id = %s
    """, (enquiry_id,))
    data = cur.fetchone()

    if not data:
        flash("Invalid request", "danger")
        return redirect(url_for("auth.super_admin_dispatch"))

    company_name, name, email = data

    # 🔥 IMPORTANT: existing company find karo
    cur.execute("""
        SELECT id FROM companies
        WHERE name = %s
        LIMIT 1
    """, (company_name,))
    company = cur.fetchone()

    if not company:
        flash("Company not found! Pehle company create karo.", "danger")
        return redirect(url_for("auth.super_admin_dispatch"))

    company_id = company[0]

    # 🔥 password generate
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    hashed_password = generate_password_hash(password)

    # 🔥 admin create
    cur.execute("""
        INSERT INTO users
        (name, email, password, role, company_id, account_type, is_deleted)
        VALUES (%s, %s, %s, 'admin', %s, 'paid', 0)
    """, (name, email, hashed_password, company_id))

    # 🔥 mark converted
    cur.execute("""
        UPDATE subscription_enquiries
        SET status = 'converted'
        WHERE id = %s
    """, (enquiry_id,))

    mysql.connection.commit()
    cur.close()

    # 🔥 email
    try:
        from flask_mail import Message
        from app import mail

        msg = Message(
            "Your FLOWRA Admin Account",
            recipients=[email]
        )
        msg.body = f"""
Hello {name},

Your admin account is ready.

Company: {company_name}
Email: {email}
Password: {password}

Login: http://127.0.0.1:5000/login

- FLOWRA
"""
        mail.send(msg)

    except Exception as e:
        print("MAIL ERROR:", e)

    flash("Admin created & credentials sent!", "success")
    return redirect(url_for("auth.super_admin_dispatch"))


@auth_bp.route("/mark-as-paid/<int:enquiry_id>", methods=["POST"])
@login_required
def mark_as_paid(enquiry_id):
    if session.get("user_role") != "super_admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        cur.execute("""
            UPDATE subscription_enquiries
            SET payment_status = 'paid'
            WHERE id = %s
        """, (enquiry_id,))

        mysql.connection.commit()
        flash("Payment marked as paid. You can now approve and convert.", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash(f"Failed to mark as paid: {str(e)}", "danger")

    finally:
        cur.close()

    return redirect(url_for("auth.super_admin_subscription_enquiries"))


# ------------------------------
# Super Admin - View paid enquiries
# ------------------------------
@auth_bp.route("/super-admin/subscription-enquiries")
@login_required
def super_admin_subscription_enquiries():
    if session.get("user_role") != "super_admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT
            id,
            company_name,
            contact_person,
            email,
            phone,
            preferred_plan,
            billing_cycle,
            gst_number,
            referral_code,
            message,
            payment_screenshot,
            payment_status,
            status,
            created_at
        FROM subscription_enquiries
        ORDER BY id DESC
    """)
    rows = cur.fetchall()
    cur.close()

    enquiries = []
    for r in rows:
        enquiries.append({
            "id": r[0],
            "company_name": r[1],
            "contact_person": r[2],
            "email": r[3],
            "phone": r[4],
            "preferred_plan": r[5],
            "billing_cycle": r[6],
            "gst_number": r[7],
            "referral_code": r[8],
            "message": r[9],
            "payment_screenshot": r[10],
            "payment_status": r[11],
            "status": r[12] or "pending",
            "created_at": r[13],
        })

    return render_template(
        "super_admin_subscription_enquiries.html",
        enquiries=enquiries
    )


# ------------------------------
# Super Admin - Export enquiries CSV
# ------------------------------
@auth_bp.route("/super-admin/subscription-enquiries/export")
@login_required
@role_required("super_admin")
def export_subscription_enquiries():
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    wanted = [
        "id",
        "company_name",
        "contact_person",
        "email",
        "phone",
        "gst_number",
        "address",
        "preferred_plan",
        "billing_cycle",
        "message",
        "referral_code",
        "payment_status",
        "payment_id",
        "order_id",
        "status",
        "created_at"
    ]

    query = build_select_query(
        "subscription_enquiries",
        wanted,
        order_by="id DESC"
    )

    cur.execute(query)
    rows = cur.fetchall()
    cur.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID", "Company Name", "Contact Person", "Email", "Phone", "GST Number",
        "Address", "Preferred Plan", "Billing Cycle", "Message", "Referral Code",
        "Payment Status", "Payment ID", "Order ID", "Status", "Created At"
    ])

    for row in rows:
        writer.writerow(list(row))

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=subscription_enquiries.csv"}
    )



@auth_bp.route("/")
def coupon_home():
    return render_template("home.html")
# ------------------------------
# Super Admin - Convert paid enquiry into real company admin
# ------------------------------
@auth_bp.route("/super-admin/subscription-enquiries/convert/<int:enquiry_id>", methods=["POST"])
@login_required
@role_required("super_admin")
def convert_subscription_enquiry(enquiry_id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    try:
        wanted = [
            "id",
            "company_name",
            "contact_person",
            "email",
            "phone",
            "preferred_plan",
            "billing_cycle",
            "payment_status",
            "status"
        ]

        query = build_select_query(
            "subscription_enquiries",
            wanted,
            where_clause="WHERE id = %s",
            limit_clause="1"
        )

        cur.execute(query, (enquiry_id,))
        enquiry = cur.fetchone()

        if not enquiry:
            cur.close()
            flash("Enquiry not found.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        enquiry_id_db = enquiry[0]
        company_name = enquiry[1]
        contact_person = enquiry[2]
        email = enquiry[3]
        phone = enquiry[4]
        preferred_plan = enquiry[5] or "starter"
        billing_cycle = (enquiry[6] or "monthly").strip().lower()
        payment_status = (enquiry[7] or "paid").strip().lower()
        status = (enquiry[8] or "pending").strip().lower()

        if payment_status not in ["paid", ""]:
            cur.close()
            flash("This enquiry is not marked as paid.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        if status == "converted":
            cur.close()
            flash("This enquiry is already converted.", "warning")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        cur.execute("""
            INSERT INTO companies (name, status)
            VALUES (%s, %s)
        """, (company_name, "Active"))
        company_id = cur.lastrowid

        temp_password = generate_temp_password(8)
        hashed_password = generate_password_hash(temp_password)

        cur.execute("""
            INSERT INTO users
            (name, email, phone, password, role, company_id, is_online, is_deleted, trial_used)
            VALUES (%s, %s, %s, %s, %s, %s, 0, 0, 1)
        """, (
            contact_person,
            email,
            phone,
            hashed_password,
            "admin",
            company_id
        ))
        admin_user_id = cur.lastrowid

        if billing_cycle == "yearly":
            safe_insert_subscription(
                user_id=admin_user_id,
                plan=preferred_plan,
                billing_cycle="yearly",
                days=365,
                is_trial=False,
                payment_status="paid",
                status_value="active"
            )
        else:
            safe_insert_subscription(
                user_id=admin_user_id,
                plan=preferred_plan,
                billing_cycle="monthly",
                days=30,
                is_trial=False,
                payment_status="paid",
                status_value="active"
            )

        enquiry_cols = table_columns("subscription_enquiries")
        update_parts = []
        params = []

        if "status" in enquiry_cols:
            update_parts.append("status = %s")
            params.append("converted")

        if "converted_company_id" in enquiry_cols:
            update_parts.append("converted_company_id = %s")
            params.append(company_id)

        if "converted_admin_user_id" in enquiry_cols:
            update_parts.append("converted_admin_user_id = %s")
            params.append(admin_user_id)

        if update_parts:
            params.append(enquiry_id_db)
            cur.execute(f"""
                UPDATE subscription_enquiries
                SET {', '.join(update_parts)}
                WHERE id = %s
            """, tuple(params))

        mysql.connection.commit()
        cur.close()

        send_company_credentials_email(
            to_email=email,
            contact_name=contact_person,
            company_name=company_name,
            login_email=email,
            temp_password=temp_password
        )

        flash("Enquiry converted successfully and credentials emailed.", "success")
        return redirect(url_for("auth.super_admin_subscription_enquiries"))

    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        flash(f"Conversion failed: {str(e)}", "danger")
        return redirect(url_for("auth.super_admin_subscription_enquiries"))


@auth_bp.route("/dashboard")
def dashboard():
    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("auth.login"))

    if not is_active(user_id):
        flash("Trial expired. Please upgrade.", "danger")
        return redirect(url_for("auth.pricing"))

    return render_template("dashboard.html")


@auth_bp.route("/buy-plan", methods=["POST"])
def buy_plan():
    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("auth.login"))

    company = request.form.get("company_name")
    plan = request.form.get("plan")

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    enquiry_cols = table_columns("subscription_enquiries")

    insert_cols = ["company_name", "preferred_plan"]
    insert_vals = ["%s", "%s"]
    params = [company, plan]

    if "payment_status" in enquiry_cols:
        insert_cols.append("payment_status")
        insert_vals.append("%s")
        params.append("paid")

    if "status" in enquiry_cols:
        insert_cols.append("status")
        insert_vals.append("%s")
        params.append("pending")

    cur.execute(f"""
        INSERT INTO subscription_enquiries
        ({', '.join(insert_cols)})
        VALUES ({', '.join(insert_vals)})
    """, tuple(params))

    mysql.connection.commit()
    cur.close()

    flash("Plan request submitted!", "success")
    return redirect(url_for("auth.dashboard"))


@auth_bp.route("/convert/<int:id>")
def convert_user(id):
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    wanted = ["company_name", "preferred_plan", "payment_status"]
    query = build_select_query(
        "subscription_enquiries",
        wanted,
        where_clause="WHERE id=%s",
        limit_clause="1"
    )
    cur.execute(query, (id,))
    enquiry = cur.fetchone()

    if not enquiry:
        cur.close()
        flash("Payment not verified!", "danger")
        return redirect(url_for("auth.super_admin_dashboard"))

    company_name = enquiry[0]
    plan = enquiry[1]
    payment_status = (enquiry[2] or "paid").strip().lower()

    if payment_status not in ["paid", ""]:
        cur.close()
        flash("Payment not verified!", "danger")
        return redirect(url_for("auth.super_admin_dashboard"))

    password = str(random.randint(100000, 999999))

    cur.execute("INSERT INTO companies (name) VALUES (%s)", (company_name,))
    company_id = cur.lastrowid

    cur.execute("""
        INSERT INTO users (email, password, role, company_id)
        VALUES (%s, %s, 'admin', %s)
    """, ("client@example.com", generate_password_hash(password), company_id))

    user_id = cur.lastrowid

    safe_insert_subscription(
        user_id=user_id,
        plan=plan,
        billing_cycle="monthly",
        days=30,
        is_trial=False,
        payment_status="paid",
        status_value="active"
    )

    enquiry_cols = table_columns("subscription_enquiries")
    if "status" in enquiry_cols:
        cur.execute("""
            UPDATE subscription_enquiries
            SET status='converted'
            WHERE id=%s
        """, (id,))

    mysql.connection.commit()
    cur.close()

    flash(f"User created. Password: {password}", "success")
    return redirect(url_for("auth.super_admin_dashboard"))


# ------------------------------
# Super Admin Analytics
# ------------------------------
@auth_bp.route("/super-admin/analytics")
@login_required
@role_required("super_admin")
def super_admin_analytics():
    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("SELECT COUNT(*) FROM companies WHERE is_deleted = 0")
    total_companies = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT c.id)
        FROM companies c
        LEFT JOIN users u ON c.id = u.company_id
        WHERE c.is_deleted = 0
          AND u.is_online = 1
    """)
    active_companies = cur.fetchone()[0]

    inactive_companies = total_companies - active_companies

    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    total_admins = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE role IN ('employee', 'qr_employee', 'sales')
    """)
    total_employees = cur.fetchone()[0]

    cur.close()

    return render_template(
        "super_admin_analytics.html",
        total_companies=total_companies,
        active_companies=active_companies,
        inactive_companies=inactive_companies,
        total_admins=total_admins,
        total_employees=total_employees
    )


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email").lower()
        password = request.form.get("password")

        mysql = current_app.config["MYSQL_INSTANCE"]
        cur = mysql.connection.cursor()

        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            flash("Email already exists", "danger")
            cur.close()
            return redirect(url_for("auth.signup"))

        cur.execute("""
            INSERT INTO users (name, email, password, role, trial_used)
            VALUES (%s, %s, %s, 'user', 0)
        """, (name, email, generate_password_hash(password)))

        mysql.connection.commit()
        cur.close()

        flash("Signup successful. Login now.", "success")
        return redirect(url_for("auth.login"))

    return render_template("signup.html")


@auth_bp.route("/start-trial")
def start_trial():
    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("auth.login"))

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    cur.execute("SELECT trial_used FROM users WHERE id=%s", (user_id,))
    trial_used_row = cur.fetchone()
    trial_used = trial_used_row[0] if trial_used_row else 0

    if trial_used == 1:
        cur.close()
        flash("Free trial already used!", "warning")
        return redirect(url_for("auth.pricing"))

    cur.execute("UPDATE users SET trial_used=1 WHERE id=%s", (user_id,))

    safe_insert_subscription(
        user_id=user_id,
        plan="starter",
        billing_cycle="trial",
        days=1,
        is_trial=True,
        payment_status="free",
        status_value="active"
    )

    mysql.connection.commit()
    cur.close()

    flash("24-hour free trial started!", "success")
    return redirect(url_for("auth.dashboard"))


@auth_bp.route("/create-company-from-enquiry", methods=["POST"])
@login_required
@role_required("super_admin")
def create_company_from_enquiry():
    import secrets
    from werkzeug.security import generate_password_hash

    mysql = current_app.config["MYSQL_INSTANCE"]
    cur = mysql.connection.cursor()

    enquiry_id = request.form.get("enquiry_id")
    company_name = request.form.get("company_name", "").strip()
    admin_name = request.form.get("admin_name", "").strip()
    admin_email = request.form.get("admin_email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    plan = request.form.get("plan", "starter").strip().lower()
    billing_cycle = request.form.get("billing_cycle", "monthly").strip().lower()

    try:
        if not enquiry_id or not company_name or not admin_name or not admin_email:
            flash("Please fill all required fields.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        cur.execute("""
            SELECT payment_status, status
            FROM subscription_enquiries
            WHERE id = %s
            LIMIT 1
        """, (enquiry_id,))
        enquiry = cur.fetchone()

        if not enquiry:
            flash("Enquiry not found.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        payment_status = (enquiry[0] or "pending").strip().lower()
        current_status = (enquiry[1] or "pending").strip().lower()

        if payment_status != "paid":
            flash("Please mark payment as paid first.", "warning")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        if current_status == "converted":
            flash("This enquiry is already converted.", "warning")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        cur.execute("""
            SELECT id
            FROM users
            WHERE LOWER(email) = LOWER(%s)
              AND (is_deleted = 0 OR is_deleted IS NULL)
            LIMIT 1
        """, (admin_email,))
        existing_user = cur.fetchone()

        if existing_user:
            flash("This email is already used by another active account.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        cur.execute("""
            SELECT id
            FROM companies
            WHERE LOWER(name) = LOWER(%s)
              AND (is_deleted = 0 OR is_deleted IS NULL)
            LIMIT 1
        """, (company_name,))
        existing_company = cur.fetchone()

        if existing_company:
            company_id = existing_company[0]
        else:
            cur.execute("""
                INSERT INTO companies (name, status)
                VALUES (%s, 'Active')
            """, (company_name,))
            company_id = cur.lastrowid

        temp_password = secrets.token_urlsafe(8)
        hashed_password = generate_password_hash(temp_password)

        cur.execute("""
            INSERT INTO users
            (name, email, phone, password, role, company_id, account_type, is_online, is_deleted, trial_used)
            VALUES (%s, %s, %s, %s, 'admin', %s, 'paid', 0, 0, 0)
        """, (
            admin_name,
            admin_email,
            phone,
            hashed_password,
            company_id
        ))
        admin_user_id = cur.lastrowid

        if billing_cycle == "yearly":
            safe_insert_subscription(
                user_id=admin_user_id,
                plan=plan,
                billing_cycle="yearly",
                days=365,
                is_trial=False,
                payment_status="paid",
                status_value="active"
            )
        else:
            safe_insert_subscription(
                user_id=admin_user_id,
                plan=plan,
                billing_cycle="monthly",
                days=30,
                is_trial=False,
                payment_status="paid",
                status_value="active"
            )

        cur.execute("""
            UPDATE subscription_enquiries
            SET status = 'converted',
                payment_status = 'paid',
                converted_company_id = %s,
                converted_admin_user_id = %s
            WHERE id = %s
        """, (company_id, admin_user_id, enquiry_id))

        mysql.connection.commit()

        try:
            send_company_credentials_email(
                to_email=admin_email,
                contact_name=admin_name,
                company_name=company_name,
                login_email=admin_email,
                temp_password=temp_password
            )
            flash("Company/Admin created and credentials emailed.", "success")
        except Exception as mail_error:
            flash(f"Company/Admin created. Email failed. Temporary password: {temp_password}", "warning")
            print("MAIL ERROR:", mail_error)

    except Exception as e:
        mysql.connection.rollback()
        flash(f"Company creation failed: {str(e)}", "danger")

    finally:
        cur.close()

    return redirect(url_for("auth.super_admin_subscription_enquiries"))

# @auth_bp.route("/create-payment-link", methods=["POST"])
# @login_required
# def create_payment_link():
#     data = request.get_json(silent=True) or {}

#     customer_name = (data.get("name") or "").strip()
#     customer_email = (data.get("email") or "").strip().lower()
#     customer_phone = (data.get("phone") or "").strip()
#     plan = (data.get("plan") or "").strip().lower()
#     cycle = (data.get("cycle") or "").strip().lower()

#     if not customer_name or not customer_email or not customer_phone or not plan or not cycle:
#         return jsonify({"success": False, "message": "Missing required fields"}), 400

#     try:
#         payment_link = razorpay_client.payment_link.create({
#             "amount": 100,
#             "currency": "INR",
#             "accept_partial": False,
#             "description": f"FLOWRA {plan.title()} ({cycle}) subscription test payment",
#             "customer": {
#                 "name": customer_name,
#                 "email": customer_email,
#                 "contact": customer_phone
#             },
#             "notify": {
#                 "sms": False,
#                 "email": False
#             },
#             "reminder_enable": False,
#             "notes": {
#                 "plan": plan,
#                 "cycle": cycle,
#                 "source": "flowra_subscription"
#             },
#             "callback_url": url_for("auth.subscription", _external=True),
#             "callback_method": "get"
#         })

#         return jsonify({
#             "success": True,
#             "payment_link_id": payment_link["id"],
#             "payment_link_url": payment_link["short_url"]
#         })

#     except Exception as e:
#         return jsonify({
#             "success": False,
#             "message": f"Payment link creation failed: {str(e)}"
#         }), 500

# @auth_bp.route("/create-payment-order", methods=["POST"])
# @login_required
# def create_payment_order():
#     data = request.get_json(silent=True) or {}

#     print("CREATE PAYMENT ORDER HIT")
#     print("JSON DATA:", data)

#     plan = (data.get("plan") or "").strip().lower()
#     cycle = (data.get("cycle") or "").strip().lower()

#     # Abhi testing ke liye sab ₹1
#     price_map = {
#         ("starter", "monthly"): 100,
#         ("starter", "yearly"): 100,
#         ("professional", "monthly"): 100,
#         ("professional", "yearly"): 100,
#         ("enterprise", "monthly"): 100,
#         ("enterprise", "yearly"): 100,
#     }

#     amount = price_map.get((plan, cycle))
#     if not amount:
#         print("INVALID PLAN/CYCLE:", plan, cycle)
#         return jsonify({
#             "success": False,
#             "message": "Invalid plan or cycle"
#         }), 400

#     try:
#         order = razorpay_client.order.create({
#             "amount": amount,
#             "currency": "INR",
#             "payment_capture": 1
#         })

#         print("ORDER CREATED:", order)

#         return jsonify({
#             "success": True,
#             "order_id": order["id"],
#             "amount": amount,
#             "key": config.RAZORPAY_KEY
#         })

#     except Exception as e:
#         print("RAZORPAY ERROR:", str(e))
#         return jsonify({
#             "success": False,
#             "message": f"Payment order creation failed: {str(e)}"
#         }), 500


# @auth_bp.route("/check-payment-qr/<qr_id>", methods=["GET"])
# def check_payment_qr(qr_id):
#     try:
#         qr = razorpay_client.qrcode.fetch(qr_id)

#         close_reason = qr.get("close_reason")
#         status = qr.get("status")
#         payments_amount_received = qr.get("payments_amount_received", 0)

#         paid = False
#         if status == "closed" and payments_amount_received > 0:
#             paid = True

#         return jsonify({
#             "status": "success",
#             "paid": paid,
#             "qr_status": status,
#             "amount_received": payments_amount_received,
#             "close_reason": close_reason
#         })
#     except Exception as e:
#         return jsonify({"status": "failed", "message": str(e)}), 500


# ------------------------------
# Logout
# ------------------------------
@auth_bp.route("/logout")
def logout():
    if "user_id" in session:
        mysql = current_app.config["MYSQL_INSTANCE"]
        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE users
            SET is_online = 0,
                active_session_token = NULL
            WHERE id = %s
        """, (session.get("user_id"),))
        mysql.connection.commit()
        cur.close()

    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("auth.login"))