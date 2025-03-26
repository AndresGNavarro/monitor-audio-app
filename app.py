# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, join_room, leave_room, emit
import os
import time
import uuid
from werkzeug.utils import secure_filename
import threading

# Intenta importar pydub para compresión de audio
try:
    from pydub import AudioSegment
    AUDIO_COMPRESSION_AVAILABLE = True
except ImportError:
    AUDIO_COMPRESSION_AVAILABLE = False
    print("Pydub no está instalado. La compresión de audio no estará disponible.")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'clave-secreta-generada'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # Límite de 25MB para subidas

# Configuración optimizada de Socket.IO
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='eventlet',  # Usar eventlet para mejor rendimiento
    ping_timeout=60,
    ping_interval=25,       # Reducir intervalo de ping para mantener conexiones
    max_http_buffer_size=50 * 1024 * 1024  # Aumentar buffer para archivos grandes
)

# Asegurarse de que existe la carpeta de uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Almacenamiento de sesiones activas
sessions = {}

# Extensiones permitidas para archivos de audio
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'm4a', 'flac'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Función para comprimir audio
def compress_audio(file_path, output_path=None, quality=128):
    """
    Comprime un archivo de audio a MP3 con la calidad especificada
    
    Args:
        file_path (str): Ruta al archivo original
        output_path (str): Ruta para el archivo comprimido (opcional)
        quality (int): Bitrate en kbps
        
    Returns:
        str: Ruta al archivo comprimido
    """
    if not AUDIO_COMPRESSION_AVAILABLE:
        print("Compresión de audio no disponible")
        return file_path
        
    try:
        if output_path is None:
            # Conservar el nombre pero cambiar extensión
            base_dir = os.path.dirname(file_path)
            filename = os.path.basename(file_path)
            name, _ = os.path.splitext(filename)
            output_path = os.path.join(base_dir, f"{name}_compressed.mp3")
        
        # Cargar archivo con pydub
        audio = AudioSegment.from_file(file_path)
        
        # Exportar como MP3 con la calidad especificada
        audio.export(output_path, format="mp3", bitrate=f"{quality}k")
        
        print(f"Audio comprimido: {file_path} -> {output_path}")
        return output_path
    
    except Exception as e:
        print(f"Error al comprimir audio: {str(e)}")
        return file_path  # Devolver el original si falla

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

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

@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    sessions_list = []
    for session_id, data in sessions.items():
        sessions_list.append({
            'id': session_id,
            'name': data.get('session_name', 'Sesión sin nombre'),
            'created_at': data.get('created_at', 0),
            'users_count': len(data.get('users', [])),
            'has_track': data.get('track') is not None
        })
    
    # Ordenar por fecha de creación (más recientes primero)
    sessions_list.sort(key=lambda x: x['created_at'], reverse=True)
    
    return jsonify({'sessions': sessions_list})


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    access_code = request.json.get('access_code')
    
    # Verificar que la sesión existe
    if session_id not in sessions:
        return jsonify({'success': False, 'error': 'Sesión no encontrada'}), 404
    
    # Verificar el código de acceso (debe coincidir con el ID de sesión)
    if access_code != session_id:
        return jsonify({'success': False, 'error': 'Código de acceso incorrecto'}), 403
    
    # Eliminar la sesión
    del sessions[session_id]
    
    # Notificar a los clientes conectados
    socketio.emit('session_closed', {'message': 'Esta sesión ha sido cerrada por el administrador'}, to=session_id)
    
    return jsonify({'success': True})

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
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
        
        # Generar nombre de archivo único para evitar colisiones
        original_filename = secure_filename(file.filename)
        filename = f"{uuid.uuid4().hex}_{original_filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Guardar archivo
        file.save(file_path)
        
        # Procesar archivo en segundo plano para mejorar UX
        def process_audio_file():
            nonlocal file_path, filename
            # Comprimir archivo si es muy grande (más de 5MB y es WAV)
            if AUDIO_COMPRESSION_AVAILABLE and (
                file_path.endswith('.wav') or 
                os.path.getsize(file_path) > 5 * 1024 * 1024
            ):
                try:
                    compressed_path = compress_audio(file_path, quality=128)
                    if os.path.exists(compressed_path) and compressed_path != file_path:
                        # Actualizar ruta al archivo comprimido
                        filename = os.path.basename(compressed_path)
                        file_path = compressed_path
                except Exception as e:
                    print(f"Error al comprimir audio: {str(e)}")
        
        # Iniciar procesamiento en segundo plano
        threading.Thread(target=process_audio_file).start()
        
        # Ruta relativa para el navegador
        relative_path = os.path.join('static/uploads', filename).replace('\\', '/')
        
        # Actualizar información de la sesión
        sessions[session_id]['track'] = {
            'filename': original_filename,
            'path': f"/{relative_path}",
            'last_updated': time.time()  # Añadir timestamp para verificación
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

@app.route('/health')
def health_check():
    return jsonify({
        "status": "ok",
        "timestamp": time.time(),
        "active_sessions": len(sessions),
        "version": "1.0.1",
        "audio_compression_available": AUDIO_COMPRESSION_AVAILABLE
    })

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
    emit('server_status', {'status': 'connected', 'time': time.time()})

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
    try:
        session_id = data.get('session_id')
        username = data.get('username', 'Usuario')
        
        if session_id not in sessions:
            emit('error', {'message': 'Sesión no encontrada'})
            return
        
        join_room(session_id)
        print(f"Usuario {username} se unió a la sesión {session_id}")
        
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
            # Añadir timestamp fresco para evitar problemas de caché
            track_data = sessions[session_id]['track'].copy()
            track_data['refresh'] = int(time.time() * 1000)
            emit('track_updated', track_data)
    except Exception as e:
        print(f"Error en on_join: {str(e)}")
        emit('error', {'message': f'Error al unirse: {str(e)}'})

@socketio.on('playback_event')
def on_playback_event(data):
    try:
        session_id = data.get('session_id')
        action = data.get('action')  # 'play', 'pause', 'seek'
        position = data.get('position', 0)
        
        if session_id in sessions:
            # Añadir timestamp del servidor para ayudar en la sincronización
            data['server_timestamp'] = int(time.time() * 1000)
            emit('playback_update', data, to=session_id)
            
            # Log para depuración
            print(f"Evento de reproducción enviado: {action} en posición {position}")
    except Exception as e:
        print(f"Error en evento de reproducción: {str(e)}")

@socketio.on_error()
def error_handler(e):
    print(f"Socket.IO error: {str(e)}")

# Función para programar la limpieza periódica de sesiones
def schedule_cleanup():
    cleanup_sessions()
    # Programar próxima limpieza en 1 hora
    threading.Timer(3600, schedule_cleanup).start()

# Iniciar limpieza programada
schedule_cleanup()

# Configuración para producción
if __name__ == '__main__':
    # Obtener puerto del entorno (para Render.com)
    port = int(os.environ.get('PORT', 5000))
    
    # Intentar usar eventlet que es mejor para WebSockets
    try:
        import eventlet
        eventlet.monkey_patch()
        print(f"Iniciando servidor con eventlet en puerto {port}")
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
    except (ImportError, ModuleNotFoundError):
        # Fallback si eventlet no está disponible
        print(f"Eventlet no disponible, usando modo predeterminado en puerto {port}")
        socketio.run(app, host='0.0.0.0', port=port, debug=False)