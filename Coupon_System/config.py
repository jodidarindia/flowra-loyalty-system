import os
from dotenv import load_dotenv

load_dotenv()

# ------------------------------
# MySQL Config
# ------------------------------
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "@punit1280")
MYSQL_DB = os.getenv("MYSQL_DB", "coupon_system")

# ------------------------------
# MongoDB Atlas Config
# ------------------------------
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://jodidarindia_db_user:oTTtFSOrJLz3DdTE@flowra-cluster.cxt8yw1.mongodb.net/flowra_db?retryWrites=true&w=majority&appName=flowra-cluster"
)

# ------------------------------
# Secret Key
# ------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "flowra_super_secret_key")

# ------------------------------
# Razorpay
# ------------------------------
RAZORPAY_KEY = os.getenv("RAZORPAY_KEY")
RAZORPAY_SECRET = os.getenv("RAZORPAY_SECRET")

# ------------------------------
# Google OAuth
# ------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# ------------------------------
# Mail
# ------------------------------
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")