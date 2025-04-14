import os
import deepl
import google.generativeai as genai
import logging
from time import sleep

logger = logging.getLogger(__name__)

# Language code mapping (Whisper to DeepL/Gemini)
# Add more mappings as needed
LANG_MAP_DEEPL = {
    "en": "EN", "ja": "JA", "zh": "ZH", "es": "ES", "fr": "FR", "de": "DE", # Add more
    # Note: DeepL uses slightly different codes for PT, etc. Check DeepL docs.
    "pt": "PT-PT", # Example: Defaulting to Portuguese (Portugal)
}
LANG_MAP_GEMINI = { # Gemini generally understands full language names or ISO codes
    "en": "English", "ja": "Japanese", "zh": "Chinese", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese",
}

TARGET_LANG_MAP_DEEPL = {
    "日本語": "JA", "英語": "EN-US", # Use EN-US for more common English variant
}
TARGET_LANG_MAP_GEMINI = {
    "日本語": "Japanese", "英語": "English",
}

# Updated signature to accept deepl_api_key
def translate_text_deepl(text, source_lang_whisper, target_lang_ui, deepl_api_key=None):
    """Translates text using DeepL API, accepting API key as argument."""
    if not deepl_api_key:
        logger.error("DeepL API key was not provided to translate_text_deepl.")
        return None, "DeepL API key not provided"
    if not text:
        return "", None # Return empty string for empty input

    # Configure DeepL client locally within the function
    try:
        local_deepl_translator = deepl.Translator(deepl_api_key)
    except Exception as e:
        logger.error(f"Failed to configure DeepL Translator with provided key: {e}")
        return None, f"DeepL configuration failed: {e}"


    source_lang_deepl = LANG_MAP_DEEPL.get(source_lang_whisper)
    target_lang_deepl = TARGET_LANG_MAP_DEEPL.get(target_lang_ui)

    if not source_lang_deepl:
        return None, f"DeepL does not support source language: {source_lang_whisper}"
    if not target_lang_deepl:
        return None, f"DeepL does not support target language: {target_lang_ui}"

    try:
        # Use the local translator instance
        result = local_deepl_translator.translate_text(
            text,
            source_lang=source_lang_deepl,
            target_lang=target_lang_deepl
        )
        logger.debug(f"DeepL translation successful for '{text[:20]}...'")
        return result.text, None
    except deepl.QuotaExceededException:
        logger.warning("DeepL API quota exceeded.")
        return None, "DeepL quota exceeded"
    except deepl.DeepLException as e:
        logger.error(f"DeepL API error: {e}")
        return None, f"DeepL API error: {e}"
    except Exception as e:
        logger.error(f"Unexpected error during DeepL translation: {e}")
        return None, f"Unexpected DeepL error: {e}"

# Updated signature to accept gemini_api_key
def translate_text_gemini(text, source_lang_whisper, target_lang_ui, gemini_api_key=None):
    """Translates text using Google Gemini API, accepting API key as argument."""
    if not gemini_api_key:
        logger.error("Gemini API key was not provided to translate_text_gemini.")
        return None, "Gemini API key not provided"
    if not text:
        return "", None # Return empty string for empty input

    # Configure Gemini client locally within the function
    try:
        genai.configure(api_key=gemini_api_key)
        local_gemini_model = genai.GenerativeModel('gemini-1.5-flash') # Or another suitable model
    except Exception as e:
        logger.error(f"Failed to configure Gemini API with provided key: {e}")
        return None, f"Gemini configuration failed: {e}"

    source_lang_gemini = LANG_MAP_GEMINI.get(source_lang_whisper, source_lang_whisper) # Fallback to original code
    target_lang_gemini = TARGET_LANG_MAP_GEMINI.get(target_lang_ui)

    if not target_lang_gemini:
         return None, f"Gemini does not support target language: {target_lang_ui}"

    prompt = f"Translate the following text from {source_lang_gemini} to {target_lang_gemini}. Output only the translated text, without any introductory phrases or explanations:\n\n{text}"

    try:
        # Add retry logic for potential API flakiness
        retries = 3
        delay = 1
        for i in range(retries):
            try:
                # Use the local model instance
                response = local_gemini_model.generate_content(prompt)
                # Accessing the text might differ based on Gemini API version/response structure
                # Check response object structure if errors occur
                translated_text = response.text.strip()
                logger.debug(f"Gemini translation successful for '{text[:20]}...'")
                return translated_text, None
            except Exception as e:
                 # Specific error handling for Gemini if available (e.g., rate limits, content filtering)
                 logger.warning(f"Gemini API attempt {i+1} failed: {e}")
                 if "rate limit" in str(e).lower() and i < retries - 1:
                     sleep(delay * (i + 1)) # Exponential backoff might be better
                     continue
                 elif i == retries - 1: # Last retry failed
                     raise e # Re-raise the last exception
                 else:
                     sleep(delay) # Simple delay for other errors

    except Exception as e:
        logger.error(f"Gemini API error after retries: {e}")
        # Log the prompt for debugging if needed (be mindful of sensitive data)
        # logger.debug(f"Failed Gemini prompt: {prompt}")
        return None, f"Gemini API error: {e}"


# This function is kept for potential future use but is replaced by the new logic in main4.py
# def translate_segments(segments, source_language, target_language):
#     # Placeholder for the original function if needed,
#     # otherwise it can be removed.
#     logger.warning("translate_segments function called but is deprecated. Translation logic moved to main4.py")
#     return segments # Return original segments for now
