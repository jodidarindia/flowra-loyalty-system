import os
MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PASSWORD = "@punit1280"
MYSQL_DB = "coupon_system"
SECRET_KEY = "flowra_super_secret_key"


RAZORPAY_KEY = os.getenv("RAZORPAY_KEY")
RAZORPAY_SECRET = os.getenv("RAZORPAY_SECRET")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")