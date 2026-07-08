"""
Agent 2: Food Video Editor

Processes Chinese food videos by:
1. Validating content type (only cooking/serving allowed)
2. Removing Chinese speech segments (keeping cooking/serving parts)
3. Removing any templates, overlays, or frames
4. Ensuring clean 9:16 vertical fullscreen format

No AI headline generation, no overlay images, no templates.
"""

import os
import sys

try:
    from .logger import logger
    from .food_video_processor import process_food_video, get_video_info, classify_video_content
except ImportError:
    from logger import logger
    from food_video_processor import process_food_video, get_video_info, classify_video_content


def process_video(video_data):
    """
    Process a food video: validate content, remove Chinese speech, ensure 9:16 format.

    Args:
        video_data: Dict with 'local_path', 'id', 'title', etc.

    Returns:
        Updated video_data dict with 'editing_status' and 'edited_path'
    """
    print("Starting Agent 2: Food Video Editor")

    raw_video_path = video_data.get('local_path', "workspace/raw_video.mp4")
    title = video_data.get('title', 'Unknown Video')
    video_id = video_data.get('id', 'video')
    edited_video_path = f"workspace/edited_{video_id}.mp4"

    if not os.path.exists(raw_video_path):
        print(f"Raw video not found at {raw_video_path}.")
        video_data["editing_status"] = "Failed"
        return video_data

    # === CONTENT VALIDATION: Only cooking/serving videos allowed ===
    print(f"Validating content type: {title[:80]}")
    content_type = classify_video_content(title)

    if content_type not in ('cooking', 'serving'):
        print(f"❌ REJECTED: Video classified as '{content_type}' (only cooking/serving allowed)")
        print(f"   Title: {title[:80]}")
        video_data["editing_status"] = "Rejected"
        video_data["reject_reason"] = f"Content type '{content_type}' not allowed (only cooking/serving)"
        return video_data

    print(f"✅ Content type: {content_type} — processing...")

    # Get video info first
    info = get_video_info(raw_video_path)
    if info:
        print(f"Input video: {info['width']}x{info['height']}, duration={info['duration']:.2f}s")
    else:
        print("Warning: Could not get video info, proceeding anyway...")

    # Process the food video
    # This will:
    # 1. Detect Chinese speech with Whisper
    # 2. Cut out Chinese speaking parts
    # 3. Keep cooking/serving segments
    # 4. Ensure 9:16 vertical format
    # 5. Output clean video (no overlays)
    result_path = process_food_video(
        raw_video_path,
        output_path=edited_video_path,
        min_segment_duration=1.5  # Keep segments >= 1.5 seconds
    )

    if result_path and os.path.exists(result_path):
        video_data["editing_status"] = "Success"
        video_data["edited_path"] = result_path

        # Get final video info
        final_info = get_video_info(result_path)
        if final_info:
            print(f"Output video: {final_info['width']}x{final_info['height']}, duration={final_info['duration']:.2f}s")

        # Cleanup raw video
        if os.path.exists(raw_video_path):
            try:
                os.remove(raw_video_path)
                print(f"Cleaned up raw video: {raw_video_path}")
            except Exception as e:
                print(f"Warning: Could not cleanup raw video: {e}")

        return video_data
    else:
        video_data["editing_status"] = "Failed"
        print("Food video processing failed.")
        return video_data


if __name__ == "__main__":
    pass
