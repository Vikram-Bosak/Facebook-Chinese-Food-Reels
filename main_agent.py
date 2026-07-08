"""
Chinese Food Reels Pipeline

Main entry point for the automated pipeline:
1. Download Chinese food videos (cooking, serving, plating)
2. Process: Remove Chinese speech parts, keep cooking/serving segments
3. Ensure clean 9:16 vertical format (no overlays, no templates)
4. Upload to Facebook Reels + YouTube Shorts

Pipeline flow:
  Download → Food Video Edit → Upload → Report
"""

import os
import sys
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.agent_1_downloader import run_downloader
from src.agent_2_editor import process_video
from src.agent_3_uploader import run_upload
from src.common.limits import can_download, can_upload, increment_download, increment_edit
from src.common.telegram import (
    report_final_summary,
    report_download_start,
    report_download_complete,
    report_edit_start,
    report_edit_complete,
    send_message
)


def run_single_sequence():
    """Run one iteration of the Chinese food reels pipeline."""
    print("\n--- STARTING CHINESE FOOD REELS PIPELINE ---")

    if not can_download() or not can_upload():
        print("Daily upload limit reached. Exiting.")
        return False

    # 1. Download Chinese food video
    report_download_start()
    video_data = run_downloader()
    if not video_data:
        print("No food video found.")
        send_message("⚠️ <b>Download Skipped:</b> No new Chinese food videos found.")
        return False

    task_id = video_data['id']
    print(f"Downloaded Video: {task_id}")
    report_download_complete(video_data['source_url'])
    send_message(f"🆔 <b>Video ID:</b> {task_id}")
    increment_download()

    # 2. Process: Remove Chinese speech, keep cooking/serving, ensure 9:16
    report_edit_start()
    try:
        print(f"Processing food video {task_id}...")
        print("  → Detecting Chinese speech segments...")
        print("  → Removing Chinese speaking parts...")
        print("  → Keeping cooking/serving segments...")
        print("  → Ensuring 9:16 vertical format...")

        video_data = process_video(video_data)
        if video_data.get('editing_status') == 'Success':
            report_edit_complete()
            increment_edit()
            print(f"✅ Video processed successfully: {video_data.get('edited_path', 'N/A')}")
        else:
            send_message(f"❌ <b>Processing Failed for {task_id}</b>")
            return False
    except Exception as e:
        print(f"Processing failed: {e}")
        send_message(f"❌ <b>Processing Failed for {task_id}:</b>\n{e}")
        return False

    # 3. Upload to Facebook + YouTube
    print(f"Uploading Video {task_id}...")
    video_data = run_upload(video_data)

    # Final Report
    report_final_summary(video_data)

    print("Pipeline run completed.")
    return True


if __name__ == "__main__":
    run_single_sequence()
