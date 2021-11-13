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
            members = {}
        self.members = members
        sessions.append(self)

    def add_member(self, user_id, name):
        self.members[user_id] = name

    def remove_member(self, user_id):
        self.members.pop(user_id)
        if len(self.members) == 0:
            sessions.remove(self)
            
    def get_members():
        return ','.join(self.members)

    def get_identifier(self):
        return self.identifier

    def get_secret(self):
        return self.secret

    def __repr__(self):
        return "Identifier: {}\n" \
               "Secret: {}\n" \
               "Members: {}".format(self.identifier, self.secret, self.members)


def get_session_by_user_id(user_id):
    for session in sessions:
        for user_id_session in session.members.keys():
            if user_id_session == user_id:
                return session
    return None


def get_session_by_identifier(identifier):
    for session in sessions:
        if session.get_identifier() == identifier:
            return session
    return Session(identifier)


def cleanup_sessions():
    for session in sessions:
        if len(session.members) == 0:
            sessions.remove(session)


def check_secret(secret, identifier):
    session = get_session_by_identifier(identifier)
    if secret == session.get_secret():
        return True
    else:
        return False


@app.route('/')
def main():
    identifier = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(36))
    return redirect(url_for('session_chat', identifier=identifier))


@app.route('/s/<identifier>')
def session_chat(identifier):
    cleanup_sessions()
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
    session = get_session_by_user_id(user_id)
    if session:
        session.remove_member(user_id)


@socketio.on('init')
def joined(join):
    identifier = join['room']
    if not identifier:
        return
    secret = join['secret']
    user_id = request.sid
    user_name = join['user']
    if not check_secret(secret, identifier):
        message = {
            "message": "You tried to join a session without the correct secret. "
                       "A new session will be created for you in 5 seconds."
        }
        emit('error', message, to=user_id)
        time = datetime.now().strftime('%H:%M')
        message = {
            "message": "Device ({}) tried to join the room with a wrong password at {}. ".format(user_name, time)
        }
        emit('system', message, to=identifier)
        return
    session = get_session_by_identifier(identifier)
    session.add_member(user_id, user_name)
    join_room(identifier)
    time = datetime.now().strftime('%H:%M')
    message = {
        "message": "New device ({}) joined the room at {}.".format(user_name, time)
    }
    emit('system', message, to=identifier)
    room_devices = ", ".join(room for room in session.members.values())
    message = {
        "message": "Current devices in the room: {}.".format(room_devices)
    }
    emit('system', message, to=identifier)


@socketio.on('message')
def handle_message(message):
    identifier = message['room']
    secret = message['secret']
    if not check_secret(secret, identifier):
        return
    if not identifier:
        return
    time = datetime.now().strftime('%H:%M')
    response = {
        "time": time,
        "message": message['message']
    }
    emit('response', response, to=identifier)


@socketio.on('system_message')
def handle_system_message(message):
    identifier = message['room']
    secret = message['secret']
    if not check_secret(secret, identifier):
        return
    if not identifier:
        return
        
    if message['message'] == "/current":
        session = get_session_by_identifier(identifier)
        system_message = "Current members: {}.".format(session.get_members())
    else:
        system_message = "Not implemented yet."
    time = datetime.now().strftime('%H:%M')
    response = {
        "time": time,
        "message": message['message']
    }
    emit('response', response, to=identifier)
    response_system = {
        "time": time,
        "message": system_message
    }
    emit('response', response_system, to=identifier)


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
