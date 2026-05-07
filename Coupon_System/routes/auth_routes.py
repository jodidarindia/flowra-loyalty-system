import secrets
import random
import string
import csv
import io
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import get_db
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
    MongoDB me schema fixed nahi hota,
    isliye compatibility ke liye empty set return kar rahe hain.
    """
    return set()

def oid(value):
    try:
        return ObjectId(value)
    except:
        return value

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


from datetime import datetime, timedelta

def safe_insert_subscription(
    user_id,
    plan,
    billing_cycle,
    days,
    is_trial,
    payment_status="paid",
    status_value="active"
):
    db = get_db()

    start_date = datetime.utcnow()
    end_date = start_date + timedelta(days=int(days))

    subscription_data = {
        "user_id": str(user_id),
        "plan": plan,
        "billing_cycle": billing_cycle,
        "is_trial": bool(is_trial),
        "payment_status": payment_status,
        "status": status_value,
        "start_date": start_date,
        "end_date": end_date,
        "created_at": start_date,
        "is_deleted": 0
    }

    result = db.subscriptions.insert_one(subscription_data)

    return str(result.inserted_id)


def is_active(user_id):
    db = get_db()
    subscription = db.subscriptions.find_one({
        "user_id": str(user_id),
        "end_date": {"$gt": datetime.utcnow()},
        "is_deleted": 0
    })
    return bool(subscription)
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
    db = get_db()
    subscription = db.subscriptions.find_one({
        "user_id": str(user_id),
        "end_date": {"$gt": datetime.utcnow()},
        "is_deleted": 0
    })
    return subscription


    



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
from functools import wraps
from flask import session, flash, redirect, url_for, current_app
from bson.objectid import ObjectId

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

        db = get_db()

        try:
            user = db.users.find_one({
                "_id": ObjectId(user_id)
            })
        except:
            user = db.users.find_one({
                "_id": user_id
            })

        db_token = user.get("active_session_token") if user else None

        if not db_token or db_token != session_token:
            session.clear()
            flash("Your account was logged in on another device.", "danger")
            return redirect(url_for("auth.login"))

        return f(*args, **kwargs)

    return wrapper


from datetime import datetime

def has_active_subscription(user_id):
    db = get_db()

    subscription = db.subscriptions.find_one({
        "user_id": str(user_id),
        "end_date": {"$gt": datetime.utcnow()},
        "$or": [
            {"status": "active"},
            {"status": {"$exists": False}},
            {"status": None}
        ],
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    return bool(subscription)


def check_trial_access(user):
    if user["account_status"] == "trial":
        if datetime.now() > user["trial_end"]:
            return False
    return True


from functools import wraps
from flask import session, flash, redirect, url_for
from bson.objectid import ObjectId

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

            db = get_db()

            try:
                user = db.users.find_one({
                    "_id": ObjectId(user_id)
                })
            except:
                user = db.users.find_one({
                    "_id": user_id
                })

            if not user:
                session.clear()
                flash("User not found. Please login again.", "danger")
                return redirect(url_for("auth.login"))

            db_token = user.get("active_session_token")
            db_role = (user.get("role") or "").strip().lower()

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

        db = get_db()

        existing = db.users.find_one({
            "email": email,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing:
            flash("Email already registered. Please login.", "warning")
            return redirect(url_for("auth.login"))

        try:
            hashed_password = generate_password_hash(password)

            db.users.insert_one({
                "name": name,
                "email": email,
                "phone": phone,
                "password": hashed_password,
                "role": "user",
                "company_id": None,
                "is_online": 0,
                "is_deleted": 0,
                "trial_used": 0,
                "account_type": "paid",
                "created_at": datetime.utcnow()
            })

            flash("Signup successful. Please login.", "success")
            return redirect(url_for("auth.login"))

        except Exception as e:
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

        db = get_db()

        user = db.users.find_one({
            "email": email,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        }, sort=[("_id", -1)])

        if not user:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login"))

        user_id = str(user.get("_id"))
        user_name = user.get("name", "")
        user_email = user.get("email", "")
        user_password = user.get("password", "")
        user_role = (user.get("role") or "").strip().lower()
        company_id = user.get("company_id")
        account_type = (user.get("account_type") or "paid").strip().lower()

        company_name = ""
        if company_id:
            company = db.companies.find_one({"_id": oid(company_id)})
            company_name = company.get("name", "") if company else ""

        if not user_password or not check_password_hash(user_password, password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login"))

        new_session_token = secrets.token_hex(32)

        db.users.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "last_login": datetime.utcnow(),
                    "is_online": 1,
                    "active_session_token": new_session_token
                }
            }
        )

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
            session["plan"] = latest_sub.get("plan")
            session["billing_cycle"] = latest_sub.get("billing_cycle")
            session["subscription_end_date"] = str(latest_sub.get("end_date"))
            session["is_trial"] = bool(latest_sub.get("is_trial", False))
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

    db = get_db()

    try:
        base_user = db.users.find_one({"_id": oid(base_user_id)})

        if not base_user:
            flash("User not found.", "danger")
            return redirect(url_for("auth.login"))

        base_name = (base_user.get("name") or "").strip() or "Trial User"
        base_email = (base_user.get("email") or "").strip().lower()
        base_phone = base_user.get("phone", "")
        hashed_password = base_user.get("password", "")
        trial_used = int(base_user.get("trial_used") or 0)

        trial_admin_email = f"trial_{base_user_id}_{base_email}"

        if trial_used == 1:
            trial_admin = db.users.find_one({
                "email": trial_admin_email,
                "role": "admin",
                "account_type": "trial",
                "$or": [
                    {"is_deleted": 0},
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}},
                    {"is_deleted": None}
                ]
            })

            if trial_admin:
                trial_admin_user_id = str(trial_admin.get("_id"))
                company_id = trial_admin.get("company_id")

                company_name = f"{base_name} Trial Company"
                if company_id:
                    company = db.companies.find_one({"_id": oid(company_id)})
                    if company:
                        company_name = company.get("name", company_name)

                active_trial = db.subscriptions.find_one({
                    "user_id": trial_admin_user_id,
                    "status": "active",
                    "end_date": {"$gt": datetime.utcnow()}
                })

                if active_trial:
                    new_session_token = secrets.token_hex(32)

                    db.users.update_one(
                        {"_id": trial_admin["_id"]},
                        {
                            "$set": {
                                "last_login": datetime.utcnow(),
                                "is_online": 1,
                                "active_session_token": new_session_token
                            }
                        }
                    )

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

            flash("Free trial already used.", "warning")
            return redirect(url_for("auth.pricing"))

        company_name = f"{base_name} Trial Company"

        company_result = db.companies.insert_one({
            "name": company_name,
            "status": "Active",
            "is_deleted": 0,
            "created_at": datetime.utcnow()
        })

        company_id = str(company_result.inserted_id)

        trial_admin_result = db.users.insert_one({
            "name": base_name,
            "email": trial_admin_email,
            "phone": base_phone,
            "password": hashed_password,
            "role": "admin",
            "company_id": company_id,
            "is_online": 0,
            "is_deleted": 0,
            "trial_used": 1,
            "account_type": "trial",
            "created_at": datetime.utcnow()
        })

        trial_admin_user_id = str(trial_admin_result.inserted_id)

        safe_insert_subscription(
            user_id=trial_admin_user_id,
            plan="starter",
            billing_cycle="trial",
            days=1,
            is_trial=True,
            payment_status="free",
            status_value="active"
        )

        new_session_token = secrets.token_hex(32)

        db.users.update_one(
            {"_id": oid(base_user_id)},
            {
                "$set": {
                    "trial_used": 1,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        db.users.update_one(
            {"_id": oid(trial_admin_user_id)},
            {
                "$set": {
                    "last_login": datetime.utcnow(),
                    "is_online": 1,
                    "active_session_token": new_session_token
                }
            }
        )

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
        flash(f"Could not start free trial: {str(e)}", "danger")
        return redirect(url_for("auth.pricing"))

    except Exception as e:
     flash(f"Could not start free trial: {str(e)}", "danger")
    return redirect(url_for("auth.pricing"))


# ------------------------------
# Paid Plan Form
# ------------------------------
@auth_bp.route("/subscription", methods=["GET", "POST"])
def subscription():

    # GET → form open
    if request.method == "GET":
        plan = request.args.get("plan", "starter")
        cycle = request.args.get("cycle", "monthly")

        return render_template(
            "subscription.html",
            selected_plan=plan,
            selected_cycle=cycle
        )

    db = get_db()

    company_name = request.form.get("company_name", "").strip()
    contact_person = request.form.get("contact_person", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    gst_number = request.form.get("gst_number", "").strip()
    address = request.form.get("address", "").strip()
    preferred_plan = request.form.get("preferred_plan", "").strip()
    billing_cycle = request.form.get("billing_cycle", "").strip()
    message = request.form.get("message", "").strip()

    payment_file = request.files.get("payment_screenshot")

    if not payment_file or payment_file.filename == "":
        flash("Upload payment screenshot", "danger")
        return redirect(request.url)

    upload_folder = os.path.join(
        current_app.root_path,
        "static",
        "uploads",
        "payment_screenshots"
    )
    os.makedirs(upload_folder, exist_ok=True)

    filename = secure_filename(payment_file.filename)
    unique_name = f"{secrets.token_hex(8)}_{filename}"

    payment_file.save(os.path.join(upload_folder, unique_name))

    db.subscription_enquiries.insert_one({
        "company_name": company_name,
        "contact_person": contact_person,
        "email": email,
        "phone": phone,
        "gst_number": gst_number,
        "address": address,
        "preferred_plan": preferred_plan,
        "billing_cycle": billing_cycle,
        "message": message,
        "payment_status": "pending",
        "status": "pending",
        "payment_screenshot": unique_name,
        "created_at": datetime.utcnow(),
        "is_deleted": 0
    })

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

    db = get_db()

    active_filter = {
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }

    try:
        total_companies = db.companies.count_documents(active_filter)

        active_companies = db.companies.count_documents({
            **active_filter,
            "status": "Active"
        })

        pending_enquiries = db.subscription_enquiries.count_documents({
            "$or": [
                {"status": "pending"},
                {"status": {"$exists": False}},
                {"status": None}
            ]
        })

        total_paid_subscriptions = db.subscriptions.count_documents({
            "status": "active",
            "payment_status": "paid",
            "end_date": {"$gt": datetime.utcnow()}
        })

        total_admins = db.users.count_documents({
            "role": "admin",
            **active_filter
        })

        converted_enquiries = db.subscription_enquiries.count_documents({
            "status": {"$in": ["approved", "converted"]}
        })

        total_trial_accounts = db.users.count_documents({
            "account_type": "trial",
            **active_filter
        })

        starter_count = db.subscriptions.count_documents({
            "plan": "starter",
            "status": "active",
            "end_date": {"$gt": datetime.utcnow()}
        })

        professional_count = db.subscriptions.count_documents({
            "plan": "professional",
            "status": "active",
            "end_date": {"$gt": datetime.utcnow()}
        })

        enterprise_count = db.subscriptions.count_documents({
            "plan": "enterprise",
            "status": "active",
            "end_date": {"$gt": datetime.utcnow()}
        })

    except Exception as e:
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

    db = get_db()

    rows = db.subscription_enquiries.find({
        "$or": [
            {"status": "pending"},
            {"status": {"$exists": False}},
            {"status": None}
        ]
    }).sort("_id", -1)

    enquiries = []

    for r in rows:
        enquiries.append((
            str(r.get("_id")),
            r.get("company_name", ""),
            r.get("contact_person", ""),
            r.get("email", ""),
            r.get("phone", ""),
            r.get("preferred_plan", ""),
            r.get("billing_cycle", ""),
            r.get("payment_screenshot", ""),
            r.get("payment_status", ""),
            r.get("status", "pending"),
            r.get("created_at")
        ))

    return render_template(
        "payment_review.html",
        enquiries=enquiries
    )



@auth_bp.route("/approve-enquiry/<enquiry_id>", methods=["POST"])
@login_required
def approve_enquiry(enquiry_id):

    if session.get("user_role") != "super_admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    db = get_db()

    try:

        db.subscription_enquiries.update_one(
            {"_id": oid(enquiry_id)},
            {
                "$set": {
                    "status": "approved",
                    "payment_status": "paid",
                    "updated_at": datetime.utcnow()
                }
            }
        )

        flash("Payment Approved!", "success")

    except Exception as e:

        flash(f"Failed to approve enquiry: {str(e)}", "danger")

    return redirect(url_for("auth.super_admin_payment_review"))

@auth_bp.route("/reject-enquiry/<enquiry_id>", methods=["POST"])
@login_required
def reject_enquiry(enquiry_id):

    if session.get("user_role") != "super_admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    db = get_db()

    try:

        db.subscription_enquiries.update_one(
            {"_id": oid(enquiry_id)},
            {
                "$set": {
                    "status": "rejected",
                    "updated_at": datetime.utcnow()
                }
            }
        )

        flash("Enquiry Rejected!", "danger")

    except Exception as e:

        flash(f"Failed to reject enquiry: {str(e)}", "danger")

    return redirect(url_for("auth.super_admin_payment_review"))

@auth_bp.route("/super-admin/dispatch")
@login_required
def super_admin_dispatch():

    if session.get("user_role") != "super_admin":
        return redirect(url_for("auth.login"))

    db = get_db()

    rows = db.subscription_enquiries.find({
        "status": "approved"
    }).sort("_id", -1)

    enquiries = []

    for r in rows:
        enquiries.append((
            str(r.get("_id")),
            r.get("company_name", ""),
            r.get("contact_person", ""),
            r.get("email", ""),
            r.get("phone", ""),
            r.get("preferred_plan", ""),
            r.get("billing_cycle", ""),
            r.get("payment_status", ""),
            r.get("status", ""),
            r.get("created_at")
        ))

    return render_template("dispatch.html", enquiries=enquiries)

@auth_bp.route("/send-credentials/<enquiry_id>", methods=["POST"])
@login_required
def send_credentials(enquiry_id):

    import random
    import string
    from werkzeug.security import generate_password_hash

    db = get_db()

    enquiry = db.subscription_enquiries.find_one({
        "_id": oid(enquiry_id)
    })

    if not enquiry:
        flash("Invalid request", "danger")
        return redirect(url_for("auth.super_admin_dispatch"))

    company_name = enquiry.get("company_name", "")
    name = enquiry.get("contact_person", "")
    email = enquiry.get("email", "").strip().lower()

    company = db.companies.find_one({
        "name": company_name
    })

    if not company:
        flash("Company not found! Pehle company create karo.", "danger")
        return redirect(url_for("auth.super_admin_dispatch"))

    company_id = str(company["_id"])

    existing_admin = db.users.find_one({
        "email": email,
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    })

    if existing_admin:
        flash("Admin already exists with this email.", "warning")
        return redirect(url_for("auth.super_admin_dispatch"))

    password = ''.join(
        random.choices(
            string.ascii_letters + string.digits,
            k=8
        )
    )

    hashed_password = generate_password_hash(password)

    user_result = db.users.insert_one({
        "name": name,
        "email": email,
        "password": hashed_password,
        "role": "admin",
        "company_id": company_id,
        "account_type": "paid",
        "is_deleted": 0,
        "is_online": 0,
        "created_at": datetime.utcnow()
    })

    admin_user_id = str(user_result.inserted_id)

    db.subscription_enquiries.update_one(
        {"_id": oid(enquiry_id)},
        {
            "$set": {
                "status": "converted",
                "converted_company_id": company_id,
                "converted_admin_user_id": admin_user_id,
                "converted_at": datetime.utcnow()
            }
        }
    )

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


@auth_bp.route("/mark-as-paid/<enquiry_id>", methods=["POST"])
@login_required
def mark_as_paid(enquiry_id):

    if session.get("user_role") != "super_admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    db = get_db()

    try:

        db.subscription_enquiries.update_one(
            {"_id": oid(enquiry_id)},
            {
                "$set": {
                    "payment_status": "paid",
                    "updated_at": datetime.utcnow()
                }
            }
        )

        flash(
            "Payment marked as paid. You can now approve and convert.",
            "success"
        )

    except Exception as e:

        flash(f"Failed to mark as paid: {str(e)}", "danger")

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

    db = get_db()

    rows = db.subscription_enquiries.find({}).sort("_id", -1)

    enquiries = []

    for r in rows:

        enquiries.append({
            "id": str(r.get("_id")),
            "company_name": r.get("company_name", ""),
            "contact_person": r.get("contact_person", ""),
            "email": r.get("email", ""),
            "phone": r.get("phone", ""),
            "preferred_plan": r.get("preferred_plan", ""),
            "billing_cycle": r.get("billing_cycle", ""),
            "gst_number": r.get("gst_number", ""),
            "referral_code": r.get("referral_code", ""),
            "message": r.get("message", ""),
            "payment_screenshot": r.get("payment_screenshot", ""),
            "payment_status": r.get("payment_status", ""),
            "status": r.get("status", "pending"),
            "created_at": r.get("created_at")
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

    db = get_db()

    rows = db.subscription_enquiries.find({}).sort("_id", -1)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID",
        "Company Name",
        "Contact Person",
        "Email",
        "Phone",
        "GST Number",
        "Address",
        "Preferred Plan",
        "Billing Cycle",
        "Message",
        "Referral Code",
        "Payment Status",
        "Payment ID",
        "Order ID",
        "Status",
        "Created At"
    ])

    for row in rows:
        writer.writerow([
            str(row.get("_id", "")),
            row.get("company_name", ""),
            row.get("contact_person", ""),
            row.get("email", ""),
            row.get("phone", ""),
            row.get("gst_number", ""),
            row.get("address", ""),
            row.get("preferred_plan", ""),
            row.get("billing_cycle", ""),
            row.get("message", ""),
            row.get("referral_code", ""),
            row.get("payment_status", ""),
            row.get("payment_id", ""),
            row.get("order_id", ""),
            row.get("status", ""),
            row.get("created_at", "")
        ])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=subscription_enquiries.csv"
        }
    )



@auth_bp.route("/")
def coupon_home():
    return render_template("home.html")
# ------------------------------
# Super Admin - Convert paid enquiry into real company admin
# ------------------------------
@auth_bp.route("/super-admin/subscription-enquiries/convert/<enquiry_id>", methods=["POST"])
@login_required
@role_required("super_admin")
def convert_subscription_enquiry(enquiry_id):

    db = get_db()

    try:
        enquiry = db.subscription_enquiries.find_one({
            "_id": oid(enquiry_id)
        })

        if not enquiry:
            flash("Enquiry not found.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        company_name = enquiry.get("company_name", "").strip()
        contact_person = enquiry.get("contact_person", "").strip()
        email = enquiry.get("email", "").strip().lower()
        phone = enquiry.get("phone", "").strip()
        preferred_plan = enquiry.get("preferred_plan", "starter")
        billing_cycle = (enquiry.get("billing_cycle") or "monthly").strip().lower()
        payment_status = (enquiry.get("payment_status") or "paid").strip().lower()
        status = (enquiry.get("status") or "pending").strip().lower()

        if payment_status not in ["paid", ""]:
            flash("This enquiry is not marked as paid.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        if status == "converted":
            flash("This enquiry is already converted.", "warning")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        company_result = db.companies.insert_one({
            "name": company_name,
            "status": "Active",
            "is_deleted": 0,
            "created_at": datetime.utcnow()
        })

        company_id = str(company_result.inserted_id)

        temp_password = generate_temp_password(8)
        hashed_password = generate_password_hash(temp_password)

        admin_result = db.users.insert_one({
            "name": contact_person,
            "email": email,
            "phone": phone,
            "password": hashed_password,
            "role": "admin",
            "company_id": company_id,
            "is_online": 0,
            "is_deleted": 0,
            "trial_used": 1,
            "account_type": "paid",
            "created_at": datetime.utcnow()
        })

        admin_user_id = str(admin_result.inserted_id)

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

        db.subscription_enquiries.update_one(
            {"_id": oid(enquiry_id)},
            {
                "$set": {
                    "status": "converted",
                    "converted_company_id": company_id,
                    "converted_admin_user_id": admin_user_id,
                    "converted_at": datetime.utcnow()
                }
            }
        )

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

    db = get_db()

    company = request.form.get("company_name", "").strip()
    plan = request.form.get("plan", "").strip()

    if not company or not plan:
        flash("Company name and plan are required.", "danger")
        return redirect(url_for("auth.dashboard"))

    db.subscription_enquiries.insert_one({
        "company_name": company,
        "preferred_plan": plan,
        "payment_status": "paid",
        "status": "pending",
        "created_by": user_id,
        "created_at": datetime.utcnow(),
        "is_deleted": 0
    })

    flash("Plan request submitted!", "success")
    return redirect(url_for("auth.dashboard"))


@auth_bp.route("/convert/<id>")
def convert_user(id):

    db = get_db()

    enquiry = db.subscription_enquiries.find_one({
        "_id": oid(id)
    })

    if not enquiry:
        flash("Payment not verified!", "danger")
        return redirect(url_for("auth.super_admin_dashboard"))

    company_name = enquiry.get("company_name", "").strip()
    plan = enquiry.get("preferred_plan", "starter")
    payment_status = (enquiry.get("payment_status") or "paid").strip().lower()

    if payment_status not in ["paid", ""]:
        flash("Payment not verified!", "danger")
        return redirect(url_for("auth.super_admin_dashboard"))

    password = str(random.randint(100000, 999999))
    hashed_password = generate_password_hash(password)

    company_result = db.companies.insert_one({
        "name": company_name,
        "status": "Active",
        "is_deleted": 0,
        "created_at": datetime.utcnow()
    })

    company_id = str(company_result.inserted_id)

    user_result = db.users.insert_one({
        "email": "client@example.com",
        "password": hashed_password,
        "role": "admin",
        "company_id": company_id,
        "is_deleted": 0,
        "is_online": 0,
        "account_type": "paid",
        "created_at": datetime.utcnow()
    })

    user_id = str(user_result.inserted_id)

    safe_insert_subscription(
        user_id=user_id,
        plan=plan,
        billing_cycle="monthly",
        days=30,
        is_trial=False,
        payment_status="paid",
        status_value="active"
    )

    db.subscription_enquiries.update_one(
        {"_id": oid(id)},
        {
            "$set": {
                "status": "converted",
                "converted_company_id": company_id,
                "converted_admin_user_id": user_id,
                "converted_at": datetime.utcnow()
            }
        }
    )

    flash(f"User created. Password: {password}", "success")
    return redirect(url_for("auth.super_admin_dashboard"))


# ------------------------------
# Super Admin Analytics
# ------------------------------
@auth_bp.route("/super-admin/analytics")
@login_required
@role_required("super_admin")
def super_admin_analytics():

    db = get_db()

    active_filter = {
        "$or": [
            {"is_deleted": 0},
            {"is_deleted": False},
            {"is_deleted": {"$exists": False}},
            {"is_deleted": None}
        ]
    }

    total_companies = db.companies.count_documents(active_filter)

    online_company_ids = db.users.distinct(
        "company_id",
        {
            "is_online": 1,
            "company_id": {"$exists": True, "$ne": None},
            **active_filter
        }
    )

    active_companies = len(online_company_ids)

    inactive_companies = total_companies - active_companies

    total_admins = db.users.count_documents({
        "role": "admin",
        **active_filter
    })

    total_employees = db.users.count_documents({
        "role": {
            "$in": [
                "employee",
                "qr_employee",
                "sales"
            ]
        },
        **active_filter
    })

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

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not name or not email or not password:
            flash("Please fill all fields.", "danger")
            return redirect(url_for("auth.signup"))

        db = get_db()

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
            flash("Email already exists", "danger")
            return redirect(url_for("auth.signup"))

        db.users.insert_one({
            "name": name,
            "email": email,
            "password": generate_password_hash(password),
            "role": "user",
            "trial_used": 0,
            "is_deleted": 0,
            "is_online": 0,
            "account_type": "paid",
            "created_at": datetime.utcnow()
        })

        flash("Signup successful. Login now.", "success")
        return redirect(url_for("auth.login"))

    return render_template("signup.html")


@auth_bp.route("/start-trial")
def start_trial():

    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("auth.login"))

    db = get_db()

    user = db.users.find_one({
        "_id": oid(user_id)
    })

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("auth.login"))

    trial_used = int(user.get("trial_used") or 0)

    if trial_used == 1:
        flash("Free trial already used!", "warning")
        return redirect(url_for("auth.pricing"))

    db.users.update_one(
        {"_id": oid(user_id)},
        {
            "$set": {
                "trial_used": 1,
                "updated_at": datetime.utcnow()
            }
        }
    )

    safe_insert_subscription(
        user_id=user_id,
        plan="starter",
        billing_cycle="trial",
        days=1,
        is_trial=True,
        payment_status="free",
        status_value="active"
    )

    flash("24-hour free trial started!", "success")
    return redirect(url_for("auth.dashboard"))


@auth_bp.route("/create-company-from-enquiry", methods=["POST"])
@login_required
@role_required("super_admin")
def create_company_from_enquiry():

    import secrets
    from werkzeug.security import generate_password_hash

    db = get_db()

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

        enquiry = db.subscription_enquiries.find_one({
            "_id": oid(enquiry_id)
        })

        if not enquiry:
            flash("Enquiry not found.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        payment_status = (
            enquiry.get("payment_status", "pending")
        ).strip().lower()

        current_status = (
            enquiry.get("status", "pending")
        ).strip().lower()

        if payment_status != "paid":
            flash("Please mark payment as paid first.", "warning")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        if current_status == "converted":
            flash("This enquiry is already converted.", "warning")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        existing_user = db.users.find_one({
            "email": admin_email,
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing_user:
            flash("This email is already used by another active account.", "danger")
            return redirect(url_for("auth.super_admin_subscription_enquiries"))

        existing_company = db.companies.find_one({
            "name": {
                "$regex": f"^{company_name}$",
                "$options": "i"
            },
            "$or": [
                {"is_deleted": 0},
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}},
                {"is_deleted": None}
            ]
        })

        if existing_company:
            company_id = str(existing_company["_id"])
        else:
            company_result = db.companies.insert_one({
                "name": company_name,
                "status": "Active",
                "is_deleted": 0,
                "created_at": datetime.utcnow()
            })

            company_id = str(company_result.inserted_id)

        temp_password = secrets.token_urlsafe(8)
        hashed_password = generate_password_hash(temp_password)

        admin_result = db.users.insert_one({
            "name": admin_name,
            "email": admin_email,
            "phone": phone,
            "password": hashed_password,
            "role": "admin",
            "company_id": company_id,
            "account_type": "paid",
            "is_online": 0,
            "is_deleted": 0,
            "trial_used": 0,
            "created_at": datetime.utcnow()
        })

        admin_user_id = str(admin_result.inserted_id)

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

        db.subscription_enquiries.update_one(
            {"_id": oid(enquiry_id)},
            {
                "$set": {
                    "status": "converted",
                    "payment_status": "paid",
                    "converted_company_id": company_id,
                    "converted_admin_user_id": admin_user_id,
                    "converted_at": datetime.utcnow()
                }
            }
        )

        try:

            send_company_credentials_email(
                to_email=admin_email,
                contact_name=admin_name,
                company_name=company_name,
                login_email=admin_email,
                temp_password=temp_password
            )

            flash(
                "Company/Admin created and credentials emailed.",
                "success"
            )

        except Exception as mail_error:

            flash(
                f"Company/Admin created. Email failed. Temporary password: {temp_password}",
                "warning"
            )

            print("MAIL ERROR:", mail_error)

    except Exception as e:

        flash(f"Company creation failed: {str(e)}", "danger")

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

        db = get_db()

        try:
            db.users.update_one(
                {"_id": oid(session.get("user_id"))},
                {
                    "$set": {
                        "is_online": 0,
                        "updated_at": datetime.utcnow()
                    },
                    "$unset": {
                        "active_session_token": ""
                    }
                }
            )
        except Exception as e:
            print("LOGOUT ERROR:", str(e))

    session.clear()

    flash("Logged out successfully.", "success")
    return redirect(url_for("auth.login"))