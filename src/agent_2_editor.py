import os
import requests
import ffmpeg
import json
import textwrap
import unicodedata
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# Attempt to import openai
try:
    import openai
except ImportError:
    openai = None

load_dotenv()


OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

if OPENAI_API_KEY and openai:
    openai.api_key = OPENAI_API_KEY


def generate_headline(title):
    """Uses Nvidia AI (via OpenAI client) to generate a short Chinese headline hook"""
    if not openai or not OPENAI_API_KEY:
        print("OpenAI/Nvidia API key not found. Using default headline format.")
        # Default simple parser if no AI — just return the title as-is
        return {"hook": title, "highlights": []}

    try:
        # Use Nvidia's base URL as requested
        client = openai.OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=OPENAI_API_KEY,
            timeout=30.0
        )

        prompt = (
            f"分析这个中文标题: '{title}'。\n"
            "为短视频创作一个吸引眼球、制造悬念的标题钩子。\n"
            "规则:\n"
            "1. 必须制造强烈悬念，让观众立刻停下来看。\n"
            "2. 保持简短有力（5到15个字）。\n"
            "3. 使用有冲击力的词语（例如：'震惊', '终于', '真相', '万万没想到', '太离谱了'）。\n"
            "4. 用中文输出，不要用英文。\n"
            "5. 不要括号、不要特殊标签。\n"
            "6. 返回一个有效的JSON对象，包含一个key: \"hook\"（完整文本）。\n"
            "示例返回:\n"
            "{\"hook\": \"震惊！这个真相居然没人知道！\"}"
        )

        response = client.chat.completions.create(
            model="nvidia/nemotron-3-ultra-550b-a55b",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            top_p=0.9,
            max_tokens=150
        )
        raw_text = response.choices[0].message.content.strip()

        # Try extracting JSON
        headline = ""
        highlights = []
        import re
        json_match = re.search(r'\{.*?\}', raw_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                headline = data.get("hook", "")
                highlights = data.get("highlights", [])
            except:
                pass

        if not headline:
            # Fallback parsing
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            if lines:
                headline = lines[-1]

        # Clean up characters
        headline = headline.replace('"', '').replace("'", "")

        # Do NOT force ALL CAPS — Chinese characters don't have case
        # Only uppercase Latin characters if any remain
        if headline and not any('\u4e00' <= c <= '\u9fff' for c in headline):
            headline = headline.upper()
            highlights = [h.upper().strip() for h in highlights]

        # Limit length safely (by character count for Chinese)
        if len(headline) > 50:
            headline = headline[:50] + "..."

        if not headline or "USER WANTS" in headline:
            return {"hook": title, "highlights": []}

        return {"hook": headline, "highlights": highlights}
    except Exception as e:
        print(f"AI Generation Error: {e}")
        return {"hook": title, "highlights": []}

def download_font():
    """Downloads NotoSansSC (Chinese-compatible) font if not present"""
    font_path = "assets/NotoSansSC-Regular.ttf"
    os.makedirs('assets', exist_ok=True)
    if not os.path.exists(font_path):
        print("Downloading NotoSansSC font for Chinese support...")
        url = "https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            with open(font_path, 'wb') as f:
                f.write(r.content)
            print("NotoSansSC font downloaded.")
        except Exception as e:
            print(f"Failed to download NotoSansSC: {e}")
            # Fallback: try the regular weight version
            try:
                url_fallback = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/Variable/TTF/NotoSansCJKsc-VF.ttf"
                r = requests.get(url_fallback, timeout=60)
                r.raise_for_status()
                with open(font_path, 'wb') as f:
                    f.write(r.content)
                print("NotoSansCJK fallback font downloaded.")
            except Exception as e2:
                print(f"Fallback font download also failed: {e2}")
                # Last resort: try system fonts
                for sys_font in [
                    "C:/Windows/Fonts/msyh.ttc",       # Microsoft YaHei
                    "C:/Windows/Fonts/simsun.ttc",      # SimSun
                    "C:/Windows/Fonts/simhei.ttf",      # SimHei
                ]:
                    if os.path.exists(sys_font):
                        import shutil
                        shutil.copy2(sys_font, font_path)
                        print(f"Using system font: {sys_font}")
                        break
    return font_path


def _is_cjk(char):
    """Check if a character is CJK (Chinese/Japanese/Korean)"""
    cp = ord(char)
    return (0x4E00 <= cp <= 0x9FFF or    # CJK Unified Ideographs
            0x3400 <= cp <= 0x4DBF or    # CJK Extension A
            0x20000 <= cp <= 0x2A6DF or  # CJK Extension B
            0xF900 <= cp <= 0xFAFF or    # CJK Compatibility Ideographs
            0x2F800 <= cp <= 0x2FA1F)    # CJK Compatibility Supplement


def _wrap_chinese_text(text, font, max_width, draw):
    """
    Wrap text that may contain Chinese characters.
    Chinese text has no spaces between words, so we wrap character-by-character
    when no spaces are available, and at spaces when possible.
    """
    lines = []

    # First, split by explicit newlines
    paragraphs = text.split('\n')

    for paragraph in paragraphs:
        if not paragraph.strip():
            lines.append([])
            continue

        # Try splitting by spaces first (handles mixed Chinese/English)
        words = paragraph.split(' ')

        current_line = []
        current_line_width = 0
        space_width = draw.textlength(" ", font=font)

        for word in words:
            if not word:
                continue

            # Check if the word itself is too long for a line (common with Chinese)
            word_width = draw.textlength(word, font=font)

            if word_width > max_width:
                # Word is too long — need to break it character by character
                if current_line:
                    lines.append(current_line)
                    current_line = []
                    current_line_width = 0

                # Break the long word into characters
                for char in word:
                    char_width = draw.textlength(char, font=font)
                    if current_line_width + char_width > max_width:
                        if current_line:
                            lines.append(current_line)
                        current_line = [char]
                        current_line_width = char_width
                    else:
                        current_line.append(char)
                        current_line_width += char_width
            else:
                # Normal word — check if it fits
                needed = word_width + (space_width if current_line_width > 0 else 0)
                if current_line_width + needed > max_width:
                    if current_line:
                        lines.append(current_line)
                    current_line = [word]
                    current_line_width = word_width
                else:
                    current_line.append(word)
                    current_line_width += needed

        if current_line:
            lines.append(current_line)

    return lines


def create_overlay_image(headline_data, output_img_path):
    """Generates a 1080x1920 transparent image with borders, text, and logo"""
    width, height = 1080, 1920
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))  # Transparent
    draw = ImageDraw.Draw(img)

    # Draw Yellow Border around the entire frame
    border_width = 15
    draw.rectangle([0, 0, width-1, height-1], outline=(255, 255, 0, 255), width=border_width)

    # 2. Parse Text
    font_path = download_font()
    text_font = ImageFont.truetype(font_path, 70)

    hook_text = headline_data.get("hook", "").replace('\n', ' ')
    highlights = headline_data.get("highlights", [])

    max_text_width = width - 150

    # Use Chinese-aware line wrapping
    lines = _wrap_chinese_text(hook_text, text_font, max_text_width, draw)

    if len(lines) > 6:
        lines = lines[:6]
        if lines[-1]:
            lines[-1][-1] = lines[-1][-1] + "..."

    # Calculate Y start so that text sits nicely at the top
    text_y_start = 120

    # Draw Text with tight black background
    for line_words in lines:
        line_str = " ".join(line_words)
        # Calculate bounding box for the black background
        bbox = draw.textbbox((0, 0), line_str, font=text_font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]

        x_pos = (width - line_w) / 2

        # Draw Black Background Box with padding
        padding_x = 20
        padding_y = 15
        box_y1 = text_y_start - padding_y
        box_y2 = text_y_start + line_h + padding_y

        draw.rectangle(
            [x_pos - padding_x, box_y1, x_pos + line_w + padding_x, box_y2],
            fill=(0, 0, 0, 255)
        )

        # Draw text with solid yellow color
        draw.text((x_pos, text_y_start), line_str, font=text_font, fill=(255, 255, 0, 255))

        text_y_start += line_h + padding_y * 2 + 20

    # Add "热门" (Hot/Trending) at the bottom center
    news_text = "热门"
    news_font = ImageFont.truetype(font_path, 90)
    news_bbox = draw.textbbox((0, 0), news_text, font=news_font)
    news_w = news_bbox[2] - news_bbox[0]
    news_h = news_bbox[3] - news_bbox[1]

    news_x = (width - news_w) / 2
    news_y_start = height - 200

    # Draw Black Background Box for 热门
    draw.rectangle(
        [news_x - 40, news_y_start - 20, news_x + news_w + 40, news_y_start + news_h + 30],
        fill=(0, 0, 0, 255)
    )
    # Draw "热门" in yellow
    draw.text((news_x, news_y_start), news_text, font=news_font, fill=(255, 255, 0, 255))

    # 3. Draw Logo Image at Top Right (Drawn last to sit on top)
    logo_path = "assets/logo.png"
    if os.path.exists(logo_path):
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            # Scale logo to fit nicely in Top Right Corner
            scale_w = 160 / logo_img.width
            scale_h = 160 / logo_img.height
            scale = min(scale_w, scale_h)

            new_w = int(logo_img.width * scale)
            new_h = int(logo_img.height * scale)
            logo_img = logo_img.resize((new_w, new_h), Image.LANCZOS)

            # Position at Top Right Corner
            logo_y = 40
            start_x = width - new_w - 40

            img.paste(logo_img, (int(start_x), int(logo_y)), logo_img)
        except Exception as e:
            print(f"Error drawing logo: {e}")
            pass

    img.save(output_img_path)

def get_video_duration(video_path):
    try:
        probe = ffmpeg.probe(video_path)
        return float(probe['format']['duration'])
    except Exception as e:
        print(f"Error getting duration: {e}")
        return 0

def edit_video(input_vid_path, overlay_img_path, output_vid_path):
    """Composites the raw video onto a 1080x1920 black background and applies the transparent overlay"""
    print("Compositing video...")
    try:
        # Base black canvas (optional now since we are full screen, but good for safety)
        base = ffmpeg.input('color=c=black:s=1080x1920', f='lavfi')

        # Raw video
        vid = ffmpeg.input(input_vid_path)

        # Overlay image
        overlay = ffmpeg.input(overlay_img_path)

        # Scale and crop the video to 1080x1920 to fit exactly inside full screen
        scaled_vid = vid.video.filter('scale', 1080, 1920, force_original_aspect_ratio='increase').filter('crop', 1080, 1920)

        # Overlay the scaled video onto the base
        vid_on_base = ffmpeg.overlay(base, scaled_vid, x=0, y=0, shortest=1)

        # Then overlay the transparent Pillow image (text) on top
        final = ffmpeg.overlay(vid_on_base, overlay, x=0, y=0)

        # Output with audio (no duration trim limit)
        out = ffmpeg.output(final, vid.audio, output_vid_path, vcodec='libx264', acodec='aac', crf=28, preset='fast')

        ffmpeg.run(out, overwrite_output=True, quiet=True)
        print("Video editing completed.")

        duration = get_video_duration(output_vid_path)
        print(f"Final video duration: {duration:.2f} seconds")

        return True
    except Exception as e:
        print(f"Error during video editing: {e}")
        return False

def process_video(video_data):
    print("Starting Agent 2: Video Editor")

    raw_video_path = video_data.get('local_path', "workspace/raw_video.mp4")
    title = video_data.get('title', 'Unknown Video')
    overlay_path = "workspace/overlay.png"
    edited_video_path = f"workspace/edited_{video_data.get('id', 'video')}.mp4"

    if not os.path.exists(raw_video_path):
        print(f"Raw video not found at {raw_video_path}.")
        video_data["editing_status"] = "Failed"
        return video_data

    print(f"Processing video: {title}")

    headline_data = generate_headline(title)
    headline_text = headline_data.get("hook", "")
    print(f"Generated Headline: {headline_text}")

    create_overlay_image(headline_data, overlay_path)

    if edit_video(raw_video_path, overlay_path, edited_video_path):
        video_data["editing_status"] = "Success"
        video_data["seo_title"] = headline_text
        video_data["edited_path"] = edited_video_path

        # Cleanup intermediate files
        if os.path.exists(raw_video_path): os.remove(raw_video_path)
        if os.path.exists(overlay_path): os.remove(overlay_path)
        return video_data
    else:
        video_data["editing_status"] = "Failed"
        print("Editing failed.")
        return video_data

if __name__ == "__main__":
    pass
