import os
import sys
import tempfile
import subprocess
from unittest import mock

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from logger import logger
from translator import translate_video

def generate_test_video(path, duration=15):
    """Generates a vertical test video with a beep sound using FFmpeg."""
    logger.info(f"Generating test video at {path} ({duration}s)...")
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'testsrc=duration={duration}:size=1080x1920:rate=25',
        '-f', 'lavfi', '-i', f'sine=frequency=440:duration={duration}',
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-pix_fmt', 'yuv420p',
        path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    logger.info("Test video generated successfully.")

def mock_generate_segment_tts(text, voice, output_path):
    """Generates a dummy audio file using FFmpeg instead of calling external TTS APIs."""
    # Generate a 5-second audio track
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=5',
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return True

def main():
    logger.info("Starting End-to-End verification of the dubbing pipeline...")
    
    test_dir = tempfile.mkdtemp()
    input_video = os.path.join(test_dir, "input_chinese.mp4")
    output_dir = os.path.join(test_dir, "output")
    
    # 1. Generate test video (15 seconds)
    generate_test_video(input_video, duration=15)
    
    # Mock segments returned by Whisper transcription
    mock_segments = [
        {'start': 1.0, 'end': 4.0, 'text': '你好，这是一个测试视频。'},
        {'start': 6.0, 'end': 10.0, 'text': '我们正在测试自动语音合成 and 对齐。'},
        {'start': 11.0, 'end': 14.0, 'text': '非常感谢您的使用。'}
    ]
    
    # Mock translations returned by OpenAI GPT / Translator
    mock_translated_segments = [
        {'start': 1.0, 'end': 4.0, 'chinese': '你好，这是一个测试视频。', 'english': 'Hello, this is a test video for our awesome automated reels pipeline.'},
        {'start': 6.0, 'end': 10.0, 'chinese': '我们正在测试自动语音合成 and 对齐。', 'english': 'We are currently testing automated voice synthesis and lip-sync alignment.'},
        {'start': 11.0, 'end': 14.0, 'chinese': '非常感谢您的使用。', 'english': 'Thank you so much for using it.'}
    ]
    
    # Mock transcribe, translate and TTS functions to avoid external API and library dependencies
    with mock.patch('translator.transcribe_chinese_audio', return_value=mock_segments), \
         mock.patch('translator.translate_segments_to_english', return_value=mock_translated_segments), \
         mock.patch('translator.generate_segment_tts', side_effect=mock_generate_segment_tts):
        
        # Set dummy env vars for TTS
        os.environ['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY', 'dummy-key')
        os.environ['TTS_VOICE'] = 'en-US-ChristopherNeural'
        
        logger.info("Triggering translate_video pipeline...")
        result = translate_video(
            input_video,
            output_dir=output_dir,
            burn_subtitles=True,
            subtitle_language='dual'
        )
        
        if result and result.get('english_video') and os.path.exists(result['english_video']):
            final_vid = result['english_video']
            logger.info(f"Pipeline ran successfully! Output: {final_vid}")
            
            # Check final video duration
            try:
                cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', final_vid]
                dur = float(subprocess.run(cmd, capture_output=True, text=True).stdout.strip())
                logger.info(f"Final video duration is {dur:.2f} seconds.")
                assert abs(dur - 15.0) < 1.0, f"Expected duration around 15s, got {dur}"
            except Exception as e:
                logger.error(f"Validation failed: {e}")
                sys.exit(1)
            
            print("\n" + "="*50)
            print("[SUCCESS] VERIFICATION PASSED: Video dubbing & alignment completed successfully!")
            print(f"Final English Video: {final_vid}")
            print(f"Subtitles: {result['subtitles']}")
            print("="*50 + "\n")
        else:
            logger.error("Pipeline run failed or output video missing.")
            sys.exit(1)

if __name__ == '__main__':
    main()
