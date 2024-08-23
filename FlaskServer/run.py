from FlaskServer import create_app
from flask_socketio import SocketIO, emit
import logging
from GlobalUtils.logger import logger, app_formatter

(sio, app) = create_app()

# SocketIO event handlers
@sio.on('connect')
def handle_connect():
    print('Client connected')
    emit('log', 'Connected to server')

@sio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@sio.on('log')
def handle_log(data):
    print(data)
    emit('log', data)

# Socket IO events
@sio.event
def log(data):
    """Emits log data to the client.
    Client should listen for 'log' event.
    Log data should be popped on LogsTable component in front-end.
    """
    emit('log', data)

# Custom handler for logging to the SocketIO
class SocketIOHandler(logging.Handler):
    def __init__(self, socketio):
        logging.Handler.__init__(self)
        self.socketio = socketio
    
    def emit(self, record):
        log_entry = self.format(record)
        self.socketio.emit('log', log_entry)

# Create and add SocketIOHandler to the logger
socketio_handler = SocketIOHandler(sio)
socketio_handler.setLevel(logging.INFO)
socketio_handler.setFormatter(app_formatter)
logger.addHandler(socketio_handler)


def run():
    sio.run(app)

if __name__ == "__main__":
    run()