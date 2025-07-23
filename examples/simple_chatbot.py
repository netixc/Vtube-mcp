"""
Simple VTube API - Direct Control Approach

This sends audio directly to VTube's external_audio endpoint.
VTube handles lip-sync and expressions, but you control the TTS.
"""

import asyncio
import aiohttp
import json
from openai import OpenAI
import os
import tempfile
from pathlib import Path
import base64
from pydub import AudioSegment
from pydub.utils import make_chunks
class Config:
    # Your LLM
    MODEL_NAME = "openai/gpt-4o-mini"
    BASE_URL_CHAT = 'https://openrouter.ai/api/v1'
    MAX_TOKENS = 150
    
    # VTube API
    VTUBE_API_URL = "http://192.168.50.67:12393/api/external_audio"
    
    # Your TTS Configuration (from VTube config)
    TTS_MODEL = 'kokoro'
    TTS_VOICE = 'af_sky+af_bella'
    TTS_API_KEY = 'not-needed'
    TTS_BASE_URL = 'http://192.168.50.60:8880/v1'
    TTS_FILE_EXT = 'mp3'

class SimpleChatbot:
    """Direct API approach - you control everything"""
    
    def __init__(self):
        self.llm_client = None
        self.conversation_history = []
        self.setup_llm()
        
    def setup_llm(self):
        """Setup your external LLM"""
        api_key = os.environ.get('OPENROUTER_API_KEY')
        if not api_key:
            print("\n❌ ERROR: OPENROUTER_API_KEY environment variable not set!")
            print("\nTo fix this, run:")
            print("export OPENROUTER_API_KEY='your-api-key-here'")
            print("\nOr add it to your .env file")
            exit(1)
            
        self.llm_client = OpenAI(
            base_url=Config.BASE_URL_CHAT,
            api_key=api_key
        )
        
        # System prompt with emotions
        self.conversation_history = [{
            "role": "system",
            "content": """You are an AI assistant with emotions.
Include emotion tags in square brackets: [joy], [sadness], [anger], [surprise], [fear], [neutral], [smirk].
Examples:
- "[joy] I'm so happy to help you!"
- "[surprise] Wow! [joy] That's amazing!"
Keep responses concise and expressive."""
        }]
    
    async def generate_tts(self, text: str) -> str:
        """Generate TTS audio using your OpenAI-compatible TTS server"""
        # Create temp file for audio
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{Config.TTS_FILE_EXT}')
        temp_path = temp_file.name
        temp_file.close()
        
        # Use OpenAI client to connect to your TTS server
        tts_client = OpenAI(
            api_key=Config.TTS_API_KEY,
            base_url=Config.TTS_BASE_URL
        )
        
        # Generate audio using your TTS server
        response = tts_client.audio.speech.create(
            model=Config.TTS_MODEL,
            voice=Config.TTS_VOICE,
            input=text
        )
        
        # Save the audio properly
        with open(temp_path, 'wb') as f:
            f.write(response.content)
        
        return temp_path
    
    def extract_emotions(self, text: str) -> list:
        """Extract emotion tags from text"""
        emotions = []
        # Shizuku model emotion mapping from model_dict.json
        emotion_map = {
            '[neutral]': 0,
            '[fear]': 1,
            '[sadness]': 1,
            '[anger]': 2, 
            '[disgust]': 2,
            '[joy]': 3,
            '[smirk]': 3,
            '[surprise]': 3
        }
        
        for tag, index in emotion_map.items():
            if tag in text.lower():
                emotions.append(index)
        
        return emotions
    
    def clean_text(self, text: str) -> str:
        """Remove emotion tags from text for TTS"""
        clean = text
        tags = ['[joy]', '[anger]', '[sadness]', '[surprise]', '[fear]', '[neutral]', '[smirk]']
        for tag in tags:
            clean = clean.replace(tag, '').replace(tag.upper(), '')
        return clean.strip()
    
    def calculate_lip_sync_volumes(self, audio_path: str) -> list:
        """Calculate volume levels for lip-sync animation"""
        # Load audio file
        audio = AudioSegment.from_file(audio_path)
        
        # Calculate RMS volumes for 20ms chunks (standard for lip-sync)
        chunk_length_ms = 20
        chunks = make_chunks(audio, chunk_length_ms)
        volumes = []
        
        for chunk in chunks:
            # Get RMS (root mean square) volume
            rms = chunk.rms
            volumes.append(rms)
        
        # Normalize volumes to 0-1 range
        if volumes:
            max_volume = max(volumes)
            if max_volume > 0:
                volumes = [v / max_volume for v in volumes]
        
        return volumes

    async def send_to_vtube(self, audio_path: str, text: str, emotions: list):
        """Send audio to VTube with emotions"""
        # Check file exists
        if not os.path.exists(audio_path):
            print(f"Error: Audio file not found at {audio_path}")
            return
            
        # Read and encode audio as base64
        with open(audio_path, 'rb') as f:
            audio_data = f.read()
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        # Calculate lip-sync volumes
        volumes = self.calculate_lip_sync_volumes(audio_path)
        print(f"Calculated {len(volumes)} volume samples for lip-sync")
        
        # Prepare the JSON payload (matching VTube's expected format)
        payload = {
            "audio": audio_base64,
            "volumes": volumes,
            "display_text": {
                "text": text,
                "duration": len(volumes) * 0.02  # 20ms per chunk
            },
            "actions": {
                "expressions": emotions
            }
        }
        
        print(f"Sending emotions: {emotions}")
        
        # Send to VTube
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    Config.VTUBE_API_URL, 
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    result_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            result = json.loads(result_text)
                            print(f"VTube response: {result.get('status', 'unknown')}")
                            if result.get('status') == 'error':
                                print(f"VTube error: {result.get('message', 'Unknown error')}")
                        except json.JSONDecodeError:
                            print(f"Could not parse VTube response: {result_text}")
                    else:
                        print(f"HTTP error {response.status}: {result_text}")
            except Exception as e:
                print(f"Error connecting to VTube: {e}")
    
    async def chat(self, user_input: str):
        """Process a chat message"""
        print(f"\nYou: {user_input}")
        
        # 1. Generate response with LLM
        self.conversation_history.append({"role": "user", "content": user_input})
        
        response = self.llm_client.chat.completions.create(
            model=Config.MODEL_NAME,
            messages=self.conversation_history,
            max_tokens=Config.MAX_TOKENS,
            temperature=0.7
        )
        
        ai_response = response.choices[0].message.content
        print(f"AI: {ai_response}")
        
        # 2. Extract emotions
        emotions = self.extract_emotions(ai_response)
        clean_text = self.clean_text(ai_response)
        
        # 3. Generate TTS
        print("Generating audio...")
        audio_path = await self.generate_tts(clean_text)
        
        # 4. Send to VTube
        print("Sending to VTube...")
        await self.send_to_vtube(audio_path, ai_response, emotions)
        
        # Cleanup
        os.unlink(audio_path)
        
        # Save to history
        self.conversation_history.append({
            "role": "assistant",
            "content": ai_response
        })
    
    async def run(self):
        """Run the chatbot"""
        print("\n=== Simple VTube API Chatbot ===")
        print("\nThis version:")
        print("✓ YOUR LLM for responses (OpenRouter)")
        print(f"✓ YOUR TTS (Kokoro at {Config.TTS_BASE_URL})")
        print("✓ VTube for display only")
        print("\nMake sure:")
        print("1. VTube is running")
        print("2. Open browser at http://192.168.50.67:12393")
        print("\nChat with your avatar! Type 'exit' to quit.\n")
        
        try:
            while True:
                user_input = input("\nYou: ").strip()
                
                if user_input.lower() in ["exit", "quit", "bye"]:
                    await self.chat("[sadness] Goodbye! Take care!")
                    await asyncio.sleep(3)
                    break
                
                if user_input:
                    await self.chat(user_input)
                    
        except KeyboardInterrupt:
            print("\nExiting...")

async def main():
    chatbot = SimpleChatbot()
    await chatbot.run()

if __name__ == "__main__":
    asyncio.run(main())

"""
This approach:
1. Uses YOUR LLM (OpenRouter)
2. Uses YOUR TTS (Kokoro at http://192.168.50.60:8880)
3. Sends audio directly to VTube's external_audio endpoint
4. VTube displays the avatar with lip-sync and expressions

The TTS configuration is taken from your VTube config:
- Model: kokoro
- Voice: af_sky+af_bella
- Server: http://192.168.50.60:8880/v1
"""