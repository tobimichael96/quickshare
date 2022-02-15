import base64
import logging
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
        self.qr_code = None
        sessions.append(self)

    def add_member(self, user_id, name):
        self.members[user_id] = name

    def add_qr(self, qr_code):
        self.qr_code = qr_code

    def remove_member(self, user_id):
        self.members.pop(user_id)
        if len(self.members) == 0:
            sessions.remove(self)
            
    def get_members(self):
        return ', '.join(self.members.values())

    def get_identifier(self):
        return self.identifier

    def get_secret(self):
        return self.secret

    def get_qr(self):
        return self.qr_code

    def get_user_name_by_user_id(self, user_id):
        return self.members[user_id]

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


def check_session_empty(identifier):
    session = get_session_by_identifier(identifier)
    return len(session.members.keys()) == 0


@app.route('/')
def main():
    identifier = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(36))
    return redirect(url_for('session_chat', identifier=identifier))


@app.route('/s/<identifier>')
def session_chat(identifier):
    cleanup_sessions()
    if not request.args.get('secret'):
        session = Session(identifier)
        secret = session.get_secret()
        session.add_qr(generate_qr(request.url, secret))
        logging.debug("Created new session ({}).".format(session.get_identifier()))
    return render_template("session.html", room=identifier)


@socketio.on('disconnect')
def disconnect():
    user_id = request.sid
    for room in rooms():
        leave_room(room)
    session = get_session_by_user_id(user_id)
    if session:
        session.remove_member(user_id)
        logging.debug("Removed user ({}) from session ({}).".format(session.get_user_name_by_user_id(user_id), session.get_identifier()))


def send_error(user_id, identifier, user_name):
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


@socketio.on('init')
def joined(join):
    identifier = join['room']
    if not identifier:
        return
    user_id = request.sid
    user_name = join['user']
    session = get_session_by_identifier(identifier)
    messages = []
    if 'secret' in join:
        secret = join['secret']
        if not check_secret(secret, identifier):
            send_error(user_id, identifier, user_name)
            logging.error("The secret the device ({}) provided was not correct.".format(user_name))
            return
    else:
        if not check_session_empty(identifier):
            send_error(user_id, identifier, user_name)
            logging.error("The device ({}) did not provide any secret, but the session was not empty.".format(user_name))
            return
        else:
            logging.debug("The device ({}) did not provide a secret and the session was empty.".format(user_name))
            messages.append({"secret": {"secret": "{}".format(session.get_secret())}})
    session.add_member(user_id, user_name)
    join_room(identifier)
    logging.debug("Added member ({}) to session ({}).".format(session.get_members(), session.get_identifier()))
    messages.append({"qrcode": {"qrcode": "{}".format(session.get_qr())}})
    for message in messages:
        for key in message:
            emit(key, message[key], to=user_id)
            logging.debug("Sent message ({}) to the device ({}).".format(key, user_name))
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
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)
    socketio.run(app, port=8080, host='0.0.0.0')
