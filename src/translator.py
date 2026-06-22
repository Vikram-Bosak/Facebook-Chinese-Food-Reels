"""
Chinese to English Video Translation Pipeline

Pipeline:
1. Extract audio from video (ffmpeg)
2. Transcribe Chinese audio → text (OpenAI Whisper)
3. Translate Chinese text → English (OpenAI GPT)
4. Generate English TTS audio (edge-tts)
5. Merge translated audio with original video
6. Generate SRT subtitles (Chinese + English)
"""

import os
import json
import subprocess
import tempfile
import asyncio
from pathlib import Path

try:
    from .logger import logger
except ImportError:
    from logger import logger


# ============================================================
# STEP 1: Extract Audio from Video
# ============================================================

def extract_audio(video_path, output_audio_path=None):
    """
    Extract audio track from video file using ffmpeg.
    Returns path to extracted audio file (WAV format for Whisper).
    """
    if output_audio_path is None:
        base = os.path.splitext(video_path)[0]
        output_audio_path = f"{base}_audio.wav"

    logger.info(f"Extracting audio from: {video_path}")

    try:
        # Extract audio as WAV (16kHz mono for best Whisper accuracy)
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vn',                    # No video
            '-acodec', 'pcm_s16le',  # 16-bit PCM
            '-ar', '16000',          # 16kHz sample rate
            '-ac', '1',              # Mono
            output_audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            logger.error(f"FFmpeg audio extraction failed: {result.stderr}")
            return None

        logger.info(f"Audio extracted successfully: {output_audio_path}")
        return output_audio_path

    except subprocess.TimeoutExpired:
        logger.error("FFmpeg audio extraction timed out")
        return None
    except FileNotFoundError:
        logger.error("FFmpeg not found. Please install FFmpeg.")
        return None
    except Exception as e:
        logger.error(f"Error extracting audio: {e}")
        return None


# ============================================================
# STEP 2: Transcribe Chinese Audio → Text (Whisper)
# ============================================================

def transcribe_chinese_audio(audio_path, use_api=True):
    """
    Transcribe Chinese audio to text with timestamps.

    Args:
        audio_path: Path to WAV audio file
        use_api: If True, use OpenAI Whisper API; if False, use local whisper

    Returns:
        List of segments: [{'start': float, 'end': float, 'text': str}, ...]
    """
    logger.info(f"Transcribing Chinese audio: {audio_path}")

    if use_api:
        return _transcribe_with_openai_api(audio_path)
    else:
        return _transcribe_with_local_whisper(audio_path)


def _transcribe_with_openai_api(audio_path):
    """Use OpenAI Whisper API for transcription."""
    try:
        from openai import OpenAI

        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY not found, falling back to local whisper")
            return _transcribe_with_local_whisper(audio_path)

        client = OpenAI(api_key=api_key)

        with open(audio_path, 'rb') as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="zh",
                response_format="verbose_json",
                timestamp_granularities=["segment"]
            )

        segments = []
        for seg in response.segments:
            segments.append({
                'start': seg['start'],
                'end': seg['end'],
                'text': seg['text'].strip()
            })

        logger.info(f"Transcribed {len(segments)} segments via OpenAI API")
        return segments

    except Exception as e:
        logger.error(f"OpenAI API transcription failed: {e}")
        return _transcribe_with_local_whisper(audio_path)


def _transcribe_with_local_whisper(audio_path):
    """Use local openai-whisper package for transcription."""
    try:
        import whisper

        logger.info("Loading local Whisper model (base)...")
        model = whisper.load_model("base")

        result = model.transcribe(
            audio_path,
            language="zh",
            task="transcribe",
            verbose=False
        )

        segments = []
        for seg in result.get('segments', []):
            segments.append({
                'start': seg['start'],
                'end': seg['end'],
                'text': seg['text'].strip()
            })

        logger.info(f"Transcribed {len(segments)} segments locally")
        return segments

    except ImportError:
        logger.error("whisper package not installed. Run: pip install openai-whisper")
        return []
    except Exception as e:
        logger.error(f"Local Whisper transcription failed: {e}")
        return []


# ============================================================
# STEP 3: Translate Chinese Text → English (OpenAI GPT)
# ============================================================

def translate_segments_to_english(segments):
    """
    Translate Chinese text segments to English using OpenAI GPT.

    Args:
        segments: List of {'start': float, 'end': float, 'text': str}

    Returns:
        List of {'start': float, 'end': float, 'chinese': str, 'english': str}
    """
    if not segments:
        return []

    logger.info(f"Translating {len(segments)} segments to English...")

    # Combine segments into batches for efficient translation
    # (reduce API calls by batching nearby segments)
    batches = _create_translation_batches(segments, max_chars=2000)

    translated_segments = []

    for batch in batches:
        batch_texts = [s['text'] for s in batch]
        batch_translations = _translate_batch(batch_texts)

        for i, seg in enumerate(batch):
            english_text = batch_translations[i] if i < len(batch_translations) else seg['text']
            translated_segments.append({
                'start': seg['start'],
                'end': seg['end'],
                'chinese': seg['text'],
                'english': english_text
            })

    logger.info(f"Translated {len(translated_segments)} segments")
    return translated_segments


def _create_translation_batches(segments, max_chars=2000):
    """Group segments into batches for efficient API calls."""
    batches = []
    current_batch = []
    current_chars = 0

    for seg in segments:
        seg_chars = len(seg['text'])
        if current_chars + seg_chars > max_chars and current_batch:
            batches.append(current_batch)
            current_batch = [seg]
            current_chars = seg_chars
        else:
            current_batch.append(seg)
            current_chars += seg_chars

    if current_batch:
        batches.append(current_batch)

    return batches


def _translate_batch(texts):
    """Translate a batch of Chinese texts to English using OpenAI."""
    try:
        from openai import OpenAI

        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY not found, returning original texts")
            return texts

        base_url = os.environ.get('OPENAI_API_BASE_URL')
        model = os.environ.get('OPENAI_API_MODEL', 'gpt-3.5-turbo')

        if base_url:
            client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            client = OpenAI(api_key=api_key)

        # Number each text for easy parsing
        numbered_texts = "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])

        system_prompt = (
            "You are a professional Chinese to English translator. "
            "Translate the following Chinese text segments into natural, fluent English. "
            "Keep translations concise and suitable for social media subtitles. "
            "Maintain the emotional tone and meaning. "
            "Return ONLY the translations, one per line, numbered to match the input."
        )

        user_prompt = f"Translate these Chinese segments to English:\n\n{numbered_texts}"

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )

        result = response.choices[0].message.content.strip()

        # Parse numbered translations
        translations = []
        for line in result.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Remove numbering (e.g., "1. " or "1)")
            import re
            cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
            if cleaned:
                translations.append(cleaned)

        # Ensure we have the right number of translations
        while len(translations) < len(texts):
            translations.append(texts[len(translations)])  # Fallback to Chinese

        return translations[:len(texts)]

    except Exception as e:
        logger.error(f"Translation API error: {e}")
        return texts  # Return original Chinese on failure


# ============================================================
# STEP 4: Generate English TTS Audio (edge-tts)
# ============================================================

def generate_english_tts(segments, output_audio_path=None):
    """
    Generate English TTS audio from translated segments using edge-tts.

    Args:
        segments: List of {'start': float, 'end': float, 'english': str}

    Returns:
        Path to generated TTS audio file (MP3)
    """
    if not segments:
        return None

    if output_audio_path is None:
        output_audio_path = os.path.join(tempfile.gettempdir(), "tts_output.mp3")

    logger.info(f"Generating English TTS for {len(segments)} segments...")

    try:
        import edge_tts
        import asyncio

        # Filter out empty segments
        valid_segments = [s for s in segments if s.get('english', '').strip()]

        if not valid_segments:
            logger.warning("No valid segments for TTS")
            return None

        # Create SRT content for TTS timing
        srt_content = _segments_to_srt(valid_segments)

        # Generate TTS using edge-tts
        voice = os.environ.get('TTS_VOICE', 'en-US-ChristopherNeural')

        asyncio.run(_generate_edge_tts(valid_segments, output_audio_path, voice))

        if os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0:
            logger.info(f"TTS audio generated: {output_audio_path}")
            return output_audio_path
        else:
            logger.error("TTS output file is empty or missing")
            return None

    except ImportError:
        logger.error("edge-tts not installed. Run: pip install edge-tts")
        return None
    except Exception as e:
        logger.error(f"TTS generation error: {e}")
        return None


async def _generate_edge_tts(segments, output_path, voice):
    """Generate TTS audio using edge-tts."""
    import edge_tts

    # Combine all English text with pauses
    full_text = ""
    for seg in segments:
        text = seg.get('english', '').strip()
        if text:
            full_text += text + ". "

    # Generate audio
    communicate = edge_tts.Communicate(full_text, voice)
    await communicate.save(output_path)


def _segments_to_srt(segments):
    """Convert segments to SRT subtitle format."""
    srt_lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_srt_time(seg['start'])
        end = _format_srt_time(seg['end'])
        text = seg.get('english', seg.get('text', ''))
        srt_lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(srt_lines)


def _format_srt_time(seconds):
    """Convert seconds to SRT time format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ============================================================
# STEP 5: Merge Translated Audio with Original Video
# ============================================================

def merge_audio_with_video(video_path, audio_path, output_path=None):
    """
    Replace original audio with translated English audio.

    Args:
        video_path: Original video file
        audio_path: New English TTS audio file
        output_path: Output video path

    Returns:
        Path to output video with English audio
    """
    if output_path is None:
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_english{ext}"

    logger.info(f"Merging translated audio with video...")

    try:
        # Get original video duration
        probe_cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'csv=p=0',
            video_path
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        original_duration = float(result.stdout.strip()) if result.stdout.strip() else 60

        # Merge: keep original video, replace audio, trim to original duration
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,      # Original video
            '-i', audio_path,      # New English audio
            '-c:v', 'copy',        # Copy video stream (no re-encode)
            '-c:a', 'aac',         # Encode audio as AAC
            '-b:a', '128k',        # Audio bitrate
            '-map', '0:v:0',       # Use video from first input
            '-map', '1:a:0',       # Use audio from second input
            '-shortest',           # Trim to shortest stream
            '-t', str(original_duration),  # Limit to original duration
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"FFmpeg merge failed: {result.stderr}")
            return None

        logger.info(f"Video with English audio created: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        return None


# ============================================================
# STEP 6: Generate Subtitle Files (SRT)
# ============================================================

def generate_subtitles(segments, output_dir=None, filename="subtitles"):
    """
    Generate SRT subtitle files for both Chinese and English.

    Args:
        segments: Translated segments with 'chinese' and 'english' keys
        output_dir: Directory for output files
        filename: Base filename (without extension)

    Returns:
        Dict with paths to generated SRT files
    """
    if output_dir is None:
        output_dir = tempfile.gettempdir()

    os.makedirs(output_dir, exist_ok=True)

    # Generate Chinese SRT
    zh_srt_path = os.path.join(output_dir, f"{filename}_chinese.srt")
    en_srt_path = os.path.join(output_dir, f"{filename}_english.srt")
    dual_srt_path = os.path.join(output_dir, f"{filename}_dual.srt")

    zh_lines = []
    en_lines = []
    dual_lines = []

    for i, seg in enumerate(segments, 1):
        start = _format_srt_time(seg['start'])
        end = _format_srt_time(seg['end'])
        zh_text = seg.get('chinese', '')
        en_text = seg.get('english', '')

        zh_lines.append(f"{i}\n{start} --> {end}\n{zh_text}\n")
        en_lines.append(f"{i}\n{start} --> {end}\n{en_text}\n")
        dual_lines.append(f"{i}\n{start} --> {end}\n{zh_text}\n{en_text}\n")

    # Write SRT files
    with open(zh_srt_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(zh_lines))

    with open(en_srt_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(en_lines))

    with open(dual_srt_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(dual_lines))

    logger.info(f"Subtitle files generated: {zh_srt_path}, {en_srt_path}, {dual_srt_path}")

    return {
        'chinese': zh_srt_path,
        'english': en_srt_path,
        'dual': dual_srt_path
    }


def burn_subtitles_into_video(video_path, srt_path, output_path=None, language='english'):
    """
    Burn (hardcode) subtitles into the video.

    Args:
        video_path: Input video
        srt_path: SRT subtitle file
        output_path: Output video path
        language: 'english', 'chinese', or 'dual'

    Returns:
        Path to video with burned subtitles
    """
    if output_path is None:
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_subtitled{ext}"

    logger.info(f"Burning {language} subtitles into video...")

    try:
        # Subtitle style based on language
        if language == 'chinese':
            style = "FontName=Noto Sans SC,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,MarginV=60"
        elif language == 'dual':
            style = "FontName=Noto Sans SC,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,MarginV=50"
        else:  # english
            style = "FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,MarginV=60"

        # Escape path for FFmpeg subtitle filter
        escaped_srt = srt_path.replace('\\', '/').replace(':', '\\:')

        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-vf', f"subtitles='{escaped_srt}':force_style='{style}'",
            '-c:a', 'copy',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"Subtitle burn failed: {result.stderr}")
            return None

        logger.info(f"Video with burned subtitles: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Error burning subtitles: {e}")
        return None


# ============================================================
# MAIN TRANSLATION PIPELINE
# ============================================================

def translate_video(video_path, output_dir=None, burn_subtitles=True, subtitle_language='dual'):
    """
    Complete pipeline: Chinese video → English dubbed video with subtitles.

    Args:
        video_path: Path to Chinese video
        output_dir: Directory for output files (default: same as input)
        burn_subtitles: Whether to hardcode subtitles into video
        subtitle_language: 'english', 'chinese', or 'dual'

    Returns:
        Dict with paths to all generated files, or None on failure
    """
    logger.info(f"=== Starting Translation Pipeline ===")
    logger.info(f"Input video: {video_path}")

    if output_dir is None:
        output_dir = os.path.dirname(video_path) or '.'

    os.makedirs(output_dir, exist_ok=True)

    # Track all generated files for cleanup
    temp_files = []

    try:
        # Step 1: Extract audio
        logger.info("Step 1/6: Extracting audio...")
        audio_path = extract_audio(video_path)
        if not audio_path:
            raise Exception("Failed to extract audio from video")
        temp_files.append(audio_path)

        # Step 2: Transcribe Chinese
        logger.info("Step 2/6: Transcribing Chinese audio...")
        use_api = bool(os.environ.get('OPENAI_API_KEY'))
        segments = transcribe_chinese_audio(audio_path, use_api=use_api)
        if not segments:
            raise Exception("Failed to transcribe audio")
        logger.info(f"Transcribed {len(segments)} segments")

        # Step 3: Translate to English
        logger.info("Step 3/6: Translating to English...")
        translated = translate_segments_to_english(segments)
        if not translated:
            raise Exception("Failed to translate segments")

        # Step 4: Generate English TTS
        logger.info("Step 4/6: Generating English TTS...")
        tts_path = os.path.join(output_dir, "tts_english.mp3")
        tts_audio = generate_english_tts(translated, tts_path)
        if not tts_audio:
            raise Exception("Failed to generate TTS audio")
        temp_files.append(tts_audio)

        # Step 5: Merge audio
        logger.info("Step 5/6: Merging translated audio with video...")
        english_video = merge_audio_with_video(video_path, tts_audio, 
            os.path.join(output_dir, "video_english.mp4"))
        if not english_video:
            raise Exception("Failed to merge audio with video")
        temp_files.append(english_video)

        # Step 6: Generate subtitles
        logger.info("Step 6/6: Generating subtitles...")
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        srt_files = generate_subtitles(translated, output_dir, base_name)

        final_video = english_video

        # Optionally burn subtitles
        if burn_subtitles and srt_files.get(subtitle_language):
            subtitled_video = burn_subtitles_into_video(
                english_video, 
                srt_files[subtitle_language],
                os.path.join(output_dir, f"{base_name}_final.mp4"),
                language=subtitle_language
            )
            if subtitled_video:
                final_video = subtitled_video

        # Clean up temp files (keep final outputs)
        for f in temp_files:
            if f != final_video and os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass

        result = {
            'original': video_path,
            'english_video': final_video,
            'subtitles': srt_files,
            'segments': translated,
            'segment_count': len(translated)
        }

        logger.info(f"=== Translation Complete ===")
        logger.info(f"English video: {final_video}")
        logger.info(f"Subtitles: {srt_files}")

        return result

    except Exception as e:
        logger.error(f"Translation pipeline failed: {e}")

        # Cleanup on failure
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass

        return None


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python translator.py <video_path> [output_dir]")
        print("Example: python translator.py input_chinese.mp4 output/")
        sys.exit(1)

    video = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None

    result = translate_video(video, out_dir)

    if result:
        print(f"\n✅ Translation successful!")
        print(f"English video: {result['english_video']}")
        print(f"Subtitles: {result['subtitles']}")
        print(f"Segments translated: {result['segment_count']}")
    else:
        print("\n❌ Translation failed!")
        sys.exit(1)
