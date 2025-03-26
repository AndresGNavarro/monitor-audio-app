# Monitor de Audio Sincronizado

Aplicación web para la monitorización sincronizada de audio diseñada para sesiones colaborativas en tiempo real.

## Descripción

Esta aplicación permite a músicos y directores compartir y escuchar pistas de audio de manera sincronizada, facilitando ensayos o evaluaciones remotas de interpretaciones musicales.

## Características

- Sincronización temporal exacta entre dispositivos
- Soporte para múltiples formatos de audio (mp3, wav, ogg, m4a, flac)
- Interfaz moderna y responsiva
- Comunicación en tiempo real entre participantes
- Sesiones identificadas por códigos únicos fáciles de compartir

## Tecnologías utilizadas

- **Backend**: Flask (Python)
- **Frontend**: HTML, CSS, JavaScript
- **Comunicación en tiempo real**: Socket.IO
- **Diseño**: Bootstrap y FontAwesome

## Instalación

1. Clonar el repositorio
   ```
   git clone <url-del-repositorio>
   cd monitor-audio-app
   ```

2. Crear y activar entorno virtual
   ```
   python -m venv venv
   # En Windows
   venv\Scripts\activate
   # En Linux/Mac
   source venv/bin/activate
   ```

3. Instalar dependencias
   ```
   pip install -r requirements.txt
   ```

4. Ejecutar la aplicación
   ```
   python app.py
   ```

5. Acceder a la aplicación en `http://localhost:5000`

## Uso

1. **Como director**:
   - Crear una nueva sesión
   - Compartir el código de sesión con los participantes
   - Subir una pista de audio
   - Controlar la reproducción

2. **Como participante**:
   - Unirse a la sesión con el código proporcionado
   - Escuchar la pista sincronizada con los demás

## Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo LICENSE para más detalles. 