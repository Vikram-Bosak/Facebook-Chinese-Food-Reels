import os
import sys
import shutil
import asyncio
import requests
import ffmpeg
import yt_dlp
import re

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from logger import logger
from translator import translate_video

def download_bilibili_direct(url, output_path):
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
        
        # 3. Direct download (non-streaming for smaller files prevents IncompleteRead errors)
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

async def extract_douyin_video_url(page_url):
    from playwright.async_api import async_playwright
    logger.info(f"Opening browser with mobile user agent to extract video URL from: {page_url}")
    async with async_playwright() as p:
        # Emulate iPhone
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            viewport={'width': 375, 'height': 812},
            is_mobile=True,
            has_touch=True
        )
        page = await context.new_page()
        
        # Navigate
        await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        logger.info("Page loaded, waiting for video element...")
        
        # Wait up to 10 seconds for video tag
        try:
            await page.wait_for_selector("video", timeout=15000)
        except Exception as e:
            logger.warning(f"Timeout waiting for video tag: {e}")
            
        # Get video source
        video_src = None
        video_elements = await page.query_selector_all("video")
        for v in video_elements:
            src = await v.get_attribute("src")
            if src:
                video_src = src
                break
                
        # If not found directly on video, check source tags
        if not video_src:
            sources = await page.query_selector_all("video source")
            for s in sources:
                src = await s.get_attribute("src")
                if src:
                    video_src = src
                    break
                    
        await browser.close()
        
        if video_src:
            # Handle relative URL
            if video_src.startswith("//"):
                video_src = "https:" + video_src
            elif video_src.startswith("/"):
                video_src = "https://www.douyin.com" + video_src
            logger.info(f"Extracted video source URL: {video_src}")
            return video_src
        else:
            logger.error("Could not find video element source.")
            return None

def download_video_direct(video_url, output_path):
    logger.info(f"Downloading video from CDN: {video_url}")
    headers = {
        "Referer": "https://www.douyin.com/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    }
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
            
        response = requests.get(video_url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            logger.info(f"Video downloaded successfully to {output_path} ({os.path.getsize(output_path)} bytes)")
            return True
        else:
            logger.error("Download failed: file is empty or missing.")
            return False
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return False

def download_with_ytdlp(url, output_path):
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

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_pipeline.py <video_url>")
        sys.exit(1)
        
    url = sys.argv[1]
    workspace_dir = "workspace"
    os.makedirs(workspace_dir, exist_ok=True)
    
    raw_video = os.path.join(workspace_dir, "raw_video.mp4")
    if os.path.exists(raw_video):
        try:
            os.remove(raw_video)
        except Exception:
            pass
            
    # Download fresh video
    download_success = False
    if "bilibili.com" in url or "b23.tv" in url:
        download_success = download_bilibili_direct(url, raw_video)
        
    if not download_success:
        # Try yt-dlp first (it doesn't need Playwright/browsers and is policy-safe)
        logger.info("Attempting download using yt-dlp...")
        download_success = download_with_ytdlp(url, raw_video)
        
    if not download_success:
        logger.warning("yt-dlp failed, falling back to Playwright...")
        # 1. Extract URL via Playwright
        video_url = asyncio.run(extract_douyin_video_url(url))
        if not video_url:
            logger.error("Failed to extract video URL. Exiting.")
            sys.exit(1)
            
        # 2. Download video
        if not download_video_direct(video_url, raw_video):
            logger.error("Failed to download video file. Exiting.")
            sys.exit(1)
            
    # Validate downloaded video duration and aspect ratio
    logger.info("Validating downloaded video constraints...")
    try:
        probe = ffmpeg.probe(raw_video)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if not video_stream:
            logger.error("Validation Failed: No video stream found.")
            if os.path.exists(raw_video):
                os.remove(raw_video)
            sys.exit(12)
            
        duration = float(probe['format'].get('duration', video_stream.get('duration', 0)))
        width = int(video_stream.get('width', 0))
        height = int(video_stream.get('height', 0))
        
        logger.info(f"Downloaded video stats: Duration = {duration}s, Dimensions = {width}x{height}")
        
        if width > height:
            logger.error(f"Validation Failed: Video is horizontal ({width}x{height}, must be vertical).")
            if os.path.exists(raw_video):
                os.remove(raw_video)
            sys.exit(12)
            
        logger.info("Video validation passed successfully.")
    except Exception as e:
        logger.error(f"Error during video validation: {e}")
        if os.path.exists(raw_video):
            os.remove(raw_video)
        sys.exit(12)
        
    # 3. Run translation pipeline
    logger.info("Starting translation & editing pipeline...")
    result = translate_video(
        raw_video,
        output_dir=workspace_dir,
        burn_subtitles=True,
        subtitle_language='english'
    )
    
    if result and result.get('english_video') and os.path.exists(result['english_video']):
        final_output = "output_dubbed_reel.mp4"
        shutil.copy2(result['english_video'], final_output)
        
        print("\n" + "="*50)
        print("SUCCESS: Chinese video downloaded, translated, and edited successfully!")
        print(f"Final English Video: {os.path.abspath(final_output)}")
        print(f"Subtitles: {result['subtitles']}")
        print("="*50 + "\n")
    else:
        logger.error("Failed to translate/edit video.")
        sys.exit(1)

if __name__ == '__main__':
    main()
