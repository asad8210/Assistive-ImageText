import os
import logging
import time
import hashlib
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from PIL import Image
import pytesseract
from gtts import gTTS, gTTSError
from langdetect import detect, LangDetectException
from functools import lru_cache
import redis
from apscheduler.schedulers.background import BackgroundScheduler
import pyttsx3

app = Flask(__name__)

# Logging config
logging.basicConfig(level=logging.INFO, format='%(asctime)s|%(levelname)s|%(message)s')
logger = logging.getLogger(__name__)

# Directories setup
UPLOAD_FOLDER = 'static/uploads'
AUDIO_FOLDER = 'static/audio'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB limit

# Redis caching setup (optional)
redis_url = os.environ.get('REDIS_URL')
redis_client = None
if redis_url:
    try:
        redis_client = redis.from_url(redis_url, decode_responses=False)
        redis_client.ping()
        logger.info("Connected to Redis for caching")
    except redis.ConnectionError:
        logger.warning("Redis connection failed, caching disabled")
        redis_client = None
else:
    logger.info("No REDIS_URL provided, caching disabled")

# Language map for OCR and TTS
language_map = {
    'en': ('eng', 'en'),
    'hi': ('hin', 'hi'),
    'ta': ('tam', 'ta'),
    'es': ('spa', 'es')
}

# Braille character map for English and Hindi
braille_map = {
    'a': '⠁', 'b': '⠃', 'c': '⠉', 'd': '⠙', 'e': '⠑',
    'f': '⠋', 'g': '⠛', 'h': '⠓', 'i': '⠊', 'j': '⠚',
    'k': '⠅', 'l': '⠇', 'm': '⠍', 'n': '⠝', 'o': '⠕',
    'p': '⠏', 'q': '⠟', 'r': '⠗', 's': '⠎', 't': '⠞',
    'u': '⠥', 'v': '⠧', 'w': '⠺', 'x': '⠭', 'y': '⠽',
    'z': '⠵',
    ' ': ' ', '\n': '\n', ',': '⠂', '.': '⠲', '?': '⠦', '!': '⠖',

    # Hindi vowels, consonants, and other signs
    "अ": "⠁", "आ": "⠡", "इ": "⠊", "ई": "⠒", "उ": "⠥",
    "ऊ": "⠳", "ए": "⠑", "ऐ": "⠣", "ओ": "⠕", "औ": "⠷",
    "ऋ": "⠗", "क": "⠅", "ख": "⠩", "ग": "⠛", "घ": "⠣",
    "ङ": "⠻", "च": "⠉", "छ": "⠡", "ज": "⠚", "झ": "⠒",
    "ञ": "⠱", "ट": "⠞", "ठ": "⠾", "ड": "⠙", "ढ": "⠹",
    "ण": "⠻", "त": "⠞", "थ": "⠮", "द": "⠙", "ध": "⠹",
    "न": "⠝", "प": "⠏", "फ": "⠟", "ब": "⠃", "भ": "⠫",
    "म": "⠍", "य": "⠽", "र": "⠗", "ल": "⠇", "व": "⠧",
    "श": "⠱", "ष": "⠳", "स": "⠎", "ह": "⠓", "क्ष": "⠟",
    "ज्ञ": "⠻", "ड़": "⠚", "ढ़": "⠚", "फ़": "⠋", "ज़": "⠵",
    "ग्य": "⠛⠽", "त्र": "⠞⠗", "श्र": "⠱⠗",

    "ा": "⠡", "ि": "⠊", "ी": "⠒", "ु": "⠥", "ू": "⠳",
    "े": "⠑", "ै": "⠣", "ो": "⠕", "ौ": "⠷", "ृ": "⠗",

    "्": "⠄", "ं": "⠈", "ः": "⠘", "ँ": "⠨",

    "०": "⠚", "१": "⠁", "२": "⠃", "३": "⠉", "४": "⠙",
    "५": "⠑", "६": "⠋", "७": "⠛", "८": "⠓", "९": "⠊",

    "।": "⠲", ",": "⠂", "?": "⠦", "!": "⠖", "\"": "⠶",
    "'": "⠄", ";": "⠆", ":": "⠒", ".": "⠲", "-": "⠤",
    "(": "⠶", ")": "⠶", "/": "⠌",

    "A": "⠁", "B": "⠃", "C": "⠉", "D": "⠙", "E": "⠑",
    "F": "⠋", "G": "⠛", "H": "⠓", "I": "⠊", "J": "⠚",
    "K": "⠅", "L": "⠇", "M": "⠍", "N": "⠝", "O": "⠕",
    "P": "⠏", "Q": "⠟", "R": "⠗", "S": "⠎", "T": "⠞",
    "U": "⠥", "V": "⠧", "W": "⠺", "X": "⠭", "Y": "⠽", "Z": "⠵",
}

@lru_cache(maxsize=128)
def text_to_braille(text):
    return ''.join(braille_map.get(ch.lower(), ' ') for ch in text)

def save_tts_audio(text, lang, path, max_retries=3):
    # Use MD5 hash as cache key
    text_hash = hashlib.md5((text + lang).encode()).hexdigest()
    cache_key = f"tts:{text_hash}"

    # Try to serve from Redis cache
    if redis_client and redis_client.exists(cache_key):
        logger.info(f"Serving TTS from Redis cache: {cache_key}")
        audio_bytes = redis_client.get(cache_key)
        with open(path, 'wb') as f:
            f.write(audio_bytes)
        return

    retry_count = 0
    backoff = 1  # seconds
    while retry_count < max_retries:
        try:
            tts = gTTS(text=text, lang=lang)
            tts.save(path)
            if redis_client:
                with open(path, 'rb') as f:
                    redis_client.setex(cache_key, 3600, f.read())
            return
        except gTTSError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                logger.warning(f"TTS rate limit hit, retrying in {backoff}s...")
                time.sleep(backoff)
                backoff *= 2
                retry_count += 1
            else:
                logger.error(f"gTTS error: {str(e)}")
                break
        except Exception as e:
            logger.error(f"Unexpected TTS error: {str(e)}")
            break

    # Offline fallback using pyttsx3
    try:
        logger.info("Using offline TTS fallback (pyttsx3)")
        engine = pyttsx3.init()
        engine.save_to_file(text, path)
        engine.runAndWait()
        if redis_client:
            with open(path, 'rb') as f:
                redis_client.setex(cache_key, 3600, f.read())
    except Exception as e:
        logger.error(f"Offline TTS fallback failed: {str(e)}")
        raise ValueError("Failed to generate audio with both online and offline TTS")

def cleanup_files():
    now = time.time()
    for folder in [app.config['UPLOAD_FOLDER'], app.config['AUDIO_FOLDER']]:
        try:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                if os.path.getmtime(file_path) < now - 3600:  # older than 1 hour
                    os.remove(file_path)
                    logger.info(f"Deleted file: {file_path}")
        except Exception as e:
            logger.error(f"File deletion error: {str(e)}")

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_files, 'interval', hours=1)

if os.environ.get("FLASK_ENV") != "production":
    scheduler.start()

@app.errorhandler(413)
def too_large(e):
    return render_template('index.html', error="File too large, max 10MB"), 413

@app.errorhandler(500)
def internal_error(e):
    return render_template('index.html', error="Internal server error, please try again"), 500

@app.route('/health')
def health_check():
    return jsonify(status="healthy"), 200

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'image' not in request.files or request.files['image'].filename == '':
            return render_template('index.html', error="No image selected")

        file = request.files['image']
        if not file.content_type in ['image/jpeg', 'image/png']:
            return render_template('index.html', error="Invalid file type, use JPEG or PNG")

        filename = secure_filename(file.filename)
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(image_path)
        except Exception as e:
            logger.error(f"File save error: {str(e)}")
            return render_template('index.html', error="Failed to save image")

        try:
            img = Image.open(image_path).convert("RGB")
            text = pytesseract.image_to_string(img, lang='hin+eng+tam+spa')
            detected_lang = 'en'
            try:
                detected_lang = detect(text) if text.strip() else 'en'
            except LangDetectException as e:
                logger.warning(f"Language detection failed: {str(e)}")
                detected_lang = 'en'

            gtts_lang = language_map.get(detected_lang, ('eng', 'en'))[1]
        except Exception as e:
            logger.error(f"OCR or image processing error: {str(e)}")
            return render_template('index.html', error="Failed to process image text")

        try:
            braille_body = text_to_braille(text)
            braille_prefix = '⠰⠓ ' if detected_lang == 'hi' else '⠰⠑ '
            braille_text = braille_prefix + braille_body
        except Exception as e:
            logger.error(f"Braille generation error: {str(e)}")
            return render_template('index.html', error="Failed to generate Braille")

        audio_filename = filename.rsplit('.', 1)[0] + '.mp3'
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
        try:
            save_tts_audio(text, gtts_lang, audio_path)
        except ValueError as e:
            return render_template('index.html', error=str(e))

        return render_template('index.html',
                               original_image=f'uploads/{filename}',
                               extracted_text=text,
                               braille_text=braille_text,
                               audio_file=f'audio/{audio_filename}',
                               detected_lang=detected_lang)

    return render_template('index.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
