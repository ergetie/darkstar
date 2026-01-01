from flask_socketio import SocketIO

socketio = SocketIO(
    cors_allowed_origins="*", 
    async_mode='eventlet', 
    manage_session=False, 
    engineio_logger=False, 
    logger=False
)
