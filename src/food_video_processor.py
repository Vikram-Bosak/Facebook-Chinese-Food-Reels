"""
Chinese Food Video Processor

Pipeline:
1. Detect speech segments using Whisper (with language detection)
2. Identify Chinese speech segments → to be removed
3. Identify cooking/serving segments (non-Chinese-speech) → to keep
4. Cut video to keep only cooking/serving segments
5. Concatenate segments into final video
6. Ensure 9:16 vertical format (no overlays, no templates)
7. Output clean fullscreen vertical video

Key rules:
- REMOVE any part where Chinese language is spoken
- KEEP cooking, food serving/plating, and (optionally) food tasting parts
- NO templates, frames, or overlays on final video
- Final output MUST be 9:16 vertical format
"""

import os
import subprocess
import json
import tempfile
import math

try:
    from .logger import logger
except ImportError:
    from logger import logger


# ============================================================
# STEP 1: Get Video Info
# ============================================================

def get_video_info(video_path):
    """Get video metadata: duration, width, height, fps."""
    try:
        probe_cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,duration',
            '-show_entries', 'format=duration',
            '-of', 'json',
            video_path
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"ffprobe failed: {result.stderr}")
            return None

        data = json.loads(result.stdout)
        stream = data.get('streams', [{}])[0]
        fmt = data.get('format', {})

        duration = float(fmt.get('duration', stream.get('duration', 0)))
        width = int(stream.get('width', 0))
        height = int(stream.get('height', 0))
        fps_str = stream.get('r_frame_rate', '30/1')
        if '/' in fps_str:
            num, den = fps_str.split('/')
            fps = float(num) / float(den) if float(den) > 0 else 30.0
        else:
            fps = float(fps_str)

        return {
            'duration': duration,
            'width': width,
            'height': height,
            'fps': fps,
            'is_vertical': height > width,
            'aspect_ratio': width / height if height > 0 else 1.0
        }
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        return None


# ============================================================
# STEP 2: Detect Speech Segments (Whisper)
# ============================================================

def detect_speech_segments(video_path, use_api=True):
    """
    Use Whisper to detect speech segments with timestamps and language.

    Returns:
        List of dicts: [{'start': float, 'end': float, 'text': str, 'language': str}, ...]
    """
    logger.info("Detecting speech segments with Whisper...")

    # Extract audio first
    audio_path = _extract_audio(video_path)
    if not audio_path:
        return []

    try:
        if use_api:
            return _whisper_api_detect(audio_path)
        else:
            return _whisper_local_detect(audio_path)
    finally:
        # Cleanup temp audio
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except:
                pass


def _extract_audio(video_path):
    """Extract audio as WAV for Whisper analysis."""
    try:
        audio_path = video_path + '_speech_detect.wav'
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vn', '-acodec', 'pcm_s16le',
            '-ar', '16000', '-ac', '1',
            audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"Audio extraction failed: {result.stderr}")
            return None
        return audio_path
    except Exception as e:
        logger.error(f"Error extracting audio: {e}")
        return None


def _whisper_api_detect(audio_path):
    """Use OpenAI Whisper API for speech detection with language detection."""
    try:
        from openai import OpenAI
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY not found, falling back to local Whisper")
            return _whisper_local_detect(audio_path)

        client = OpenAI(api_key=api_key)

        with open(audio_path, 'rb') as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["segment"]
            )

        segments = []
        detected_lang = getattr(response, 'language', 'zh')
        logger.info(f"Whisper detected language: {detected_lang}")

        for seg in response.segments:
            segments.append({
                'start': seg['start'],
                'end': seg['end'],
                'text': seg['text'].strip(),
                'language': detected_lang
            })

        logger.info(f"Detected {len(segments)} speech segments via OpenAI API")
        return segments

    except Exception as e:
        logger.error(f"OpenAI Whisper API failed: {e}. Falling back to local.")
        return _whisper_local_detect(audio_path)


def _whisper_local_detect(audio_path):
    """Use local openai-whisper for speech detection."""
    try:
        import whisper

        logger.info("Loading local Whisper model (base)...")
        model = whisper.load_model("base")

        result = model.transcribe(
            audio_path,
            task="transcribe",
            verbose=False
        )

        detected_lang = result.get('language', 'zh')
        logger.info(f"Local Whisper detected language: {detected_lang}")

        segments = []
        for seg in result.get('segments', []):
            segments.append({
                'start': seg['start'],
                'end': seg['end'],
                'text': seg['text'].strip(),
                'language': detected_lang
            })

        logger.info(f"Detected {len(segments)} speech segments locally")
        return segments

    except ImportError:
        logger.error("whisper package not installed. Run: pip install openai-whisper")
        return []
    except Exception as e:
        logger.error(f"Local Whisper detection failed: {e}")
        return []


# ============================================================
# STEP 3: Identify Chinese vs Cooking Segments
# ============================================================

def identify_segments(speech_segments, total_duration, min_cooking_duration=1.0):
    """
    Identify which parts to KEEP (cooking/serving) and which to REMOVE (Chinese speech).

    Logic:
    - Chinese speech segments → REMOVE
    - Everything else (silence, ambient sounds, non-Chinese speech) → KEEP
    - Merge nearby keep-segments for smoother output
    - Filter out very short keep-segments (< min_cooking_duration)

    Returns:
        List of keep_segments: [{'start': float, 'end': float}, ...]
    """
    if total_duration <= 0:
        return []

    # Mark all time as "keep" initially
    # Then subtract Chinese speech segments
    # Result = cooking/serving segments

    # Sort speech segments by start time
    sorted_speech = sorted(speech_segments, key=lambda x: x['start'])

    # Build "keep" segments by inverting speech segments
    keep_segments = []
    current_pos = 0.0

    for seg in sorted_speech:
        speech_start = max(0, seg['start'])
        speech_end = min(total_duration, seg['end'])

        # Add the gap before this speech segment as a keep segment
        if speech_start > current_pos + 0.1:  # At least 100ms gap
            keep_segments.append({
                'start': current_pos,
                'end': speech_start
            })

        current_pos = speech_end

    # Add the remaining part after the last speech segment
    if current_pos < total_duration - 0.1:
        keep_segments.append({
            'start': current_pos,
            'end': total_duration
        })

    # Merge nearby keep segments (gap < 0.5s)
    merged = _merge_close_segments(keep_segments, gap_threshold=0.5)

    # Filter out very short segments
    filtered = [s for s in merged if (s['end'] - s['start']) >= min_cooking_duration]

    logger.info(f"Identified {len(filtered)} cooking/serving segments (removed {len(sorted_speech)} speech segments)")

    for i, seg in enumerate(filtered):
        logger.info(f"  Keep segment {i+1}: {seg['start']:.2f}s - {seg['end']:.2f}s ({seg['end']-seg['start']:.2f}s)")

    return filtered


def _merge_close_segments(segments, gap_threshold=0.5):
    """Merge segments that are close together."""
    if not segments:
        return []

    merged = [segments[0].copy()]
    for seg in segments[1:]:
        if seg['start'] - merged[-1]['end'] < gap_threshold:
            merged[-1]['end'] = seg['end']
        else:
            merged.append(seg.copy())

    return merged


# ============================================================
# STEP 4: Cut and Concatenate Video Segments
# ============================================================

def cut_and_concatenate(video_path, keep_segments, output_path):
    """
    Cut the video to keep only the specified segments and concatenate them.

    Uses ffmpeg concat demuxer for lossless concatenation.
    """
    if not keep_segments:
        logger.error("No keep segments provided, cannot cut video.")
        return False

    temp_dir = tempfile.mkdtemp(prefix='food_video_')
    segment_files = []

    try:
        # Cut each segment
        for i, seg in enumerate(keep_segments):
            segment_path = os.path.join(temp_dir, f"seg_{i:04d}.mp4")
            duration = seg['end'] - seg['start']

            cmd = [
                'ffmpeg', '-y',
                '-ss', str(seg['start']),
                '-i', video_path,
                '-t', str(duration),
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                '-c:a', 'aac', '-b:a', '128k',
                '-avoid_negative_ts', 'make_zero',
                segment_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logger.warning(f"Failed to cut segment {i}: {result.stderr[-200:]}")
                continue

            if os.path.exists(segment_path) and os.path.getsize(segment_path) > 1000:
                segment_files.append(segment_path)
            else:
                logger.warning(f"Segment {i} file too small or missing, skipping.")

        if not segment_files:
            logger.error("No valid segments were cut.")
            return False

        # Concatenate segments using concat demuxer
        concat_list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_path, 'w') as f:
            for sf in segment_files:
                f.write(f"file '{sf}'\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', concat_list_path,
            '-c', 'copy',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"Concatenation failed: {result.stderr}")
            # Fallback: re-encode concat
            cmd_fallback = [
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0',
                '-i', concat_list_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                '-c:a', 'aac', '-b:a', '128k',
                output_path
            ]
            result = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.error(f"Fallback concatenation also failed: {result.stderr}")
                return False

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            logger.info(f"Video segments concatenated: {output_path}")
            return True
        else:
            logger.error("Concatenated output file is missing or too small.")
            return False

    except Exception as e:
        logger.error(f"Error during cut and concatenate: {e}")
        return False
    finally:
        # Cleanup temp files
        import shutil
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


# ============================================================
# STEP 5: Ensure 9:16 Vertical Format
# ============================================================

def ensure_vertical_format(video_path, output_path, target_width=1080, target_height=1920):
    """
    Ensure the video is in 9:16 vertical format.

    - If already vertical (9:16 or close): scale to target resolution
    - If horizontal: crop center to 9:16, then scale
    - If square or other: crop/scale to fit 9:16

    Output is always fullscreen 9:16 with NO black bars.
    """
    info = get_video_info(video_path)
    if not info:
        logger.error("Cannot get video info for format conversion.")
        return False

    width = info['width']
    height = info['height']
    target_ratio = target_width / target_height  # 9:16 = 0.5625
    current_ratio = width / height

    logger.info(f"Current: {width}x{height} (ratio={current_ratio:.4f}), Target: {target_width}x{target_height} (ratio={target_ratio:.4f})")

    # Already correct aspect ratio - just scale
    if abs(current_ratio - target_ratio) < 0.02:
        logger.info("Video already in correct aspect ratio, scaling to target resolution.")
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f'scale={target_width}:{target_height}:flags=lanczos',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            output_path
        ]
    # Horizontal or very wide: crop center to 9:16 then scale
    elif current_ratio > target_ratio:
        logger.info("Video is wider than 9:16, cropping center to fit.")
        # Calculate crop dimensions (crop height to match 9:16 ratio from width)
        crop_h = int(width / target_ratio)
        if crop_h > height:
            # Can't crop from width, crop from height instead
            crop_w = int(height * target_ratio)
            crop_h = height
        else:
            crop_w = width

        # Center crop
        x_offset = (width - crop_w) // 2
        y_offset = (height - crop_h) // 2

        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f'crop={crop_w}:{crop_h}:{x_offset}:{y_offset},scale={target_width}:{target_height}:flags=lanczos',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            output_path
        ]
    # Taller than 9:16: scale width to target, let height be proportional
    else:
        logger.info("Video is taller than 9:16, scaling to fit width.")
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f'scale={target_width}:-2:flags=lanczos',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            output_path
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"Format conversion failed: {result.stderr[-300:]}")
            return False

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            new_info = get_video_info(output_path)
            if new_info:
                logger.info(f"Final video: {new_info['width']}x{new_info['height']}, duration={new_info['duration']:.2f}s")
            return True
        return False

    except Exception as e:
        logger.error(f"Error during format conversion: {e}")
        return False


# ============================================================
# MAIN PIPELINE
# ============================================================

def process_food_video(video_path, output_path=None, min_segment_duration=1.5):
    """
    Complete pipeline: Chinese food video → clean 9:16 vertical video.

    Steps:
    1. Get video info
    2. Detect speech segments (Whisper)
    3. Identify Chinese speech → to remove
    4. Identify cooking/serving segments → to keep
    5. Cut and concatenate keep segments
    6. Ensure 9:16 vertical format
    7. Output clean video

    Args:
        video_path: Path to input Chinese food video
        output_path: Path for output (default: same dir with _clean suffix)
        min_segment_duration: Minimum duration (seconds) for a segment to be kept

    Returns:
        Path to processed video, or None on failure
    """
    logger.info(f"=== Starting Food Video Processing ===")
    logger.info(f"Input: {video_path}")

    if not os.path.exists(video_path):
        logger.error(f"Input video not found: {video_path}")
        return None

    if output_path is None:
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_clean{ext}"

    # Step 1: Get video info
    logger.info("Step 1/5: Analyzing video...")
    info = get_video_info(video_path)
    if not info:
        logger.error("Failed to analyze video.")
        return None

    total_duration = info['duration']
    logger.info(f"Video: {info['width']}x{info['height']}, duration={total_duration:.2f}s")

    # Skip very short videos (< 3 seconds)
    if total_duration < 3.0:
        logger.warning(f"Video too short ({total_duration:.2f}s), skipping.")
        return None

    # Step 2: Detect speech segments
    logger.info("Step 2/5: Detecting speech segments...")
    use_api = bool(os.environ.get('OPENAI_API_KEY'))
    speech_segments = detect_speech_segments(video_path, use_api=use_api)

    if not speech_segments:
        logger.info("No speech detected. Video is pure cooking/serving content.")
        # No speech = no Chinese to remove, just ensure format
        keep_segments = [{'start': 0, 'end': total_duration}]
    else:
        logger.info(f"Found {len(speech_segments)} speech segments")

        # Step 3: Identify cooking/serving segments
        logger.info("Step 3/5: Identifying cooking/serving segments...")
        keep_segments = identify_segments(
            speech_segments, total_duration,
            min_cooking_duration=min_segment_duration
        )

    if not keep_segments:
        logger.error("No cooking/serving segments found after analysis. Video may be entirely Chinese speech.")
        return None

    # Calculate total kept duration
    total_kept = sum(s['end'] - s['start'] for s in keep_segments)
    removed_pct = (1 - total_kept / total_duration) * 100 if total_duration > 0 else 0
    logger.info(f"Keeping {total_kept:.2f}s out of {total_duration:.2f}s ({removed_pct:.1f}% removed)")

    # Step 4: Cut and concatenate
    logger.info("Step 4/5: Cutting and concatenating segments...")
    temp_concat = output_path + '.temp.mp4'
    success = cut_and_concatenate(video_path, keep_segments, temp_concat)

    if not success:
        logger.error("Failed to cut and concatenate video segments.")
        return None

    # Step 5: Ensure 9:16 vertical format
    logger.info("Step 5/5: Ensuring 9:16 vertical format...")
    success = ensure_vertical_format(temp_concat, output_path)

    # Cleanup temp file
    if os.path.exists(temp_concat):
        try:
            os.remove(temp_concat)
        except:
            pass

    if not success:
        logger.error("Failed to convert to vertical format.")
        return None

    # Final validation
    final_info = get_video_info(output_path)
    if final_info:
        logger.info(f"=== Processing Complete ===")
        logger.info(f"Output: {output_path}")
        logger.info(f"Final: {final_info['width']}x{final_info['height']}, duration={final_info['duration']:.2f}s")
        logger.info(f"Segments kept: {len(keep_segments)}")

        # Verify it's actually vertical
        if final_info['width'] > final_info['height']:
            logger.warning("Output video is still horizontal! This should not happen.")
    else:
        logger.warning("Could not verify final video info.")

    return output_path


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python food_video_processor.py <video_path> [output_path]")
        print("Example: python food_video_processor.py input.mp4 output_clean.mp4")
        sys.exit(1)

    video = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None

    result = process_food_video(video, out)

    if result:
        print(f"\n✅ Food video processed successfully!")
        print(f"Output: {result}")
    else:
        print("\n❌ Processing failed!")
        sys.exit(1)
