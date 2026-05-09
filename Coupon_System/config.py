import os
from dotenv import load_dotenv

load_dotenv()


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

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")



# ------------------------------
# Google OAuth
# ------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
