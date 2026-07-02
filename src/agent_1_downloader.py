import os
import json
import asyncio
import sys
from dotenv import load_dotenv

# Prevent encoding crashes when printing Chinese characters to standard output
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

load_dotenv()
HISTORY_FILE = 'downloaded_history.txt'
QUEUE_FILE = 'workspace/queue.json'

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

async def scan_douyin_food_videos():
    print("Scanning Douyin, Kuaishou, and Bilibili Food sections...")
    history = load_history()
    queue = load_queue()
    queued_ids = {item['id'] for item in queue}
    new_candidates = []
    
    # 1. Robust Bilibili API Fallback (Does not require Playwright)
    import urllib.parse
    import requests
    import re
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/"
    }
    
    bilibili_kws = ["美食测评", "美食挑战", "做菜教程"]
    for kw in bilibili_kws:
        try:
            url = f"https://api.bilibili.com/x/web-interface/wbi/search/all/v2?keyword={urllib.parse.quote(kw)}"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get('code') == 0:
                    result = data.get('data', {}).get('result', [])
                    video_result = None
                    if isinstance(result, list):
                        for item in result:
                            if isinstance(item, dict) and item.get('result_type') == 'video':
                                video_result = item
                                break
                    elif isinstance(result, dict):
                        video_result = result.get('video')
                        
                    if video_result:
                        data_list = video_result.get('data', [])
                        for v in data_list:
                            bvid = v.get('bvid')
                            if not bvid:
                                continue
                            if bvid in history or bvid in queued_ids:
                                continue
                            
                            title_clean = re.sub(r'<[^>]+>', '', v.get('title', ''))
                            video_url = f"https://www.bilibili.com/video/{bvid}"
                            new_candidates.append({
                                "id": bvid,
                                "title": title_clean[:120],
                                "source_url": video_url,
                                "status": "PENDING"
                            })
                            print(f"Discovered Bilibili food video: ID={bvid} | Title={title_clean[:50]}")
        except Exception as e:
            print(f"Error scanning Bilibili API: {e}")

    # 2. Playwright Scraper for Douyin, Kuaishou, and Bilibili (runs on GitHub Actions or policy-free environments)
    try:
        from playwright.async_api import async_playwright
        
        target_urls = [
            "https://www.douyin.com/jingxuan",
            "https://www.kuaishou.com/new-reco",
            "https://www.bilibili.com/"
        ]
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 800}
            )
            page = await context.new_page()
            
            for target_url in target_urls:
                try:
                    print(f"Playwright scraping: {target_url}")
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(5000)
                    
                    # Douyin / Kuaishou card extraction
                    if "douyin.com" in target_url:
                        cards = await page.query_selector_all('[data-aweme-id]')
                        for card in cards:
                            aweme_id = await card.get_attribute('data-aweme-id')
                            if aweme_id and aweme_id not in history and aweme_id not in queued_ids:
                                text = await card.inner_text()
                                text_cleaned = ' '.join(text.split())
                                keywords = ["测评", "试吃", "吃播", "评价", "点评", "体验", "口味", "挑战", "比赛", "大胃王", "pk", "教程", "配方", "做法", "步骤", "做菜", "烹饪", "食谱"]
                                if any(kw in text_cleaned for kw in keywords):
                                    new_candidates.append({
                                        "id": aweme_id,
                                        "title": text_cleaned[:120],
                                        "source_url": f"https://www.douyin.com/video/{aweme_id}",
                                        "status": "PENDING"
                                    })
                                    print(f"Discovered Douyin video: ID={aweme_id} | Title={text_cleaned[:50]}")
                                    
                    elif "kuaishou.com" in target_url:
                        # Extract links containing short-video or Kwai video patterns
                        links = await page.query_selector_all('a')
                        for link in links:
                            href = await link.get_attribute('href')
                            if href and ('/short-video/' in href or '/video/' in href or '/f/' in href):
                                vid = href.split('/')[-1].split('?')[0]
                                if vid and vid not in history and vid not in queued_ids:
                                    text = await link.inner_text()
                                    text_cleaned = ' '.join(text.split())
                                    new_candidates.append({
                                        "id": vid,
                                        "title": text_cleaned[:120] if text_cleaned else f"Kuaishou Video {vid}",
                                        "source_url": f"https://www.kuaishou.com/short-video/{vid}" if not href.startswith('http') else href,
                                        "status": "PENDING"
                                    })
                                    print(f"Discovered Kuaishou video: ID={vid}")
                                    
                except Exception as e:
                    print(f"Error scraping {target_url} with Playwright: {e}")
            await browser.close()
            
    except Exception as err:
        print(f"Playwright scraper skipped/failed: {err}")

    # Save unique new candidates to queue
    if new_candidates:
        unique_candidates = []
        seen_ids = set(queued_ids)
        for c in new_candidates:
            if c['id'] not in seen_ids:
                unique_candidates.append(c)
                seen_ids.add(c['id'])
                
        if unique_candidates:
            queue.extend(unique_candidates)
            save_queue(queue)
            print(f"Added {len(unique_candidates)} new videos to the queue.")
        else:
            print("No new unique food videos discovered in this scan.")
    else:
        print("No new unique food videos discovered in this scan.")

def scan_rss_feed():
    print("Reading local RSS feed...")
    FEED_FILE = 'workspace/reels_feed.xml'
    if not os.path.exists(FEED_FILE):
        print(f"Local RSS feed not found at {FEED_FILE}. Please run rss_generator.py first.")
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
                    new_candidates.append({
                        "id": vid,
                        "title": title_node.text,
                        "source_url": link_node.text,
                        "status": "PENDING"
                    })
                    print(f"RSS Feed Match: ID={vid} | Title={title_node.text[:50]}")
                    
        if new_candidates:
            queue.extend(new_candidates)
            save_queue(queue)
            print(f"Added {len(new_candidates)} new videos from RSS feed to the queue.")
        else:
            print("No new unique videos found in the RSS feed.")
    except Exception as e:
        print(f"Error parsing local RSS feed: {e}")

def run_downloader():
    print("Running Downloader: Scanning and filling queue...")
    # First parse from RSS feed if available
    scan_rss_feed()
    
    # Also attempt standard scraper scan in background
    try:
        asyncio.run(scan_douyin_food_videos())
    except Exception:
        pass
    
    # Return the first PENDING video in the queue if available
    queue = load_queue()
    pending = [item for item in queue if item['status'] == 'PENDING']
    if pending:
        # Return first pending item metadata
        item = pending[0]
        print(f"Next pending video: {item['title']} ({item['source_url']})")
        
        # Add local_path for the editor
        item['local_path'] = "workspace/raw_video.mp4"
        item['original_file'] = f"{item['id']}.mp4"
        
        # Download the video if not already downloaded
        import yt_dlp
        import requests
        import re
        
        workspace_dir = "workspace"
        os.makedirs(workspace_dir, exist_ok=True)
        raw_video = os.path.join(workspace_dir, "raw_video.mp4")
        
        if not os.path.exists(raw_video) or os.path.getsize(raw_video) < 1000:
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
