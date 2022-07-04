import base64
import io
import logging
import random
import string
from datetime import datetime
from io import BytesIO
import os
import shutil

import qrcode
from flask import Flask, redirect, url_for, request, render_template, send_from_directory, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from PIL import Image, ImageDraw
from cryptography.fernet import Fernet


app = Flask(__name__)
socketio = SocketIO(app)

sessions = []


class Session:
    def __init__(self, identifier, members=None, initial=False):
        self.identifier = identifier
        self.initial = initial
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
        cleanup_sessions()
            
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

    def get_initial_state(self):
        return self.initial

    def set_initial_state(self, initial):
        self.initial = initial

    def __repr__(self):
        return f'Identifier: {self.identifier}\n' \
               f'Initial: {self.initial}\n' \
               f'Members: {self.members}'


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
    return None


def get_count_of_users():
    counter = 0
    for session in sessions:
        counter += len(session.members)
    return counter


def cleanup_sessions():
    for session in sessions:
        logging.debug(f"Session found {session.get_identifier()}, members: {len(session.members)}")
        if len(session.members) == 0:
            session_folder = f"{files_path}/{session.get_identifier()}"
            if os.path.exists(session_folder):
                logging.debug("Folder exists, going to clean up.")
                for filename in os.listdir(session_folder):
                    file_path = os.path.join(session_folder, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    except Exception as e:
                        logging.error(f'Failed to delete {file_path}. Reason: {e}')
                shutil.rmtree(session_folder)
            else:
                logging.debug("Folder does not exist, nothing to do.")
            sessions.remove(session)
            logging.debug(f'Successfully removed session ({session}).')
            del session


def check_secret(secret, identifier, user_name):
    session = get_session_by_identifier(identifier)
    if secret == session.get_secret():
        return True
    else:
        logging.critical(f'The device ({user_name}) did provide a secret, but the secret does not match.')
        send_error(identifier)
        return False


def check_session_empty(identifier):
    session = get_session_by_identifier(identifier)
    return len(session.members.keys()) == 0


@app.route('/favicon.ico')
def fav():
    return app.send_static_file('favicon.png')


@app.route('/')
def main():
    return render_template('index.html')


@app.route('/new_session')
def new_session():
    cleanup_sessions()
    identifier = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(36))
    session = Session(identifier, initial=True)
    logging.debug("Created new session: ({}).".format(session.get_identifier()))
    return redirect(url_for('session_chat', identifier=identifier))


@app.route('/<identifier>')
def session_chat(identifier):
    secret = request.args.get('secret')
    if not secret:
        session = get_session_by_identifier(identifier)
        if session:
            if session.get_initial_state():
                secret = session.get_secret()
                session.add_qr(generate_qr(request.url, secret))
            else:
                if check_secret(secret, identifier, 'Unknown'):
                    return render_template("session.html", identifier=identifier)
                else:
                    return redirect(url_for('error'))
        else:
            return redirect(url_for('error'))
    else:
        if not check_secret(secret, identifier, 'Unknown'):
            return redirect(url_for('error'))

    return render_template("session.html", identifier=identifier)


@app.route('/<path:filepath>', methods=['GET'])
def download(filepath):
    filename = filepath.split('/')[1]
    fernet = Fernet(encryption_key)
    absolute_path = f"{files_path}/{filepath}"
    if os.path.exists(absolute_path):
        logging.debug(f"File requested: {filepath}")
        with open(absolute_path, 'rb') as enc_file:
            encrypted = enc_file.read()
        decrypted = fernet.decrypt(encrypted)
        return send_file(io.BytesIO(decrypted), download_name=filename, as_attachment=True)
    else:
        logging.error(f"File requested, but not found: {filepath}")
        return render_template('404.html'), 404


@app.route('/statistics', methods=['GET'])
def statistics():
    return {
        "sessions": len(sessions),
        "members": get_count_of_users()
    }


@app.route('/error', methods=['GET'])
def error():
    return render_template('error.html')


@app.errorhandler(404)
def page_not_found(e):
    logging.debug(f"404 - {e}")
    return render_template('404.html'), 404


@app.errorhandler(502)
def page_not_found(e):
    logging.debug(f"502 - {e}")
    return render_template('404.html'), 404


def send_error(identifier):
    time = datetime.now().strftime('%H:%M')
    message = {
        "message": 'User tried to join the session without the valid secret.',
        "time": time
    }
    socketio.emit('system', message, to=identifier)


@socketio.on('disconnect')
def disconnect():
    user_id = request.sid
    logging.debug(f"Received disconnect from {user_id}.")
    for room in rooms():
        leave_room(room)
    session = get_session_by_user_id(user_id)
    if session:
        username = session.get_user_name_by_user_id(user_id)
        identifier = session.get_identifier()
        logging.debug(f'Removed user ({username}) from session ({identifier}).')
        session.remove_member(user_id)
        time = datetime.now().strftime('%H:%M')
        message = {
            "message": f"{username} left the session.",
            "time": time
        }
        emit('system', message, to=identifier)


@socketio.on('init')
def joined(join):
    identifier = join['identifier']
    session = get_session_by_identifier(identifier)
    if not session:
        return
    user_id = request.sid
    user_name = join['user_name']
    messages = []
    if 'secret' not in join:
        if session.get_initial_state():
            logging.debug(f'The device ({user_name}) did not provide a secret, but the session is initializing.')
            messages.append({"secret": {"secret": f'{session.get_secret()}'}})
        else:
            logging.error(f'The device ({user_name}) did not provide any secret and '
                          f'the session is not in initial state anymore.')
            return
    else:
        secret = join['secret']
        if not check_secret(secret, identifier, user_name):
            return
        else:
            logging.debug(f'The device ({user_name}) provided a secret that matched.')

    session.add_member(user_id, user_name)
    join_room(identifier)
    logging.debug(f'Added member ({user_name}) to session ({session.get_identifier()}).')
    messages.append({"qrcode": {"qrcode": f'{session.get_qr()}'}})
    for message in messages:
        for key in message:
            emit(key, message[key], to=user_id)
            logging.debug(f'Sent message ({key}) to the device ({user_name}).')
    time = datetime.now().strftime('%H:%M')
    if not session.get_initial_state():
        message = {
            "message": f'New device ({user_name}) joined the room.',
            "time": time
        }
        emit('system', message, to=identifier)
        message = {
            "message": f'Current devices in the room: {session.get_members()}.',
            "time": time
        }
    else:
        message = {
            "message": f'New session for {user_name} created.',
            "time": time
        }
        session.set_initial_state(False)
    emit('system', message, to=identifier)


@socketio.on('message')
def handle_message(message):
    identifier = message['identifier']
    secret = message['secret']
    user_name = message['user_name']
    if not check_secret(secret, identifier, user_name):
        return
    if not identifier:
        return

    time = datetime.now().strftime('%H:%M')
    if "data" in message:
        file = message['data']
        filename = message['name']
        filepath = f"{files_path}/{identifier}"
        if not os.path.exists(filepath):
            os.makedirs(filepath)

        fernet = Fernet(encryption_key)
        out_file = open(f"{filepath}/{filename}", "wb")
        encrypted = fernet.encrypt(file)
        out_file.write(encrypted)
        out_file.close()
        response = {
            "user_name": user_name,
            "time": time,
            "message": filename
        }
        emit('upload', response, to=identifier)
    else:
        response = {
            "user_name": user_name,
            "time": time,
            "message": message['message']
        }
        emit('response', response, to=identifier)


@socketio.on('system_message')
def handle_system_message(message):
    identifier = message['identifier']
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
    dir_path = os.path.dirname(os.path.realpath(__file__))
    files_path = f'{dir_path}/uploads'
    if os.path.exists(files_path):
        shutil.rmtree(files_path)
    # Generate key and keep it only in memory
    encryption_key = Fernet.generate_key()
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)
    socketio.run(app, port=8080, host='0.0.0.0')
