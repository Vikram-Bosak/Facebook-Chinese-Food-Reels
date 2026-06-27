import os
import hashlib
import ffmpeg
import time
try:
    from .database import is_duplicate, insert_media, update_reel_metadata, mark_reel_uploaded, mark_reel_failed, get_reel_status, increment_attempts, reset_attempts
    from .seo_generator import generate_seo_metadata, format_caption
    from .facebook_uploader import upload_reel, upload_photo
    from .telegram_reporter import report_success, report_failure, report_progress
    from .drive_reader import get_next_media, move_file, count_pending_media
    from .logger import logger
    from .translator import translate_video
except ImportError:
    from database import is_duplicate, insert_media, update_reel_metadata, mark_reel_uploaded, mark_reel_failed, get_reel_status, increment_attempts, reset_attempts
    from seo_generator import generate_seo_metadata, format_caption
    from facebook_uploader import upload_reel, upload_photo
    from telegram_reporter import report_success, report_failure, report_progress
    from drive_reader import get_next_media, move_file, count_pending_media
    from logger import logger
    from translator import translate_video

class PermanentValidationError(Exception):
    """Exception raised for errors that cannot be resolved via retries (e.g. corrupt files, duplicates)."""
    pass

def get_file_hash(filepath):
    """Calculates MD5 hash of the file to prevent exact duplicates."""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def validate_media(filepath, media_type='reel'):
    """
    Validates if media meets constraints.
    """
    try:
        if media_type == 'photo':
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if file_size_mb > 30:
                return False, "Photo exceeds 30MB limit"
            ext = os.path.splitext(filepath)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png']:
                return False, "Photo format must be JPG or PNG"
            return True, "Valid"

        # Check file size (100 MB max)
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        if file_size_mb > 100:
            return False, "File exceeds 100MB limit"
            
        probe = ffmpeg.probe(filepath)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        
        if not video_stream:
            return False, "No video stream found"
            
        # Check orientation
        width = int(video_stream.get('width', 0))
        height = int(video_stream.get('height', 0))
        if width > height:
            return False, "Video is horizontal, must be vertical (9:16)"
            
        return True, "Valid"
    except FileNotFoundError:
        return False, "FFmpeg/FFprobe was not found on your system PATH. Please install FFmpeg and make sure it is added to the PATH."
    except ffmpeg.Error as e:
        return False, f"FFmpeg error parsing video: {e}"
    except Exception as e:
        return False, f"Error validating media: {e}"

def process_next_media(media_type='reel'):
    """Main workflow to process one media item from the queue with robust retry/validation logic."""
    video_info = get_next_media(media_type)
    if not video_info:
        logger.info(f"No pending {media_type}s found in Google Drive.")
        return False
        
    filepath = video_info['path']
    filename = video_info['filename']
    file_id = video_info['file_id']
    service = video_info['service']
    
    remaining_queue = count_pending_media(media_type) - 1
    
    logger.info(f"Processing {media_type}: {filename}")
    
    try:
        # Duplicate Check
        file_hash = get_file_hash(filepath)
        db_status, db_attempts = get_reel_status(filename, file_hash)
        
        if db_status == 'uploaded':
            raise PermanentValidationError(f"Duplicate file detected: {media_type} already successfully uploaded.")
        elif db_status == 'failed':
            raise PermanentValidationError(f"Duplicate file detected: {media_type} has already failed permanently.")
        elif db_status == 'pending':
            if db_attempts >= 3:
                raise PermanentValidationError(f"{media_type} has already failed after {db_attempts} attempts.")
            else:
                logger.info(f"{media_type} {filename} is in pending status (attempt {db_attempts + 1}/3). Retrying...")
            
        # Media Validation
        is_valid, msg = validate_media(filepath, media_type)
        if not is_valid:
            raise PermanentValidationError(f"{media_type} validation failed: {msg}")
            
        # Database tracking (prevent parallel processing)
        if db_status is None:
            if not insert_media(filename, file_hash, media_type):
                raise PermanentValidationError("Failed to lock file in database. Might be processing already.")
            
        # AI SEO Generation
        logger.info("Generating SEO metadata via OpenAI...")
        report_progress("SEO Generation", f"Generating English title/hashtags for: {filename}")
        seo = generate_seo_metadata(filename, media_type)
        caption = format_caption(seo)
        update_reel_metadata(filename, seo['title'], seo['description'], seo['hashtags'])
        
        # Translation: Chinese → English (if enabled)
        upload_filepath = filepath  # Default: upload original
        translate_enabled = os.environ.get('ENABLE_TRANSLATION', 'false').lower() == 'true'
        
        if translate_enabled and media_type == 'reel':
            logger.info("Translating Chinese video to English...")
            report_progress("Translation & Dubbing", f"Dubbing '{filename}' to English with Lip-Sync aligned OpenAI TTS...")
            try:
                output_dir = os.path.join(os.path.dirname(filepath), 'translated')
                os.makedirs(output_dir, exist_ok=True)
                
                translation_result = translate_video(
                    filepath, 
                    output_dir=output_dir,
                    burn_subtitles=True,
                    subtitle_language='dual'
                )
                
                if translation_result and translation_result.get('english_video'):
                    upload_filepath = translation_result['english_video']
                    logger.info(f"Translation successful: {upload_filepath}")
                else:
                    logger.warning("Translation failed, uploading original video")
            except Exception as translate_err:
                logger.warning(f"Translation error: {translate_err}, uploading original")
        
        # Facebook Upload with Retries
        logger.info(f"Uploading to Facebook {media_type}s...")
        report_progress("Uploading", f"Uploading '{seo.get('title', filename)}' to Facebook Page...")
        max_retries = 3
        retry_delays = [60, 300, 900] # 1 min, 5 min, 15 min
        fb_url = None
        
        for attempt in range(max_retries):
            try:
                if media_type == 'reel':
                    fb_url = upload_reel(upload_filepath, caption, title=seo.get('title'))
                else:
                    fb_url = upload_photo(upload_filepath, caption)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delays[attempt]
                    logger.warning(f"Upload attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Upload failed after {max_retries} attempts: {e}")
                    
        # Success Handling
        mark_reel_uploaded(filename, fb_url)
        report_success(filename, seo['title'], fb_url, remaining_queue, media_type)
        
        # Move file in Drive
        move_file(service, file_id, video_info['pending_id'], video_info['uploaded_id'])
        logger.info("Process completed successfully. Video uploaded and moved to 'Uploaded' folder.")
        
    except PermanentValidationError as e:
        # Failure Handling for permanent/validation errors
        logger.error(f"Permanent validation error processing media: {e}")
        mark_reel_failed(filename)
        report_failure(filename, str(e), remaining_queue, media_type)
        
        # Move file in Drive to Failed immediately
        try:
            move_file(service, file_id, video_info['pending_id'], video_info['failed_id'])
            logger.info("Video moved to 'Failed' folder in Google Drive due to validation error.")
        except Exception as move_err:
            logger.error(f"Also failed to move file in Drive: {move_err}")
            
    except Exception as e:
        # Failure Handling for transient/network/API errors
        logger.error(f"Transient error processing video: {e}")
        
        # Increment attempt counter
        attempts = increment_attempts(filename)
        if attempts >= 3:
            logger.error(f"Max attempts (3) reached for {media_type} {filename}. Marking as failed permanently.")
            mark_reel_failed(filename)
            report_failure(filename, f"Upload failed after 3 attempts: {e}", remaining_queue, media_type)
            
            # Move file in Drive to Failed
            try:
                move_file(service, file_id, video_info['pending_id'], video_info['failed_id'])
                logger.info("Video moved to 'Failed' folder in Google Drive.")
            except Exception as move_err:
                logger.error(f"Also failed to move file in Drive: {move_err}")
        else:
            # Keep the file in the Pending folder so the scheduler retries it next run
            warn_msg = f"Upload failed (attempt {attempts}/3): {e}. Remaining in pending for retry."
            logger.warning(warn_msg)
            report_failure(filename, warn_msg, remaining_queue, media_type)
            
    finally:
        # Cleanup temp files (original + translated)
        for cleanup_path in [filepath, upload_filepath]:
            if cleanup_path and os.path.exists(cleanup_path) and cleanup_path != filepath:
                try:
                    os.remove(cleanup_path)
                    logger.info(f"Translated file cleaned up: {cleanup_path}")
                except Exception as cleanup_err:
                    logger.error(f"Failed to cleanup translated file: {cleanup_err}")
        
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"Temporary file cleaned up: {filepath}")
            except Exception as cleanup_err:
                logger.error(f"Failed to cleanup temporary file {filepath}: {cleanup_err}")
            
    return True
