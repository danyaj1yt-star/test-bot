import requests
import time
import os
import tempfile
from typing import Optional

# AssemblyAI API settings
ASSEMBLYAI_API_KEY = "3e3eebf57daf4aaea8453bcf5c480674"
ASSEMBLYAI_BASE_URL = "https://api.assemblyai.com"

HEADERS = {
    "authorization": ASSEMBLYAI_API_KEY
}


async def download_voice_file(bot, file_id: str) -> Optional[str]:
    """
    Downloads a voice file from Telegram and saves it temporarily
    Returns the path to the temporary file or None on error
    """
    try:
        # Get file info from Telegram
        file_info = await bot.get_file(file_id)
        
        # Download file
        file_bytes = await bot.download_file(file_info.file_path)
        
        # Save to temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
        temp_file.write(file_bytes.read())
        temp_file.close()
        
        return temp_file.name
    except Exception as e:
        print(f"❌ Error downloading voice file: {e}")
        return None


def upload_file_to_assemblyai(file_path: str) -> Optional[str]:
    """
    Uploads a local audio file to AssemblyAI
    Returns the upload URL or None on error
    """
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                ASSEMBLYAI_BASE_URL + "/v2/upload",
                headers=HEADERS,
                data=f
            )
        
        if response.status_code == 200:
            return response.json()["upload_url"]
        else:
            print(f"❌ Upload failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error uploading file: {e}")
        return None


def transcribe_audio(audio_url: str) -> Optional[str]:
    """
    Transcribes audio from the given URL using AssemblyAI
    Returns the transcribed text or None on error
    """
    try:
        # Start transcription with language detection enabled
        data = {
            "audio_url": audio_url,
            "speech_model": "best",
            "language_detection": True
        }
        
        response = requests.post(
            ASSEMBLYAI_BASE_URL + "/v2/transcript",
            json=data,
            headers=HEADERS
        )
        
        if response.status_code != 200:
            print(f"❌ Transcription request failed: {response.status_code} - {response.text}")
            return None
        
        transcript_id = response.json()['id']
        polling_endpoint = ASSEMBLYAI_BASE_URL + "/v2/transcript/" + transcript_id
        
        # Poll for completion
        max_attempts = 60  # Maximum 3 minutes (60 * 3 seconds)
        attempts = 0
        
        while attempts < max_attempts:
            transcription_result = requests.get(polling_endpoint, headers=HEADERS).json()
            
            if transcription_result['status'] == 'completed':
                return transcription_result.get('text', '')
            
            elif transcription_result['status'] == 'error':
                error_msg = transcription_result.get('error', 'Unknown error')
                print(f"❌ Transcription failed: {error_msg}")
                return None
            
            else:
                # Still processing
                time.sleep(3)
                attempts += 1
        
        print(f"❌ Transcription timeout after {max_attempts * 3} seconds")
        return None
        
    except Exception as e:
        print(f"❌ Error during transcription: {e}")
        return None


async def transcribe_voice_message(bot, file_id: str) -> Optional[str]:
    """
    Complete pipeline: download voice message, upload to AssemblyAI, and transcribe
    Returns the transcribed text or None on error
    """
    print(f"🎙️ transcribe_voice_message called with file_id: {file_id}")
    temp_file = None
    try:
        # Download voice file
        print(f"🎙️ Downloading voice file...")
        temp_file = await download_voice_file(bot, file_id)
        if not temp_file:
            print(f"❌ Failed to download voice file")
            return None
        print(f"✅ Voice file downloaded: {temp_file}")
        
        # Upload to AssemblyAI
        print(f"🎙️ Uploading to AssemblyAI...")
        audio_url = upload_file_to_assemblyai(temp_file)
        if not audio_url:
            print(f"❌ Failed to upload to AssemblyAI")
            return None
        print(f"✅ Uploaded, URL: {audio_url}")
        
        # Transcribe
        print(f"🎙️ Starting transcription...")
        transcript = transcribe_audio(audio_url)
        if transcript:
            print(f"✅ Transcription complete: {transcript[:100]}...")
        else:
            print(f"❌ Transcription failed")
        return transcript
        
    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception as e:
                print(f"⚠️ Failed to remove temp file: {e}")
