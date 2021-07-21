import base64
import random
import string
from datetime import datetime
from io import BytesIO

import qrcode
from flask import Flask, redirect, url_for, request, render_template
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__, template_folder="templates")
socketio = SocketIO(app)


@app.route('/')
def main():
    identifier = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(36))
    return redirect(url_for('session_chat', identifier=identifier))


@app.route('/session/<identifier>')
def session_chat(identifier):
    qr_code = generate_qr(request.url)
    return render_template("session.html", qr_code=qr_code, identifier=identifier)


@socketio.on('init')
def joined(join):
    join_room(join['room'])
    time = datetime.now().strftime('%H:%M')
    response = {
        "time": time,
        "message": "New device ({}) joined the room at {}.".format(join['user'], time)
    }
    emit('joined', response, room=join['room'])


@socketio.on('message')
def write_to_site(message):
    time = datetime.now().strftime('%H:%M')
    response = {
        "time": time,
        "message": message['message']
    }
    emit('response', response, room=message['room'])


def generate_qr(url):
    qr = qrcode.QRCode(
        version=1,
        box_size=12,
        border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buffered_img = BytesIO()
    img.save(buffered_img, format="JPEG")
    encoded = base64.b64encode(buffered_img.getvalue())
    mime = "image/jpeg"
    uri = "data:%s;base64,%s" % (mime, encoded.decode())
    return uri


if __name__ == '__main__':
    socketio.run(app, port=8080, host='0.0.0.0')
