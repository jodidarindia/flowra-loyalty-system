from flask import Flask, redirect, url_for
from datetime import timedelta
from flask_mysqldb import MySQL
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
app.config["SESSION_COOKIE_SECURE"] = False

# ------------------------------
# Mail config
# ------------------------------
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = config.MAIL_USERNAME
app.config["MAIL_PASSWORD"] = config.MAIL_PASSWORD
app.config["MAIL_DEFAULT_SENDER"] = config.MAIL_USERNAME

# ------------------------------
# MySQL config
# ------------------------------
app.config["MYSQL_HOST"] = config.MYSQL_HOST
app.config["MYSQL_USER"] = config.MYSQL_USER
app.config["MYSQL_PASSWORD"] = config.MYSQL_PASSWORD
app.config["MYSQL_DB"] = config.MYSQL_DB

mysql = MySQL(app)
app.config["MYSQL_INSTANCE"] = mysql

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
# Mongo test route
# ------------------------------
@app.route("/mongo-test")
def mongo_test():

    mongo = app.config["MONGO_INSTANCE"]

    db = mongo.cx["flowra_db"]

    db.test.insert_one({
        "name": "FLOWRA",
        "status": "connected"
    })

    return "MongoDB Connected Successfully"

# ------------------------------
# Run app
# ------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        ssl_context=("192.168.1.13+2.pem", "192.168.1.13+2-key.pem")
    )