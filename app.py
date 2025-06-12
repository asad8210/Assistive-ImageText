import os
import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for
from werkzeug.utils import secure_filename
from PIL import Image
import pytesseract
from gtts import gTTS
from langdetect import detect, LangDetectException
from functools import lru_cache
import redis
from apscheduler.schedulers.background import BackgroundScheduler
import time
import hashlib

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s|%(levelname)s|%(message)s')
logger = logging.getLogger(__name__)

# Configure directories
UPLOAD_FOLDER = 'static/uploads'
AUDIO_FOLDER = 'static/audio'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB limit

# Redis for caching
redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
try:
    redis_client = redis.from_url(redis_url, decode_responses=True)
    redis_client.ping()
except redis.ConnectionError:
    logger.warning("Redis connection failed, caching disabled")
    redis_client = None

# Supported languages for OCR and TTS
language_map = {
    'en': ('eng', 'en'), 'hi': ('hin', 'hi'), 'ta': ('tam', 'ta'), 'es': ('spa', 'es')
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
    return ''.join(braille_map.get(ch, ' ') for ch in text)

def save_tts_audio(text, lang, path):
    text_hash = hashlib.md5((text + lang).encode()).hexdigest()
    cache_key = f"tts:{text_hash}"
    if redis_client and redis_client.exists(cache_key):
        logger.info("Serving TTS from cache: %s", cache_key)
        with open(path, 'wb') as f:
            f.write(redis_client.get(cache_key))
        return
    try:
        tts = gTTS(text=text, lang=lang)
        tts.save(path)
        if redis_client:
            with open(path, 'rb') as f:
                redis_client.setex(cache_key, 3600, f.read())
    except Exception as e:
        logger.error("TTS error: %s", str(e))
        raise ValueError("Failed to generate audio")

def cleanup_files():
    now = time.time()
    for folder in [app.config['UPLOAD_FOLDER'], app.config['AUDIO_FOLDER']]:
        try:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                if os.path.getmtime(file_path) < now - 3600:
                    os.remove(file_path)
                    logger.info("Deleted file: %s", file_path)
        except Exception as e:
            logger.error("File deletion error: %s", str(e))

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_files, 'interval', hours=1)

# Only start the scheduler in non-production environments to save memory
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
            logger.error("File save error: %s", str(e))
            return render_template('index.html', error="Failed to save image")

        try:
            img = Image.open(image_path).convert("RGB")
            detected_lang = 'en'
            try:
                text = pytesseract.image_to_string(img, lang='hin+eng+tam+spa')
                detected_lang = detect(text) if text.strip() else 'en'
            except (LangDetectException, pytesseract.TesseractError) as e:
                logger.error("OCR or langdetect error: %s", str(e))
                return render_template('index.html', error="Failed to process image text")

            gtts_lang = language_map.get(detected_lang, ('eng', 'en'))[1]
        except Exception as e:
            logger.error("Image processing error: %s", str(e))
            return render_template('index.html', error="Invalid image format")

        try:
            braille_body = text_to_braille(text)
            braille_prefix = '⠰⠓ ' if detected_lang == 'hi' else '⠰⠑ '
            braille_text = braille_prefix + braille_body
        except Exception as e:
            logger.error("Braille error: %s", str(e))
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
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
