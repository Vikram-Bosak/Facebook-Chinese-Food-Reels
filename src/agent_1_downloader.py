import os
import json
import asyncio
from playwright.async_api import async_playwright
from dotenv import load_dotenv

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
    print("Scanning Douyin Food section for new videos...")
    history = load_history()
    queue = load_queue()
    queued_ids = {item['id'] for item in queue}
    
    # Target URL for food videos
    target_url = "https://www.douyin.com/jingxuan/food"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)
            
            # Extract cards with data-aweme-id
            cards = await page.query_selector_all('[data-aweme-id]')
            print(f"Found {len(cards)} video cards on the page.")
            
            new_candidates = []
            for card in cards:
                aweme_id = await card.get_attribute('data-aweme-id')
                if not aweme_id:
                    continue
                    
                if aweme_id in history or aweme_id in queued_ids:
                    continue
                    
                text = await card.inner_text()
                text_cleaned = ' '.join(text.split())
                
                # Check for food related keywords
                keywords = ["美食", "小吃", "烹饪", "做菜", "食谱", "味道", "烧烤", "海鲜", "水果", "夜市", "葱花饼", "牛肋排"]
                is_food = any(kw in text_cleaned for kw in keywords)
                
                if is_food:
                    video_url = f"https://www.douyin.com/video/{aweme_id}"
                    new_candidates.append({
                        "id": aweme_id,
                        "title": text_cleaned[:120],
                        "source_url": video_url,
                        "status": "PENDING"
                    })
                    print(f"Discovered new food video: ID={aweme_id} | Title={text_cleaned[:50]}")
            
            if new_candidates:
                # Add to queue
                queue.extend(new_candidates)
                save_queue(queue)
                print(f"Added {len(new_candidates)} new videos to the queue.")
            else:
                print("No new unique food videos discovered in this scan.")
                
        except Exception as e:
            print(f"Error scanning Douyin: {e}")
        finally:
            await browser.close()

def run_downloader():
    print("Running Downloader: Scanning and filling queue...")
    asyncio.run(scan_douyin_food_videos())
    
    # Return the first PENDING video in the queue if available
    queue = load_queue()
    pending = [item for item in queue if item['status'] == 'PENDING']
    if pending:
        # Return first pending item metadata
        item = pending[0]
        print(f"Next pending video: {item['title']} ({item['source_url']})")
        return item
    return None

if __name__ == "__main__":
    run_downloader()
