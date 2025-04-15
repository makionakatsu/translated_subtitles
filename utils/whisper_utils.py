import time
import logging # Import logging
from faster_whisper import WhisperModel

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# --- モデルキャッシュ辞書 ---
MODEL_CACHE = {}

# --- get_cached_model: モデルサイズ・デバイス・精度を指定して WhisperModel をキャッシュ経由で取得する ---
def get_cached_model(model_size="medium", device="cpu", compute_type="int8"):
    """Loads a WhisperModel from cache or downloads it."""
    cache_key = f"{model_size}_{device}_{compute_type}"
    if cache_key not in MODEL_CACHE:
        logger.info(f"Loading Whisper model: {model_size} (device={device}, compute={compute_type})")
        start_time = time.time()
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            elapsed = time.time() - start_time
            logger.info(f"Model loaded in {elapsed:.2f} seconds")
            MODEL_CACHE[cache_key] = model
        except Exception as e:
            logger.error(f"Failed to load Whisper model '{model_size}': {e}")
            # Re-raise the exception or return None to indicate failure
            raise # Or return None
    # Return the cached model, or the newly loaded one
    return MODEL_CACHE.get(cache_key) # Use .get for safety, though it should exist if no exception

# --- transcribe_with_faster_whisper: 音声ファイルを transcribe して segments と info を返す ---
def transcribe_with_faster_whisper(audio_file_path, model_size="medium", device="cpu", compute_type="int8", beam_size=5):
    """Transcribes an audio file using faster-whisper."""
    try:
        model = get_cached_model(model_size=model_size, device=device, compute_type=compute_type)
        if model is None:
             logger.error("Transcription failed: Model could not be loaded.")
             return None, None # Indicate failure

        logger.info(f"Starting transcription for {audio_file_path} with beam_size={beam_size}")
        start_time = time.time()
        # Add VAD filter? Example: segments, info = model.transcribe(audio, beam_size=5, vad_filter=True)
        segments_generator, info = model.transcribe(audio_file_path, beam_size=beam_size)
        
        # Consume the generator to get the list of segments
        # This is where potential errors during transcription might surface
        segments = list(segments_generator) 
        
        elapsed = time.time() - start_time
        logger.info(f"Transcription finished in {elapsed:.2f} seconds. Language: {info.language} (Prob: {info.language_probability:.2f})")
        return segments, info
        
    except Exception as e:
        logger.error(f"Error during transcription of {audio_file_path}: {e}")
        logger.exception("Detailed traceback for transcription error:") # この行を追加
        return None, None # Indicate failure
