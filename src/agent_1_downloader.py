"""
Agent 1: Chinese Food Video Downloader

Downloads Chinese food videos from CURATED PROFILES ONLY.
- 10 specific Bilibili profiles that post cooking/serving content
- Content filter: only cooking process and food serving/plating videos
- NO tasting, eating, mukbang, or review videos
"""

import os
import json
import asyncio
import sys
import re
import urllib.parse
import requests
from dotenv import load_dotenv

# Prevent encoding crashes when printing Chinese characters
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

load_dotenv()
HISTORY_FILE = 'downloaded_history.txt'
QUEUE_FILE = 'workspace/queue.json'

# Content classifier: only cooking/serving videos allowed
try:
    from .food_video_processor import classify_video_content, is_video_processable
except ImportError:
    from food_video_processor import classify_video_content, is_video_processable


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            return set(f.read().splitlines())
    return set()


def save_to_history(video_id):
    with open(HISTORY_FILE, 'a') as f:
        f.write(f"{video_id}\n")


def load_queue():
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_queue(queue):
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    with open(QUEUE_FILE, 'w') as f:
        json.dump(queue, f, indent=2)


def load_curated_profiles():
    """Load curated food profiles from JSON config."""
    profiles_path = os.path.join(os.path.dirname(__file__), 'curated_profiles.json')
    if not os.path.exists(profiles_path):
        profiles_path = 'src/curated_profiles.json'
    if not os.path.exists(profiles_path):
        profiles_path = 'curated_profiles.json'

    if os.path.exists(profiles_path):
        try:
            with open(profiles_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('profiles', [])
        except Exception as e:
            print(f"Error loading curated profiles: {e}")
            return []
    else:
        print(f"WARNING: curated_profiles.json not found at {profiles_path}")
        return []


def fetch_bilibili_profile_videos(uid, max_videos=5):
    """
    Fetch latest videos from a Bilibili profile.
    Tries Bilibili API first, falls back to yt-dlp for profile scanning.
    Returns list of video dicts with bvid, title, url.
    """
    videos = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/"
    }

    # Method 1: Bilibili API
    try:
        api_url = f"https://api.bilibili.com/x/space/arc/search?mid={uid}&ps={max_videos}&pn=1&order=pubdate"
        r = requests.get(api_url, headers=headers, timeout=15)
        data = r.json()

        if data.get('code') == 0:
            vlist = data.get('data', {}).get('list', {}).get('vlist', [])
            for v in vlist:
                bvid = v.get('bvid', '')
                title = v.get('title', '')
                if bvid and title:
                    videos.append({
                        'bvid': bvid,
                        'title': title,
                        'url': f"https://www.bilibili.com/video/{bvid}",
                        'description': v.get('description', ''),
                        'duration': v.get('length', '')
                    })
            if videos:
                return videos
        else:
            print(f"  API error for UID {uid}: {data.get('message', 'unknown')}")

    except Exception as e:
        print(f"  Bilibili API error for {uid}: {e}")

    # Method 2: yt-dlp fallback (more reliable, handles rate limiting)
    try:
        import yt_dlp
        channel_url = f"https://space.bilibili.com/{uid}/video"
        print(f"  Trying yt-dlp fallback for UID {uid}...")

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlistend': max_videos,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(channel_url, download=False)
            if result and 'entries' in result:
                for entry in result['entries']:
                    if entry and entry.get('id'):
                        # If title is empty, try to get it from the URL
                        title = entry.get('title', '') or entry.get('fulltitle', '')
                        if not title:
                            # Extract title from URL pattern
                            title = entry.get('url', entry.get('id', ''))
                        videos.append({
                            'bvid': entry['id'],
                            'title': title,
                            'url': entry.get('url', f"https://www.bilibili.com/video/{entry['id']}"),
                            'description': entry.get('description', ''),
                            'duration': entry.get('duration', '')
                        })

    except Exception as e:
        print(f"  yt-dlp fallback failed for UID {uid}: {e}")

    return videos


async def scan_curated_profiles():
    """
    Scan ONLY curated food profiles for new cooking/serving videos.
    No random search — only specific profiles.
    """
    print("=" * 60)
    print("SCANNING CURATED FOOD PROFILES (Cooking/Serving Only)")
    print("=" * 60)

    profiles = load_curated_profiles()
    if not profiles:
        print("ERROR: No curated profiles found! Add profiles to src/curated_profiles.json")
        return

    print(f"Found {len(profiles)} curated profiles to scan")

    history = load_history()
    queue = load_queue()
    queued_ids = {item['id'] for item in queue}
    new_candidates = []

    for profile in profiles:
        profile_name = profile.get('name', profile.get('name_en', 'Unknown'))
        uid = profile.get('uid', '')
        platform = profile.get('platform', 'bilibili')
        content_type = profile.get('content_type', 'cooking')

        print(f"\n--- Scanning: {profile_name} ({platform}) ---")

        if not uid:
            print(f"  SKIP: No UID for {profile_name}")
            continue

        # Fetch latest videos from this profile
        if platform == 'bilibili':
            videos = fetch_bilibili_profile_videos(uid, max_videos=5)
        else:
            print(f"  SKIP: Platform '{platform}' not supported yet")
            continue

        if not videos:
            print(f"  No videos found for {profile_name}")
            continue

        print(f"  Found {len(videos)} videos from {profile_name}")

        # Delay between profiles to avoid rate limiting
        import time
        time.sleep(5)

        for video in videos:
            bvid = video['bvid']
            title = video['title']

            # Skip if already processed
            if bvid in history or bvid in queued_ids:
                continue

            # CONTENT FILTER: only cooking/serving videos allowed
            if not is_video_processable(title, video.get('description', '')):
                print(f"  REJECTED (not cooking/serving): {title[:60]}")
                continue

            # Classify content type
            content = classify_video_content(title, video.get('description', ''))
            print(f"  ✅ ACCEPTED ({content}): {title[:60]}")

            new_candidates.append({
                "id": bvid,
                "title": title[:120],
                "source_url": video['url'],
                "profile_name": profile_name,
                "profile_uid": uid,
                "content_type": content,
                "status": "PENDING"
            })
            queued_ids.add(bvid)

    # Save unique new candidates to queue
    if new_candidates:
        queue.extend(new_candidates)
        save_queue(queue)
        print(f"\n{'=' * 60}")
        print(f"Added {len(new_candidates)} new cooking/serving videos to queue")
        print(f"{'=' * 60}")
    else:
        print(f"\n{'=' * 60}")
        print("No new cooking/serving videos found in this scan")
        print(f"{'=' * 60}")


def scan_rss_feed():
    """Read local RSS feed (if available)."""
    print("Reading local RSS feed...")
    FEED_FILE = 'workspace/reels_feed.xml'
    if not os.path.exists(FEED_FILE):
        print(f"Local RSS feed not found at {FEED_FILE}. Skipping.")
        return

    try:
        import xml.etree.ElementTree as ET
        history = load_history()
        queue = load_queue()
        queued_ids = {item['id'] for item in queue}

        tree = ET.parse(FEED_FILE)
        root = tree.getroot()

        new_candidates = []
        for item in root.findall('.//item'):
            title_node = item.find('title')
            link_node = item.find('link')
            guid_node = item.find('guid')

            if title_node is not None and link_node is not None and guid_node is not None:
                vid = guid_node.text
                if vid not in history and vid not in queued_ids:
                    rss_title = title_node.text or ""
                    # CONTENT FILTER: only cooking/serving videos allowed
                    if not is_video_processable(rss_title):
                        print(f"REJECTED (not cooking/serving): {rss_title[:60]}")
                        continue
                    new_candidates.append({
                        "id": vid,
                        "title": rss_title,
                        "source_url": link_node.text,
                        "status": "PENDING"
                    })
                    print(f"RSS Feed Match: ID={vid} | Title={rss_title[:50]}")

        if new_candidates:
            queue.extend(new_candidates)
            save_queue(queue)
            print(f"Added {len(new_candidates)} new videos from RSS feed to queue.")
        else:
            print("No new unique videos found in the RSS feed.")
    except Exception as e:
        print(f"Error parsing local RSS feed: {e}")


def run_downloader():
    """Main downloader: scan curated profiles + RSS feed."""
    print("\n" + "=" * 60)
    print("CHINESE FOOD VIDEO DOWNLOADER")
    print("Source: Curated Profiles Only (Cooking/Serving)")
    print("=" * 60)

    # First parse from RSS feed if available
    scan_rss_feed()

    # Scan curated profiles (main source)
    try:
        asyncio.run(scan_curated_profiles())
    except Exception as e:
        print(f"Profile scan error: {e}")

    # Return the first PENDING video in the queue if available
    queue = load_queue()
    pending = [item for item in queue if item['status'] == 'PENDING']

    # If no pending videos from profiles, try YouTube search fallback
    if not pending:
        print("\nNo videos from curated profiles. Trying YouTube search fallback...")
        history = load_history()
        try:
            import yt_dlp
            search_queries = [
                "chinese cooking process vertical short",
                "chinese food making plating short",
                "中式烹饪 竖版 short",
            ]
            for query in search_queries:
                try:
                    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True}) as ydl:
                        result = ydl.extract_info(f"ytsearch5:{query}", download=False)
                        if result and 'entries' in result:
                            for entry in result['entries']:
                                if entry and entry.get('id'):
                                    vid_id = entry['id']
                                    if vid_id in history or vid_id in {item['id'] for item in queue}:
                                        continue
                                    title = entry.get('title', '') or entry.get('fulltitle', '')
                                    if not is_video_processable(title):
                                        continue
                                    new_item = {
                                        "id": vid_id,
                                        "title": title[:120],
                                        "source_url": f"https://www.youtube.com/watch?v={vid_id}",
                                        "profile_name": "YouTube Search",
                                        "content_type": classify_video_content(title),
                                        "status": "PENDING"
                                    }
                                    queue.append(new_item)
                                    save_queue(queue)
                                    pending.append(new_item)
                                    print(f"  YouTube fallback: {title[:60]}")
                                    break
                except Exception as e:
                    print(f"  YouTube search failed: {e}")
                if pending:
                    break
        except Exception as e:
            print(f"  YouTube fallback error: {e}")

    if pending:
        item = pending[0]
        print(f"\nNext pending video: {item['title']} ({item['source_url']})")

        # Add local_path for the editor
        item['local_path'] = "workspace/raw_video.mp4"
        item['original_file'] = f"{item['id']}.mp4"

        # Download the video
        import yt_dlp

        workspace_dir = "workspace"
        os.makedirs(workspace_dir, exist_ok=True)
        raw_video = os.path.join(workspace_dir, "raw_video.mp4")

        # Always download fresh
        if os.path.exists(raw_video):
            os.remove(raw_video)

        print(f"Downloading video: {item['source_url']}")

        # Try Bilibili direct download first
        download_success = False
        if "bilibili.com" in item['source_url'] or "b23.tv" in item['source_url']:
            match = re.search(r'video/(BV[a-zA-Z0-9]+)', item['source_url'])
            if match:
                bvid = match.group(1)
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Referer": "https://www.bilibili.com/"
                    }
                    view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
                    r = requests.get(view_url, headers=headers, timeout=15)
                    data = r.json()
                    if data.get('code') == 0:
                        cid = data['data']['cid']
                        playurl_api = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=16&type=&otype=json"
                        r2 = requests.get(playurl_api, headers=headers, timeout=15)
                        data2 = r2.json()
                        if data2.get('code') == 0:
                            video_url = data2['data']['durl'][0]['url']
                            r3 = requests.get(video_url, headers=headers, timeout=60)
                            r3.raise_for_status()
                            with open(raw_video, 'wb') as f:
                                f.write(r3.content)
                            if os.path.exists(raw_video) and os.path.getsize(raw_video) > 1000:
                                download_success = True
                                print(f"Bilibili download successful: {raw_video}")
                except Exception as e:
                    print(f"Bilibili direct download failed: {e}")

        # Fallback to yt-dlp
        if not download_success:
            try:
                ydl_opts = {
                    'outtmpl': raw_video,
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'merge_output_format': 'mp4',
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([item['source_url']])
                if os.path.exists(raw_video) and os.path.getsize(raw_video) > 1000:
                    download_success = True
                    print(f"yt-dlp download successful: {raw_video}")
            except Exception as e:
                print(f"yt-dlp download failed: {e}")

        if not download_success:
            print(f"Failed to download video: {item['source_url']}")
            return None

        # Mark as processing in queue
        item['status'] = 'PROCESSING'
        save_queue(queue)

        return item
    return None


if __name__ == "__main__":
    run_downloader()
