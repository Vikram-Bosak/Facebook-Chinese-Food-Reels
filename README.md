# 🍜 Chinese Food Reels Automation

Automated system that downloads Chinese food videos, removes Chinese speech parts, keeps cooking/serving segments, and uploads clean 9:16 vertical reels to Facebook and YouTube.

## ✨ Features

- **Chinese Food Video Discovery**: Scans Bilibili, Douyin, Kuaishou for Chinese food content
- **Smart Speech Detection**: Uses Whisper AI to detect Chinese speech segments
- **Automatic Chinese Removal**: Cuts out Chinese speaking parts, keeps cooking/serving
- **Clean 9:16 Output**: Fullscreen vertical format for Reels/Shorts
- **No Templates/Overlays**: Clean video output with no frames or overlays
- **Multi-Platform Upload**: Facebook Reels + YouTube Shorts
- **Telegram Reports**: Instant notifications
- **Duplicate Prevention**: SQLite tracking
- **GitHub Actions**: Automated scheduling

## 🎯 Content Rules

### Video Types
Only these Chinese food video types are processed:
- 🍳 **Cooking Process** (खाना बनाते हुए) — Primary content
- 🍽️ **Food Serving/Plating** (खाना सर्व करते हुए) — Primary content
- 😋 **Food Tasting** (खाना टेस्ट करते हुए) — Occasional

### Chinese Language Removal
- All Chinese speech segments are detected using Whisper AI
- Chinese speaking parts are automatically cut out
- Only non-speech cooking/serving segments are kept

### Video Editing
- ❌ NO templates, frames, or overlays
- ❌ NO Chinese text or labels
- ✅ Clean fullscreen output
- ✅ Original audio preserved (ambient cooking sounds)

### Aspect Ratio
- Final video: **9:16 vertical** (Fullscreen)
- Suitable for: Facebook Reels, Instagram Reels, YouTube Shorts

## 🛠️ Setup

### 1. Prerequisites
- Python 3.11+
- FFmpeg installed
- API keys for: OpenAI (Whisper), Facebook, YouTube, Telegram

### 2. Install
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium --with-deps
```

### 3. Configure
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Run Locally
```bash
# Process a single video
python run_pipeline.py https://www.bilibili.com/video/BV1xx411c7mD

# Run full pipeline (download → process → upload)
python main_agent.py
```

### 5. GitHub Actions
Push to GitHub, set Repository Secrets, and the workflow runs automatically.

## 📁 Project Structure
```
Facebook-Chinese-Food-Reels/
├── src/
│   ├── food_video_processor.py   # Core: speech detection + cutting + 9:16
│   ├── agent_1_downloader.py     # Video discovery & download
│   ├── agent_2_editor.py         # Food video processing wrapper
│   ├── agent_3_uploader.py       # Facebook + YouTube upload
│   ├── translator.py             # Translation pipeline (disabled)
│   ├── queue_manager.py          # Workflow with validation
│   ├── database.py               # SQLite tracking
│   └── ...
├── .github/workflows/            # GitHub Actions CI/CD
├── main_agent.py                 # Main pipeline entry
├── run_pipeline.py               # Standalone video processing
└── README.md
```

## 📊 Pipeline Flow
```
Chinese Food Video (Bilibili/Douyin/Kuaishou)
    ↓
Step 1: Download Video
    ↓
Step 2: Extract Audio + Detect Speech (Whisper)
    ↓
Step 3: Identify Chinese Speech Segments → REMOVE
    ↓
Step 4: Identify Cooking/Serving Segments → KEEP
    ↓
Step 5: Cut & Concatenate Keep Segments
    ↓
Step 6: Ensure 9:16 Vertical Format
    ↓
Clean Food Reel → Upload to Facebook & YouTube
```

## 📄 License
MIT License
