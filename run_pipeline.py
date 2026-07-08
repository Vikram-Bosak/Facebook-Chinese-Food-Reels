"""
Chinese Food Video Pipeline - Standalone Script

Downloads a Chinese food video from a URL, processes it by:
1. Removing Chinese speech segments
2. Keeping cooking/serving parts
3. Ensuring clean 9:16 vertical format
4. Output: Clean food reel ready for upload

Usage:
    python run_pipeline.py <video_url>

Example:
    python run_pipeline.py https://www.bilibili.com/video/BV1xx411c7mD
    python run_pipeline.py https://www.douyin.com/video/123456789
"""

import os
import sys
import re
import requests
import yt_dlp
import subprocess

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from logger import logger
from food_video_processor import process_food_video, get_video_info


def download_bilibili_direct(url, output_path):
    """Download from Bilibili using direct API."""
    logger.info(f"Attempting direct Bilibili API download for: {url}")
    try:
        match = re.search(r'video/(BV[a-zA-Z0-9]+)', url)
        if not match:
            logger.error("Could not parse BVID from Bilibili URL.")
            return False
        bvid = match.group(1)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/"
        }

        # 1. Get cid
        view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        r = requests.get(view_url, headers=headers, timeout=15)
        data = r.json()
        if data.get('code') != 0:
            logger.error(f"Error getting Bilibili view info: {data.get('message')}")
            return False

        cid = data['data']['cid']

        # 2. Get playurl
        playurl_api = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=16&type=&otype=json"
        r2 = requests.get(playurl_api, headers=headers, timeout=15)
        data2 = r2.json()
        if data2.get('code') != 0:
            logger.error(f"Error getting Bilibili play URL: {data2.get('message')}")
            return False

        durl = data2['data']['durl']
        video_url = durl[0]['url']

        # 3. Direct download
        if os.path.exists(output_path):
            os.remove(output_path)

        logger.info("Downloading Bilibili MP4...")
        r3 = requests.get(video_url, headers=headers, timeout=60)
        r3.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(r3.content)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            logger.info("Direct Bilibili download completed successfully.")
            return True
        return False
    except Exception as e:
        logger.error(f"Direct Bilibili download failed: {e}")
        return False


def download_with_ytdlp(url, output_path):
    """Download using yt-dlp."""
    logger.info(f"Downloading via yt-dlp: {url}")
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
        ydl_opts = {
            'outtmpl': output_path,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            logger.info("Downloaded successfully via yt-dlp")
            return True
        return False
    except Exception as e:
        logger.error(f"yt-dlp download failed: {e}")
        return False


def validate_vertical(video_path):
    """Validate that video is vertical (height > width)."""
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=15
        )
        if probe.returncode == 0 and probe.stdout.strip():
            parts = probe.stdout.strip().split(',')
            if len(parts) == 2:
                width, height = int(parts[0]), int(parts[1])
                if width > height:
                    logger.error(f"Video is horizontal ({width}x{height}), must be vertical.")
                    return False
        return True
    except Exception as e:
        logger.warning(f"Could not validate video orientation: {e}")
        return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_pipeline.py <video_url>")
        print("\nExample:")
        print("  python run_pipeline.py https://www.bilibili.com/video/BV1xx411c7mD")
        print("  python run_pipeline.py https://www.douyin.com/video/123456789")
        sys.exit(1)

    url = sys.argv[1]
    output_dir = "workspace"
    os.makedirs(output_dir, exist_ok=True)

    raw_video = os.path.join(output_dir, "raw_video.mp4")
    final_output = "output_food_reel.mp4"

    # Clean old files
    for f in [raw_video, final_output]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass

    # === STEP 1: Download ===
    logger.info("=" * 50)
    logger.info("STEP 1: Downloading Chinese food video...")
    logger.info("=" * 50)

    download_success = False
    if "bilibili.com" in url or "b23.tv" in url:
        download_success = download_bilibili_direct(url, raw_video)

    if not download_success:
        logger.info("Trying yt-dlp...")
        download_success = download_with_ytdlp(url, raw_video)

    if not download_success:
        logger.error("Failed to download video. Exiting.")
        sys.exit(1)

    # Validate downloaded video
    info = get_video_info(raw_video)
    if info:
        logger.info(f"Downloaded: {info['width']}x{info['height']}, duration={info['duration']:.2f}s")
    else:
        logger.error("Could not analyze downloaded video.")
        sys.exit(1)

    # === STEP 2: Process (Remove Chinese speech, keep cooking/serving, ensure 9:16) ===
    logger.info("=" * 50)
    logger.info("STEP 2: Processing food video...")
    logger.info("  → Detecting Chinese speech segments...")
    logger.info("  → Removing Chinese speaking parts...")
    logger.info("  → Keeping cooking/serving segments...")
    logger.info("  → Ensuring 9:16 vertical format...")
    logger.info("=" * 50)

    result_path = process_food_video(
        raw_video,
        output_path=final_output,
        min_segment_duration=1.5
    )

    if result_path and os.path.exists(result_path):
        final_info = get_video_info(result_path)
        if final_info:
            logger.info(f"Final video: {final_info['width']}x{final_info['height']}, duration={final_info['duration']:.2f}s")

        print("\n" + "=" * 50)
        print("SUCCESS: Chinese food video processed successfully!")
        print(f"Output: {os.path.abspath(final_output)}")
        print(f"  → Chinese speech parts removed")
        print(f"  → Cooking/serving segments kept")
        print(f"  → Clean 9:16 vertical format")
        print(f"  → No overlays or templates")
        print("=" * 50 + "\n")
    else:
        logger.error("Food video processing failed.")
        sys.exit(1)


if __name__ == '__main__':
    main()
