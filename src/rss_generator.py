import os
import json
import requests
import urllib.parse
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
import sys

# Prevent encoding crashes when printing Chinese characters to standard output
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

FEED_FILE = 'workspace/reels_feed.xml'

def fetch_bilibili_videos(keyword):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/"
    }
    videos = []
    try:
        url = f"https://api.bilibili.com/x/web-interface/wbi/search/all/v2?keyword={urllib.parse.quote(keyword)}"
        r = requests.get(url, headers=headers, timeout=15)
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
                        if bvid:
                            title_clean = re.sub(r'<[^>]+>', '', v.get('title', ''))
                            videos.append({
                                'id': bvid,
                                'title': title_clean,
                                'link': f"https://www.bilibili.com/video/{bvid}",
                                'description': f"Bilibili video from search keyword: {keyword}"
                            })
    except Exception as e:
        print(f"Error fetching Bilibili videos for keyword '{keyword}': {e}")
    return videos

def generate_rss():
    print("Generating local RSS feed from Chinese video sources...")
    os.makedirs(os.path.dirname(FEED_FILE), exist_ok=True)
    
    # Collect all video items
    collected_items = []
    
    # Query categories
    categories = ["美食测评", "美食挑战", "做菜教程"]
    for cat in categories:
        collected_items.extend(fetch_bilibili_videos(cat))
        
    # Deduplicate by ID
    unique_items = []
    seen_ids = set()
    for item in collected_items:
        if item['id'] not in seen_ids:
            unique_items.append(item)
            seen_ids.add(item['id'])
            
    # Create XML Structure
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    
    title = ET.SubElement(channel, "title")
    title.text = "Chinese Food Reels XML RSS Feed"
    
    link = ET.SubElement(channel, "link")
    link.text = "http://localhost/reels_feed.xml"
    
    desc = ET.SubElement(channel, "description")
    desc.text = "Aggregated vertical and short Chinese food videos for translation"
    
    for item in unique_items:
        item_node = ET.SubElement(channel, "item")
        
        i_title = ET.SubElement(item_node, "title")
        i_title.text = item['title']
        
        i_link = ET.SubElement(item_node, "link")
        i_link.text = item['link']
        
        i_guid = ET.SubElement(item_node, "guid")
        i_guid.text = item['id']
        
        i_desc = ET.SubElement(item_node, "description")
        i_desc.text = item['description']
        
    # Pretty print XML
    xml_str = ET.tostring(rss, encoding='utf-8')
    parsed_xml = minidom.parseString(xml_str)
    pretty_xml = parsed_xml.toprettyxml(indent="  ", encoding="utf-8")
    
    with open(FEED_FILE, 'wb') as f:
        f.write(pretty_xml)
        
    print(f"Successfully generated local RSS feed with {len(unique_items)} items at: {FEED_FILE}")

if __name__ == "__main__":
    generate_rss()
