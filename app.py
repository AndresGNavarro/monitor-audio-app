# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, join_room, leave_room, emit
import os
import time
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'clave-secreta-generada'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # Límite de 25MB para subidas
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60)

# Asegurarse de que existe la carpeta de uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Almacenamiento de sesiones activas
sessions = {}

# Extensiones permitidas para archivos de audio
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'm4a', 'flac'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/crear-sesion', methods=['GET', 'POST'])
def create_session():
    if request.method == 'POST':
        session_id = generate_session_id()
        creator_name = request.form.get('creator_name', 'Director')
        session_name = request.form.get('session_name', 'Sesión de audio')
        
        # Guardar información de la sesión
        sessions[session_id] = {
            'created_at': time.time(),
            'creator_name': creator_name,
            'session_name': session_name,
            'track': None,
            'users': []
        }
        
        return render_template('session.html', 
                               session_id=session_id, 
                               is_creator=True, 
                               creator_name=creator_name,
                               session_name=session_name)
    
    return render_template('create_session.html')

@app.route('/unirse-sesion', methods=['GET', 'POST'])
def join_session():
    error = None
    session_id = request.args.get('session_id', '')
    
    if request.method == 'POST':
        session_id = request.form.get('session_id')
        user_name = request.form.get('user_name', 'Músico')
        
        if session_id in sessions:
            # Sesión encontrada, unirse
            return render_template('session.html', 
                                   session_id=session_id, 
                                   is_creator=False,
                                   user_name=user_name,
                                   session_name=sessions[session_id].get('session_name', 'Sesión de audio'))
        else:
            # Sesión no encontrada
            error = "Código de sesión no válido. Verifica e intenta nuevamente."
    
    return render_template('join_session.html', error=error, session_id=session_id)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'audio_file' not in request.files:
        return jsonify({"error": "No se ha seleccionado ningún archivo"}), 400
    
    file = request.files['audio_file']
    session_id = request.form.get('session_id')
    
    if file.filename == '':
        return jsonify({"error": "No se ha seleccionado ningún archivo"}), 400
    
    if session_id not in sessions:
        return jsonify({"error": "Sesión no válida"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"error": "Tipo de archivo no permitido. Usa MP3, WAV, OGG, M4A o FLAC"}), 400
    
    try:
        # Generar nombre de archivo único para evitar colisiones
        original_filename = secure_filename(file.filename)
        filename = f"{uuid.uuid4().hex}_{original_filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Guardar archivo
        file.save(file_path)
        
        # Ruta relativa para el navegador
        relative_path = os.path.join('static/uploads', filename).replace('\\', '/')
        
        # Actualizar información de la sesión
        sessions[session_id]['track'] = {
            'filename': original_filename,
            'path': f"/{relative_path}"
        }
        
        # Notificar a todos los miembros de la sesión sobre la nueva pista
        socketio.emit('track_updated', sessions[session_id]['track'], to=session_id)
        
        return jsonify({
            "success": True, 
            "file_path": sessions[session_id]['track']['path'],
            "filename": original_filename
        })
    
    except Exception as e:
        print(f"Error al subir archivo: {str(e)}")
        return jsonify({"error": f"Error al procesar el archivo: {str(e)}"}), 500

@app.route('/server-time')
def get_server_time():
    return jsonify({"timestamp": int(time.time() * 1000)})

# Funciones de soporte
def generate_session_id():
    """Genera un ID de sesión único y fácil de compartir"""
    # Usar los primeros 6 caracteres de un UUID para crear un código corto
    return str(uuid.uuid4())[:6].upper()

# Limpiar sesiones antiguas periódicamente
def cleanup_sessions():
    """Elimina sesiones inactivas después de 24 horas"""
    now = time.time()
    for session_id in list(sessions.keys()):
        if now - sessions[session_id]['created_at'] > 86400:  # 24 horas
            del sessions[session_id]

# Socket.IO events
@socketio.on('connect')
def handle_connect():
    print(f"Cliente conectado: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Cliente desconectado: {request.sid}")
    # Buscar en qué sesión estaba este usuario
    for session_id, data in sessions.items():
        users = data['users']
        for i, user in enumerate(users):
            if user['id'] == request.sid:
                username = user['username']
                data['users'].pop(i)
                emit('user_left', {
                    'username': username,
                    'users': [u['username'] for u in data['users']]
                }, to=session_id)
                break

@socketio.on('join')
def on_join(data):
    session_id = data.get('session_id')
    username = data.get('username', 'Usuario')
    
    if session_id not in sessions:
        emit('error', {'message': 'Sesión no encontrada'})
        return
    
    join_room(session_id)
    
    # Agregar usuario a la lista de la sesión
    user_data = {
        'id': request.sid,
        'username': username
    }
    sessions[session_id]['users'].append(user_data)
    
    # Notificar a todos sobre el nuevo usuario
    user_list = [user['username'] for user in sessions[session_id]['users']]
    emit('user_joined', {
        'username': username,
        'users': user_list
    }, to=session_id)
    
    # Enviar información de la pista actual si existe
    if sessions[session_id]['track']:
        emit('track_updated', sessions[session_id]['track'])

@socketio.on('playback_event')
def on_playback_event(data):
    session_id = data.get('session_id')
    action = data.get('action')  # 'play', 'pause', 'seek'
    position = data.get('position', 0)
    
    if session_id in sessions:
        # Añadir timestamp del servidor para ayudar en la sincronización
        data['server_timestamp'] = int(time.time() * 1000)
        emit('playback_update', data, to=session_id)

# Configuración para producción
if __name__ == '__main__':
    # En entorno de desarrollo, activar depuración
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    
    print(f"Iniciando servidor en {host}:{port} (Debug: {debug_mode})")
    socketio.run(app, host=host, port=port, debug=debug_mode)