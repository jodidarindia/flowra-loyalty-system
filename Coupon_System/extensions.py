from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect

mail = Mail()
csrf = CSRFProtect()
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from authlib.integrations.flask_client import OAuth

mail = Mail()
csrf = CSRFProtect()
oauth = OAuth()