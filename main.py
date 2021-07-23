import base64
import random
import string
from datetime import datetime
from io import BytesIO

import qrcode
from flask import Flask, redirect, url_for, request, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from PIL import Image, ImageDraw


app = Flask(__name__)
socketio = SocketIO(app)


sessions = []


class Session:
    def __init__(self, identifier, members=None):
        self.identifier = identifier
        self.secret = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(36))
        if members is None:
            members = []
        self.members = members
        sessions.append(self)

    def add_member(self, member):
        self.members.append(member)

    def remove_member(self, member):
        self.members.remove(member)
        if len(self.members) == 0:
            sessions.remove(self)

    def get_identifier(self):
        return self.identifier

    def get_secret(self):
        return self.secret

    def __repr__(self):
        return "Identifier: {}\n" \
               "Secret: {}\n" \
               "Members: {}".format(self.identifier, self.secret, self.members)


def get_session_by_member(member):
    for session in sessions:
        for member_session in session.members:
            if member_session == member:
                return session
    return None


def get_session_by_identifier(identifier):
    for session in sessions:
        if session.get_identifier() == identifier:
            return session
    return Session(identifier)


@app.route('/')
def main():
    identifier = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(36))
    return redirect(url_for('session_chat', identifier=identifier))


@app.route('/s/<identifier>')
def session_chat(identifier):
    secret = request.args.get('secret')
    if not secret:
        session = Session(identifier)
        secret = session.get_secret()
    qr_code = generate_qr(request.url, secret)
    return render_template("session.html", qr_code=qr_code, room=identifier, secret=secret)


@socketio.on('disconnect')
def disconnect():
    user_id = request.sid
    for room in rooms():
        leave_room(room)
    session = get_session_by_member(user_id)
    if session:
        session.remove_member(user_id)


@socketio.on('init')
def joined(join):
    identifier = join['room']
    if not identifier:
        return
    secret = join['secret']
    session = get_session_by_identifier(identifier)
    user_id = request.sid
    if session.get_secret() != secret:
        message = {
            "message": "You tried to join a session without the correct secret. "
                       "A new session will be created for you in 5 seconds."
        }
        emit('error', message, to=user_id)
        time = datetime.now().strftime('%H:%M')
        message = {
            "time": time,
            "message": "Device ({}) tried to join the room with a wrong password at {}. ".format(join['user'], time)
        }
        emit('system', message, to=identifier)
        return
    session.add_member(user_id)
    join_room(identifier)
    time = datetime.now().strftime('%H:%M')
    response = {
        "time": time,
        "message": "New device ({}) joined the room at {}.".format(join['user'], time)
    }
    emit('system', response, to=identifier)


@socketio.on('message')
def write_to_site(message):
    identifier = message['room']
    if not identifier:
        return
    time = datetime.now().strftime('%H:%M')
    response = {
        "time": time,
        "message": message['message']
    }
    emit('response', response, to=identifier)


def generate_qr(url, secret):
    qr = qrcode.QRCode(
        version=1,
        box_size=12,
        border=0)
    qr.add_data(url + "?secret=" + secret)
    qr.make(fit=True)
    img = qr.make_image(fill_color='white', back_color="#222831")
    buffered_img = BytesIO()
    img.save(buffered_img, format="JPEG")
    encoded = base64.b64encode(buffered_img.getvalue())
    mime = "image/jpeg"
    uri = "data:%s;base64,%s" % (mime, encoded.decode())
    return uri


if __name__ == '__main__':
    socketio.run(app, port=8080, host='0.0.0.0')
