"""
ElevenLabs Text-to-Speech service.
Génère un fichier audio MP3 et retourne l'URL publique pour Twilio.
"""
import os
import uuid
import hashlib
import httpx
from config import settings

# Cache: (text_hash, voice_id) → public_url — évite de re-générer les phrases répétées
_tts_cache: dict[tuple, str] = {}


def text_to_speech(text: str, voice_id: str = None) -> str:
    """
    Convertit le texte en audio via ElevenLabs.
    Retourne l'URL publique du fichier audio.
    voice_id : utilise la voix du business si fournie, sinon la voix globale.
    """
    vid = voice_id or settings.elevenlabs_voice_id

    # Retourne depuis le cache si l'audio existe déjà
    cache_key = (hashlib.md5(text.encode()).hexdigest(), vid)
    if cache_key in _tts_cache:
        cached_url = _tts_cache[cache_key]
        cached_path = os.path.join("static", "audio", cached_url.split("/")[-1])
        if os.path.exists(cached_path):
            return cached_url
        else:
            del _tts_cache[cache_key]

    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = os.path.join("static", "audio", filename)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "speed": 1.1,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
            "style": 0.2,
            "use_speaker_boost": True,
        },
    }

    with httpx.Client(timeout=30) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()

    with open(filepath, "wb") as f:
        f.write(response.content)

    public_url = f"{settings.base_url}/static/audio/{filename}"
    _tts_cache[cache_key] = public_url
    return public_url


def cleanup_old_audio(max_age_seconds: int = 3600):
    """Supprime les fichiers audio de plus d'une heure."""
    import time
    audio_dir = os.path.join("static", "audio")
    if not os.path.exists(audio_dir):
        return
    now = time.time()
    for fname in os.listdir(audio_dir):
        fpath = os.path.join(audio_dir, fname)
        if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > max_age_seconds:
            os.remove(fpath)
