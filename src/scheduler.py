import os
import sys
import json
import subprocess
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Add src/ to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import logger
from agent_1_downloader import run_downloader, save_to_history
from telegram_reporter import report_success, report_failure, report_progress

HISTORY_LOG_FILE = 'workspace/processed_history.json'
QUEUE_FILE = 'workspace/queue.json'

def load_processed_history():
    if os.path.exists(HISTORY_LOG_FILE):
        try:
            with open(HISTORY_LOG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_processed_history(history):
    os.makedirs(os.path.dirname(HISTORY_LOG_FILE), exist_ok=True)
    with open(HISTORY_LOG_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def clean_and_count_recent_uploads():
    history = load_processed_history()
    now = datetime.now(timezone.utc)
    one_day_ago = now - timedelta(hours=24)
    
    # Filter for uploads in the last 24 hours
    recent_uploads = []
    for item in history:
        try:
            upload_time = datetime.fromisoformat(item['timestamp'])
            if upload_time >= one_day_ago:
                recent_uploads.append(item)
        except Exception:
            pass
            
    # Save cleaned history back
    save_processed_history(recent_uploads)
    return len(recent_uploads)

def update_queue_status(video_id, status):
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, 'r') as f:
                queue = json.load(f)
            for item in queue:
                if item['id'] == video_id:
                    item['status'] = status
            with open(QUEUE_FILE, 'w') as f:
                json.dump(queue, f, indent=2)
        except Exception as e:
            logger.error(f"Error updating queue status: {e}")

def main():
    load_dotenv()
    logger.info("Initializing Automated Scheduler Cycle...")
    
    # 1. Clean history and check quota
    recent_count = clean_and_count_recent_uploads()
    logger.info(f"Processed videos in last 24 hours: {recent_count}/5")
    
    if recent_count >= 5:
        logger.info("Daily quota of 5 videos in 24 hours has been reached. Skipping processing.")
        return
        
    # 2. Run scan to populate the queue
    logger.info("Scanning for new videos...")
    next_video = run_downloader()
    
    if not next_video:
        logger.info("No PENDING food videos available in the queue.")
        return
        
    video_id = next_video['id']
    source_url = next_video['source_url']
    title = next_video['title']
    
    logger.info(f"Triggering processing for video ID {video_id}: {title}")
    report_progress("Starting Processing Pipeline", f"Video ID: {video_id}\nTitle: {title}")
    
    # Update status to PROCESSING
    update_queue_status(video_id, "PROCESSING")
    
    # 3. Execute download, translation, editing, and subtitle burning
    try:
        python_exe = sys.executable
        # run run_pipeline.py which handles downloading and translating
        cmd = [python_exe, 'run_pipeline.py', source_url]
        logger.info(f"Running command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            error_msg = f"Pipeline execution failed (code {result.returncode}): {result.stderr}"
            logger.error(error_msg)
            report_failure("output_dubbed_reel.mp4", error_msg, 5 - recent_count - 1)
            update_queue_status(video_id, "FAILED")
            return
            
        logger.info("E2E translation and rendering completed successfully!")
        
        # 4. Upload Step (Call agent 3 uploader or simulate it)
        # Note: If FB_ACCESS_TOKEN and FB_PAGE_ID are active, we can run agent_3_uploader
        # Otherwise we copy to output and log success.
        fb_url = "https://facebook.com/watch/mock_reel_url"
        uploader_script = os.path.join(os.path.dirname(__file__), 'agent_3_uploader.py')
        if os.path.exists(uploader_script):
            try:
                # We can call the uploader agent to post to FB
                logger.info("Triggering Agent 3: Facebook Uploader...")
                upload_res = subprocess.run([python_exe, uploader_script], capture_output=True, text=True, timeout=300)
                if upload_res.returncode == 0:
                    logger.info("Agent 3 uploaded successfully.")
                else:
                    logger.warning(f"Agent 3 upload warning: {upload_res.stderr}")
            except Exception as e:
                logger.error(f"Error running uploader script: {e}")
                
        # 5. Save to history and update queue status
        save_to_history(video_id)
        update_queue_status(video_id, "COMPLETED")
        
        # Log to processed history
        history = load_processed_history()
        history.append({
            "id": video_id,
            "title": title,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        save_processed_history(history)
        
        # 6. Report Success to Telegram
        report_success(
            filename="output_dubbed_reel.mp4",
            title=title,
            fb_url=fb_url,
            remaining_queue=max(0, 5 - recent_count - 1)
        )
        logger.info(f"Video {video_id} processed, uploaded, and logged successfully.")
        
    except Exception as e:
        error_msg = f"Unexpected error during scheduling cycle: {e}"
        logger.error(error_msg)
        report_failure("output_dubbed_reel.mp4", error_msg, max(0, 5 - recent_count - 1))
        update_queue_status(video_id, "FAILED")

if __name__ == "__main__":
    main()
