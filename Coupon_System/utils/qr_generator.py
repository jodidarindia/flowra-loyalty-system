import qrcode
import os


def generate_qr(data, filename):
    folder = "static/qrcodes"
    os.makedirs(folder, exist_ok=True)

    
    path = os.path.join(folder, filename)

    img = qrcode.make(data)
    img.save(path)

    return path