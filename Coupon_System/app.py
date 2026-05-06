from flask import Flask, render_template, url_for, redirect, session
from flask_mail import Mail
from datetime import timedelta
from flask_mysqldb import MySQL
from datetime import timedelta
import config
from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp
from extensions import mail, csrf
from routes.admin_routes import admin_bp                                
from dotenv import load_dotenv

load_dotenv()
print(config.RAZORPAY_KEY)

app = Flask(__name__)


# ------------------------------
# Secret key / session config
# ------------------------------
app.secret_key = config.SECRET_KEY
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False   # True only on HTTPS/live server
csrf.init_app(app)



from extensions import mail, csrf, oauth

# ... existing config ...

mail.init_app(app)
csrf.init_app(app)
oauth.init_app(app)
mail = Mail()

app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = "pmadhav550@gmail.com"
app.config["MAIL_PASSWORD"] = "fuqmsnwozcvibwwm"
app.config["MAIL_DEFAULT_SENDER"] = "pmadhav550@gmail.com"

mail.init_app(app)
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
# Run app 
# ------------------------------
if __name__ == "__main__":
  app.run(
    host="0.0.0.0",
    port=5000,
    debug=True,
    ssl_context=("192.168.1.13+2.pem", "192.168.1.13+2-key.pem")
)