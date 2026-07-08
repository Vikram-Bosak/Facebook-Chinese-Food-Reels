# 🍜 Chinese Food Reels Automation

Automated system that downloads Chinese food videos from **10 curated profiles**, removes Chinese speech, keeps only cooking/serving segments, and uploads clean 9:16 vertical reels.

## ✨ Features

- **10 Curated Profiles**: Only download from specific Chinese food channels
- **Content Filter**: Only cooking process and food serving/plating videos
- **Smart Speech Detection**: Whisper AI detects Chinese speech segments
- **Automatic Chinese Removal**: Cuts out Chinese speaking parts
- **Clean 9:16 Output**: Fullscreen vertical format — NO templates, NO overlays
- **Sound Effects + BGM Only**: No Chinese speech in final video
- **Multi-Platform Upload**: Facebook Reels + YouTube Shorts
- **Telegram Reports**: Instant notifications

## 🎯 Content Rules (STRICT)

### Only 2 Types of Videos Allowed

| Type | Status |
|---|---|
| 🍳 **Cooking Process** (खाना बनाते हुए) | ✅ ACCEPT |
| 🍽️ **Food Serving/Plating** (खाना सर्व करते हुए) | ✅ ACCEPT |
| 😋 Food Tasting (खाना टेस्ट) | ❌ REJECT |
| 🍔 Mukbang/Challenge | ❌ REJECT |
| 📝 Review/测评 | ❌ REJECT |

### Chinese Speech Removal
- Whisper AI detects all Chinese speech timestamps
- Chinese speaking parts are automatically cut out
- Only non-speech cooking/serving segments are kept

### Clean Output
- ❌ NO templates, frames, or overlays
- ❌ NO Chinese text or labels
- ✅ Clean fullscreen 9:16 vertical video
- ✅ Sound effects + background music only

## 📁 Curated Profiles

10 specific Bilibili profiles that post cooking/serving content:

| # | Profile | Content |
|---|---|---|
| 1 | 美食作家王刚 | Cooking |
| 2 | 麻辣德子 | Cooking |
| 3 | 蜀中桃子姐 | Cooking |
| 4 | 农村小翔哥 | Cooking |
| 5 | 品美食的阿飞 | Cooking |
| 6 | 美食台 | Both |
| 7 | 老饭骨 | Cooking |
| 8 | 日食记 | Both |
| 9 | 大漠叔叔 | Cooking |
| 10 | 厨房里的艺术家 | Both |

Profiles are configured in `src/curated_profiles.json`.

## 🛠️ Setup

### 1. Prerequisites
- Python 3.11+
- FFmpeg installed
- API keys: OpenAI (Whisper), Facebook, YouTube, Telegram

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

### 4. Run
```bash
# Full pipeline (download from profiles → process → upload)
python main_agent.py

# Process a single video
python run_pipeline.py https://www.bilibili.com/video/BV1xx411c7mD
```

## 📊 Pipeline Flow
```
Curated Profiles (10 specific channels)
    ↓
Step 1: Fetch latest videos from profiles
    ↓
Step 2: Content Filter (only cooking/serving)
    ↓
Step 3: Download video
    ↓
Step 4: Detect Chinese speech (Whisper)
    ↓
Step 5: Cut out Chinese speaking parts
    ↓
Step 6: Keep cooking/serving segments
    ↓
Step 7: Ensure 9:16 vertical format
    ↓
Clean Food Reel → Upload to Facebook & YouTube
```

## 📁 Project Structure
```
Facebook-Chinese-Food-Reels/
├── src/
│   ├── food_video_processor.py    # Core: speech detection + cutting + 9:16
│   ├── curated_profiles.json      # 10 specific food channels
│   ├── agent_1_downloader.py      # Profile-based video discovery
│   ├── agent_2_editor.py          # Food video processing wrapper
│   ├── agent_3_uploader.py        # Facebook + YouTube upload
│   └── ...
├── .github/workflows/             # GitHub Actions CI/CD
├── main_agent.py                  # Main pipeline entry
├── run_pipeline.py                # Standalone video processing
└── README.md
```

## 📄 License
MIT License
