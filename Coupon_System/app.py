from flask import Flask, redirect, url_for
from datetime import timedelta

from flask_pymongo import PyMongo
from dotenv import load_dotenv

import config

from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp
from extensions import mail, csrf, oauth

load_dotenv()

app = Flask(__name__)

# ------------------------------
# Secret key / session config
# ------------------------------
app.secret_key = config.SECRET_KEY
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["WTF_CSRF_SSL_STRICT"] = False

# ------------------------------
# Mail config
# ------------------------------
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = config.MAIL_USERNAME
app.config["MAIL_PASSWORD"] = config.MAIL_PASSWORD
app.config["MAIL_DEFAULT_SENDER"] = config.MAIL_USERNAME
app.config["MAIL_TIMEOUT"] = 10



# ------------------------------
# MongoDB config
# ------------------------------
app.config["MONGO_URI"] = config.MONGO_URI

mongo = PyMongo(app)
app.config["MONGO_INSTANCE"] = mongo

# ------------------------------
# Extensions
# ------------------------------
mail.init_app(app)
csrf.init_app(app)
oauth.init_app(app)

# ------------------------------
# Blueprints
# ------------------------------
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)

# ------------------------------
# Home route
# ------------------------------
@app.route("/")
def home():
    return redirect(url_for("auth.login"))


# ------------------------------
# Disable browser cache
# ------------------------------
@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response





# ------------------------------
# Run app
# ------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        
    )