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
    """Translate a batch of Chinese texts to English using OpenAI GPT (preferred) or free Google Translate fallback."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if api_key:
        try:
            from openai import OpenAI
            base_url = os.environ.get('OPENAI_API_BASE_URL')
            model = os.environ.get('OPENAI_API_MODEL', 'gpt-4o-mini')

            if base_url:
                client = OpenAI(api_key=api_key, base_url=base_url)
            else:
                client = OpenAI(api_key=api_key)

            numbered_texts = "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])

            system_prompt = (
                "You are an expert translator specializing in translating viral Chinese social media videos (reels/shorts) to English for a US audience. "
                "Translate the following segments into highly natural, engaging, and colloquial English. "
                "Preserve the emotional tone, humor, and drama of the original speaker. "
                "Ensure the translation is concise so that it can be spoken in a similar duration as the original Chinese segment. "
                "Return ONLY the translations, one per line, numbered to match the input format."
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

            import re
            translations = []
            for line in result.split('\n'):
                line = line.strip()
                if not line:
                    continue
                cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
                if cleaned:
                    translations.append(cleaned)

            while len(translations) < len(texts):
                translations.append(texts[len(translations)])

            logger.info(f"Translated {len(translations)} segments via OpenAI API")
            return translations[:len(texts)]
        except Exception as e:
            logger.error(f"OpenAI translation failed: {e}. Falling back to Google Translate.")

    # Fallback to Google Translate
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='zh-CN', target='en')
        translations = []
        for text in texts:
            if not text.strip():
                translations.append(text)
                continue
            try:
                translated = translator.translate(text)
                translations.append(translated if translated else text)
            except Exception as e:
                logger.warning(f"Translation failed for segment: {e}")
                translations.append(text)
        logger.info(f"Translated {len(translations)} segments via Google Translate (free)")
        return translations
    except ImportError:
        logger.error("deep-translator not installed. Run: pip install deep-translator")
        return texts
    except Exception as e:
        logger.error(f"Free translation error: {e}")
        return texts


# ============================================================
# STEP 4: Generate English TTS Audio (OpenAI TTS & Segment Alignment)
# ============================================================

def get_audio_duration(path):
    """Get the duration of an audio file using ffprobe."""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'csv=p=0',
            path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(res.stdout.strip())
    except Exception as e:
        logger.error(f"Error getting audio duration for {path}: {e}")
        return 0.0

_kokoro_instance = None

def get_kokoro():
    global _kokoro_instance
    if _kokoro_instance is None:
        try:
            import sys
            user_site = os.path.expanduser('~/.local/lib/python3.12/site-packages')
            if user_site not in sys.path:
                sys.path.append(user_site)
            from kokoro_onnx import Kokoro
            # Look in assets/kokoro relative to project root
            # Project root is parent of src directory
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, 'assets', 'kokoro', 'kokoro-v1.0.onnx')
            voices_path = os.path.join(base_dir, 'assets', 'kokoro', 'voices-v1.0.bin')
            if not os.path.exists(model_path):
                model_path = 'assets/kokoro/kokoro-v1.0.onnx'
                voices_path = 'assets/kokoro/voices-v1.0.bin'
                
            if os.path.exists(model_path) and os.path.exists(voices_path):
                logger.info(f"Initializing Kokoro ONNX model from {model_path}...")
                _kokoro_instance = Kokoro(model_path, voices_path)
            else:
                logger.warning(f"Kokoro model files not found at {model_path}. Fallback to edge-tts.")
        except Exception as e:
            logger.error(f"Failed to load Kokoro: {e}")
    return _kokoro_instance

def generate_segment_tts(text, voice, output_path):
    """Generate a single TTS audio chunk using Kokoro ONNX (free, natural, primary)
    or edge-tts (free fallback). OpenAI TTS is optional if OPENAI_API_KEY is set.

    Kokoro voices: af_sarah, af_bella, af_heart (female), bm_george (male),
                   am_michael, bf_emma, af_nicole, af_sky (more options).
    """
    # === PRIMARY: Kokoro ONNX (free, natural quality) ===
    try:
        kokoro = get_kokoro()
        if kokoro:
            # Voice mapping — Kokoro has rich voice options
            kokoro_voice = "af_heart"  # Default: most natural female voice ⭐⭐⭐⭐⭐
            voice_lower = voice.lower()
            if 'guy' in voice_lower or 'male' in voice_lower or 'christopher' in voice_lower or 'george' in voice_lower:
                kokoro_voice = "bm_george"    # Warm male voice
            elif 'michael' in voice_lower:
                kokoro_voice = "am_michael"   # Deep male voice
            elif 'bella' in voice_lower:
                kokoro_voice = "af_bella"     # Soft female
            elif 'heart' in voice_lower:
                kokoro_voice = "af_heart"     # Expressive female
            elif 'nicole' in voice_lower or 'emma' in voice_lower:
                kokoro_voice = "bf_emma"      # Clear female
            elif 'sky' in voice_lower:
                kokoro_voice = "af_sky"       # Youthful female
            elif voice.startswith("af_") or voice.startswith("am_") or voice.startswith("bf_") or voice.startswith("bm_"):
                kokoro_voice = voice

            samples, sample_rate = kokoro.create(text, voice=kokoro_voice, speed=0.95, lang="en-us")
            import soundfile as sf
            sf.write(output_path, samples, sample_rate)

            # Post-process: lowpass to soften digital artifacts
            try:
                temp_post = output_path + ".post.wav"
                subprocess.run([
                    'ffmpeg', '-y', '-i', output_path,
                    '-af', 'lowpass=f=15000',
                    temp_post
                ], capture_output=True, check=True)
                os.replace(temp_post, output_path)
            except Exception:
                pass  # Use unfiltered if post-process fails

            return True
    except Exception as e:
        logger.error(f"Kokoro TTS failed: {e}. Trying fallback...")

    # === FALLBACK 1: OpenAI TTS (only if API key is available) ===
    api_key = os.environ.get('OPENAI_API_KEY')
    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            openai_voice = 'echo'  # Warm, natural male
            voice_lower = voice.lower()
            if 'christopher' in voice_lower or 'guy' in voice_lower or 'eric' in voice_lower or 'male' in voice_lower:
                openai_voice = 'echo'
            elif 'samantha' in voice_lower or 'jenny' in voice_lower or 'aria' in voice_lower or 'female' in voice_lower:
                openai_voice = 'shimmer'
            elif voice in ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer']:
                openai_voice = voice

            response = client.audio.speech.create(
                model="tts-1-hd",
                voice=openai_voice,
                input=text
            )
            response.stream_to_file(output_path)
            return True
        except Exception as e:
            logger.error(f"OpenAI TTS failed: {e}.")

    # === FALLBACK 2: edge-tts (free, last resort) ===
    try:
        import edge_tts
        import asyncio
        asyncio.run(edge_tts.Communicate(text, voice).save(output_path))
        return True
    except Exception as e:
        logger.error(f"edge-tts failed for text '{text}': {e}")
        return False

def generate_english_tts(segments, output_audio_path=None, video_path=None):
    """
    Generate English TTS audio from translated segments and align them to the video timeline.
    Speed factor is adjusted dynamically per-segment to fit the original segment duration.
    """
    if not segments:
        return None

    if output_audio_path is None:
        output_audio_path = os.path.join(tempfile.gettempdir(), "tts_output.mp3")

    logger.info(f"Generating and aligning English TTS for {len(segments)} segments...")

    # Calculate total duration needed
    total_duration = 60.0
    if video_path:
        try:
            probe_cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'csv=p=0',
                video_path
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            total_duration = float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not read video duration: {e}. Defaulting to max segment end.")
            total_duration = max(s['end'] for s in segments) + 1.0
    else:
        total_duration = max(s['end'] for s in segments) + 1.0

    voice = os.environ.get('TTS_VOICE', 'en-US-ChristopherNeural')
    temp_dir = tempfile.gettempdir()
    
    # Step 1: Create silent base audio track
    silent_base = os.path.join(temp_dir, "silent_base.wav")
    try:
        subprocess.run([
            'ffmpeg', '-y', '-f', 'lavfi', 
            '-i', 'anullsrc=r=44100:cl=stereo', 
            '-t', str(total_duration), 
            silent_base
        ], capture_output=True, check=True)
    except Exception as e:
        logger.error(f"Failed to generate silent base audio: {e}")
        return None

    # Step 2: Generate and adjust each segment
    adjusted_segments = []
    inputs = ['-i', silent_base]
    filter_complex_parts = []
    
    # Create a short silence file for natural breathing pauses between segments
    silence_pad_path = os.path.join(temp_dir, "silence_pad_150ms.wav")
    try:
        subprocess.run([
            'ffmpeg', '-y', '-f', 'lavfi',
            '-i', 'anullsrc=r=44100:cl=stereo',
            '-t', '0.15',
            silence_pad_path
        ], capture_output=True, check=True)
    except Exception as e:
        logger.warning(f"Failed to create silence pad: {e}")
        silence_pad_path = None

    prev_seg_end = 0.0  # Track the end time of the previous segment

    for idx, seg in enumerate(segments):
        text = seg.get('english', '').strip()
        if not text:
            continue
        
        start = seg['start']
        end = seg['end']
        target_dur = end - start
        if target_dur <= 0:
            continue

        temp_seg_raw = os.path.join(temp_dir, f"seg_raw_{idx}.mp3")
        if generate_segment_tts(text, voice, temp_seg_raw):
            actual_dur = get_audio_duration(temp_seg_raw)
            if actual_dur <= 0:
                continue

            temp_seg_final = temp_seg_raw
            
            # If the generated speech is longer than the original segment duration, speed it up
            if actual_dur > target_dur:
                speed = actual_dur / target_dur
                logger.info(f"Segment {idx} is too slow ({actual_dur:.2f}s > {target_dur:.2f}s). Speeding up by {speed:.2f}x")
                
                # Cap speed at 1.35x to prevent robotic/unnatural audio
                speed = min(speed, 1.35)
                
                # Use chained atempo filters for smoother, more natural speed adjustment
                if speed <= 1.15:
                    # Single atempo for small speed changes
                    filters = [f"atempo={speed:.4f}"]
                elif speed <= 1.3:
                    # Two chained atempo filters for medium speed changes
                    step = speed ** 0.5  # sqrt for balanced chaining
                    filters = [f"atempo={step:.4f}", f"atempo={step:.4f}"]
                else:
                    # Three chained atempo filters for large speed changes
                    step = speed ** (1.0/3.0)  # cube root for balanced chaining
                    filters = [f"atempo={step:.4f}", f"atempo={step:.4f}", f"atempo={step:.4f}"]
                
                temp_seg_speed = os.path.join(temp_dir, f"seg_speed_{idx}.wav")
                try:
                    subprocess.run([
                        'ffmpeg', '-y', '-i', temp_seg_raw,
                        '-filter:a', ",".join(filters),
                        temp_seg_speed
                    ], capture_output=True, check=True)
                    temp_seg_final = temp_seg_speed
                except Exception as e:
                    logger.error(f"Failed to speed up segment {idx}: {e}")

            # Add natural silence gap if there's a gap between segments
            # This creates breathing pauses that make the dubbing sound more human
            gap = start - prev_seg_end
            if gap > 0.1 and silence_pad_path and os.path.exists(silence_pad_path):
                # Calculate silence duration: 50-150ms based on gap size
                silence_dur = min(0.15, max(0.05, gap * 0.3))
                temp_seg_padded = os.path.join(temp_dir, f"seg_padded_{idx}.wav")
                try:
                    subprocess.run([
                        'ffmpeg', '-y',
                        '-i', silence_pad_path,
                        '-i', temp_seg_final,
                        '-filter_complex',
                        f'[0:a]atrim=0:{silence_dur:.3f},asetpts=PTS-STARTPTS[sil];[sil][1:a]concat=n=2:v=0:a=1[out]',
                        '-map', '[out]',
                        temp_seg_padded
                    ], capture_output=True, check=True)
                    temp_seg_final = temp_seg_padded
                except Exception as e:
                    logger.warning(f"Failed to add silence gap for segment {idx}: {e}")

            # Update the end time of the previous segment
            prev_seg_end = end

            # Add to input list and prepare adelay filter
            input_idx = len(inputs) // 2  # This corresponds to the input index of this file in FFmpeg
            inputs.extend(['-i', temp_seg_final])
            
            delay_ms = int(start * 1000)
            # Use adelay filter for stereo audio (delaying both left and right channels)
            filter_complex_parts.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms}[a{input_idx}]")
            adjusted_segments.append(f"[a{input_idx}]")

    if not adjusted_segments:
        logger.warning("No valid TTS segments were generated.")
        return silent_base

    # Step 3: Mix all delayed segments together on top of the silent base
    mix_inputs = "".join(adjusted_segments)
    filter_graph = ";".join(filter_complex_parts)
    filter_graph += f";[0:a]{mix_inputs}amix=inputs={len(adjusted_segments)+1}:duration=first:dropout_transition=0:normalize=0[outa]"

    cmd = ['ffmpeg', '-y'] + inputs + [
        '-filter_complex', filter_graph,
        '-map', '[outa]',
        '-ar', '44100',
        '-ac', '2',
        output_audio_path
    ]

    try:
        logger.info("Mixing audio segments into final aligned audio track...")
        temp_raw_mix = os.path.join(temp_dir, "raw_mix.wav")
        subprocess.run(cmd + [temp_raw_mix], capture_output=True, check=True)

        # Step 4: Post-process the mixed audio for natural, human-like quality
        # - lowpass: soften any remaining digital/robotic artifacts
        # - loudnorm: normalize to professional broadcast loudness
        # - equalizer: slight presence boost at 3kHz for vocal clarity
        logger.info("Post-processing mixed audio for natural quality...")
        post_filters = "lowpass=f=14000,loudnorm=I=-16:TP=-1.5:LRA=11,equalizer=f=3000:t=q:w=1:g=1"
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', temp_raw_mix,
                '-af', post_filters,
                '-ar', '44100', '-ac', '2',
                output_audio_path
            ], capture_output=True, check=True)
            logger.info("Post-processing complete. Audio should sound natural and human-like.")
            return output_audio_path
        except subprocess.CalledProcessError as e:
            logger.warning(f"Post-processing failed, returning raw mix: {e}")
            import shutil
            shutil.copy2(temp_raw_mix, output_audio_path)
            return output_audio_path

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg mixing failed: {e.stderr.decode('utf-8', errors='ignore')}")
        return None


# ============================================================
# STEP 5: Merge Translated Audio with Original Video
# ============================================================

def separate_vocals(audio_path, output_dir):
    """
    Runs Demucs on the audio file to separate vocals from background music/effects.
    Returns path to the background (no vocals) audio file.
    """
    logger.info("Running Demucs vocal separator on audio...")
    try:
        import sys
        user_site = os.path.expanduser('~/.local/lib/python3.12/site-packages')
        if user_site not in sys.path:
            sys.path.append(user_site)
        
        # Run Demucs using the local CLI command directly
        demucs_executable = os.path.expanduser('~/.local/bin/demucs')
        if not os.path.exists(demucs_executable):
            demucs_executable = 'demucs' # Fallback to path
            
        cmd = [
            demucs_executable,
            '--two-stems=vocals',
            '-o', output_dir,
            audio_path
        ]
        
        logger.info(f"Executing: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.error(f"Demucs separation failed: {result.stderr}")
            return None
            
        base_name = os.path.splitext(os.path.basename(audio_path))[0]
        bg_audio_path = os.path.join(output_dir, 'htdemucs', base_name, 'no_vocals.wav')
        
        if os.path.exists(bg_audio_path):
            logger.info(f"Vocals successfully separated. Background audio: {bg_audio_path}")
            return bg_audio_path
        else:
            logger.error(f"Demucs finished but output file not found at: {bg_audio_path}")
            return None
            
    except Exception as e:
        logger.error(f"Error running Demucs separation: {e}")
        return None


def merge_audio_with_video(video_path, audio_path, bg_music_path=None, output_path=None):
    """
    Mix original background audio (with vocals removed) with translated English TTS voice.
    """
    if output_path is None:
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_english{ext}"

    logger.info(f"Merging translated audio with video...")

    try:
        if bg_music_path and os.path.exists(bg_music_path):
            logger.info("Mixing separated background music (no vocals) with English dubbed voice...")
            # We mix BGM (bg_music_path) at 90% volume and English voice (audio_path) at 100% volume
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-i', bg_music_path,
                '-i', audio_path,
                '-filter_complex', '[1:a]volume=0.9[bg];[2:a]volume=1.0[fg];[bg][fg]amix=inputs=2:duration=first:dropout_transition=0[outa]',
                '-map', '0:v:0',
                '-map', '[outa]',
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                output_path
            ]
        else:
            logger.info("No background music path provided. Mapping English voice directly.")
            # Discard the original background audio entirely
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-i', audio_path,
                '-map', '0:v:0',
                '-map', '1:a',
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                output_path
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"FFmpeg merge failed: {result.stderr}")
            return None

        logger.info(f"Video with mixed audio created: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        return None




# Template overlay system REMOVED — clean 9:16 fullscreen output only
# Old function overlay_on_template_3_4() was here — deleted per user request


def _format_srt_time(seconds):
    """Convert seconds to SRT time format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

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
        # Clean 9:16 output — no template, standard margins
        margin_v = "20"
        margin_v_dual = "15"

        # Subtitle style based on language
        if language == 'chinese':
            style = f"FontName=Noto Sans SC,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,MarginV={margin_v}"
        elif language == 'dual':
            style = f"FontName=Noto Sans SC,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,MarginV={margin_v_dual}"
        else:  # english
            style = f"FontName=Arial,FontSize=12,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,MarginV={margin_v}"

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



def trim_video_to_59s(video_path, output_dir):
    """Bypassed: Returns the video path directly without trimming."""
    return video_path


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

    # Trim video to 59 seconds if needed
    original_video_path = video_path
    video_path = trim_video_to_59s(video_path, output_dir)

    # Track all generated files for cleanup
    temp_files = []
    if video_path != original_video_path:
        temp_files.append(video_path)

    try:
        # Step 1: Extract audio
        logger.info("Step 1/6: Extracting audio...")
        audio_path = extract_audio(video_path)
        if not audio_path:
            raise Exception("Failed to extract audio from video")
        temp_files.append(audio_path)

        # Separate vocals from BGM/effects using Demucs
        bg_music_path = separate_vocals(audio_path, output_dir)
        if bg_music_path:
            temp_files.append(bg_music_path)

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
        tts_audio = generate_english_tts(translated, tts_path, video_path=video_path)
        if not tts_audio:
            raise Exception("Failed to generate TTS audio")
        temp_files.append(tts_audio)

        # Step 5: Merge audio
        logger.info("Step 5/6: Merging translated audio with video...")
        english_video = merge_audio_with_video(video_path, tts_audio, bg_music_path=bg_music_path,
            output_path=os.path.join(output_dir, "video_english.mp4"))
        if not english_video:
            raise Exception("Failed to merge audio with video")
        temp_files.append(english_video)

        # Template overlay REMOVED — clean 9:16 fullscreen output only
        # Old code: overlay_on_template_3_4(english_video, template_video_path)

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
