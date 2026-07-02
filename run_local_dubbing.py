import os
import sys
import subprocess
from unittest import mock

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from logger import logger
from translator import translate_video

def create_sample_video(path, duration=20):
    """Generates a vertical sample video simulating a Chinese reel (20 seconds)"""
    logger.info(f"Generating sample vertical video at {path} ({duration}s)...")
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'testsrc=duration={duration}:size=1080x1920:rate=25',
        '-f', 'lavfi', '-i', f'sine=frequency=500:duration={duration}',
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-pix_fmt', 'yuv420p',
        path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    logger.info("Sample video generated.")

def mock_generate_segment_tts(text, voice, output_path):
    """Generates a mock TTS segment audio file using FFmpeg (880Hz tone)"""
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=4',
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return True

def main():
    input_path = "sample_chinese_video.mp4"
    output_dir = "local_output"
    final_output = "output_dubbed_reel.mp4"
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Create a dummy Chinese video of 20 seconds
    create_sample_video(input_path, duration=20)
    
    # Simulating 3 voice segments in the Chinese video
    mock_segments = [
        {'start': 2.0, 'end': 5.0, 'text': '你好，欢迎收看今天的视频。'},
        {'start': 7.0, 'end': 11.0, 'text': '我们演示了先进的语音克隆和视频对齐。'},
        {'start': 13.0, 'end': 17.0, 'text': '最后，双语字幕已成功烧录。'}
    ]
    
    mock_translations = [
        {'start': 2.0, 'end': 5.0, 'chinese': '你好，欢迎收看今天的视频。', 'english': 'Hello everyone, welcome to today\'s viral video.'},
        {'start': 7.0, 'end': 11.0, 'chinese': '我们演示了先进的语音克隆和视频对齐。', 'english': 'We are showcasing advanced voice preservation and precise video alignment.'},
        {'start': 13.0, 'end': 17.0, 'chinese': '最后，双语字幕已成功烧录。', 'english': 'Finally, the bilingual subtitles are successfully burned in.'}
    ]
    
    logger.info("Starting local editing and synchronization pipeline...")
    
    # Patch Whisper and Translation APIs to perform local offline mock execution
    with mock.patch('translator.transcribe_chinese_audio', return_value=mock_segments), \
         mock.patch('translator.translate_segments_to_english', return_value=mock_translations), \
         mock.patch('translator.generate_segment_tts', side_effect=mock_generate_segment_tts):
         
         result = translate_video(
             input_path,
             output_dir=output_dir,
             burn_subtitles=True,
             subtitle_language='dual'
         )
         
         if result and result.get('english_video') and os.path.exists(result['english_video']):
             # Move output to output_dubbed_reel.mp4
             import shutil
             shutil.copy2(result['english_video'], final_output)
             logger.info(f"Successfully edited video and saved to local file: {final_output}")
             
             # Cleanup intermediate files
             if os.path.exists(input_path): os.remove(input_path)
             if os.path.exists(output_dir): shutil.rmtree(output_dir)
             
             print("\n" + "="*50)
             print("SUCCESS: Locally edited video saved successfully!")
             print(f"File Path: {os.path.abspath(final_output)}")
             print("="*50 + "\n")
         else:
             logger.error("Failed to edit video locally.")

if __name__ == '__main__':
    main()
