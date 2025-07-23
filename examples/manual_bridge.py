"""
Agent-Zero VTube Manual Bridge

Simple approach: Copy Agent-Zero's response and this sends it to VTube.
"""

import asyncio
import aiohttp
import json
import base64
import re
from openai import OpenAI
import sys
import wave
import io


class Config:
    # Your TTS
    TTS_MODEL = "kokoro"
    TTS_BASE_URL = 'http://192.168.50.60:8880/v1'
    TTS_VOICE = "af_sky+af_bella"
    
    # VTube API
    VTUBE_API_URL = "http://192.168.50.67:12393"


class ManualVTubeBridge:
    """Manual bridge - you paste Agent-Zero responses"""
    
    def __init__(self):
        self.tts_client = OpenAI(
            api_key="not-needed",
            base_url=Config.TTS_BASE_URL
        )
    
    def add_emotion_tags(self, text: str) -> str:
        """Add emotion tags if not present"""
        if re.search(r'\[(joy|sadness|anger|surprise|fear|neutral|smirk)\]', text):
            return text
        
        emotion = "[neutral]"
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["hello", "hi", "great", "wonderful", "happy", "excited"]):
            emotion = "[joy]"
        elif any(word in text_lower for word in ["sorry", "unfortunately", "sad", "apologize"]):
            emotion = "[sadness]"
        elif any(word in text_lower for word in ["error", "failed", "problem", "wrong"]):
            emotion = "[anger]"
        elif any(word in text_lower for word in ["wow", "amazing", "incredible", "oh my"]):
            emotion = "[surprise]"
        elif any(word in text_lower for word in ["hmm", "let me think", "consider", "perhaps"]):
            emotion = "[smirk]"
        elif any(word in text_lower for word in ["careful", "danger", "warning"]):
            emotion = "[fear]"
        
        return f"{emotion} {text}"
    
    def clean_text_for_tts(self, text: str) -> str:
        """Remove emotion tags for TTS"""
        cleaned = re.sub(r'\[\w+\]', '', text)
        return ' '.join(cleaned.split()).strip()
    
    async def generate_audio(self, text: str) -> bytes:
        """Generate audio using TTS"""
        clean_text = self.clean_text_for_tts(text)
        
        try:
            response = self.tts_client.audio.speech.create(
                model=Config.TTS_MODEL,
                voice=Config.TTS_VOICE,
                response_format="wav",
                input=clean_text
            )
            return response.content
        except Exception as e:
            print(f"TTS error: {e}")
            return None
    
    def calculate_volumes_simple(self, audio_data: bytes) -> list:
        """Simple volume calculation"""
        try:
            with wave.open(io.BytesIO(audio_data), 'rb') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                duration_ms = (frames / rate) * 1000
                
            chunk_count = int(duration_ms / 20)
            volumes = []
            for i in range(chunk_count):
                volume = 0.5 + 0.3 * abs((i % 20) - 10) / 10
                volumes.append(volume)
            
            return volumes
        except:
            return [0.5] * 100
    
    async def send_to_vtube(self, text: str) -> bool:
        """Send text to VTube with audio"""
        # Add emotions
        text_with_emotions = self.add_emotion_tags(text)
        print(f"\nProcessing: {text_with_emotions[:80]}...")
        
        # Generate audio
        print("Generating audio...")
        audio_data = await self.generate_audio(text_with_emotions)
        
        if not audio_data:
            print("Failed to generate audio!")
            return False
        
        # Calculate volumes
        volumes = self.calculate_volumes_simple(audio_data)
        
        # Send to VTube
        try:
            payload = {
                "type": "external_audio",
                "audio": base64.b64encode(audio_data).decode('utf-8'),
                "volumes": volumes,
                "slice_length": 20,
                "display_text": {
                    "text": text_with_emotions,
                    "duration": len(volumes) * 0.02
                },
                "source": "agent_zero_manual"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{Config.VTUBE_API_URL}/api/external_audio",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        print("✓ Sent to VTube successfully!")
                        return True
                    else:
                        error = await response.text()
                        print(f"✗ VTube error: {error}")
                        return False
                        
        except Exception as e:
            print(f"✗ Send error: {e}")
            return False
    
    async def run_interactive(self):
        """Interactive mode - paste responses"""
        print("\n=== Agent-Zero → VTube Manual Bridge ===")
        print("\nHow to use:")
        print("1. Chat with Agent-Zero in your browser")
        print("2. Copy the AI response")
        print("3. Paste it here")
        print("4. It will appear on VTube with emotions!\n")
        
        print("Type 'exit' to quit\n")
        
        while True:
            try:
                print("\n" + "="*50)
                user_input = input("Paste Agent-Zero response (or 'exit'): ").strip()
                
                if user_input.lower() in ["exit", "quit", "bye"]:
                    break
                
                if user_input:
                    await self.send_to_vtube(user_input)
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
        
        print("\nGoodbye!")
    
    async def run_single(self, text: str):
        """Single message mode"""
        await self.send_to_vtube(text)


async def main():
    bridge = ManualVTubeBridge()
    
    if len(sys.argv) > 1:
        # Command line mode
        text = ' '.join(sys.argv[1:])
        await bridge.run_single(text)
    else:
        # Interactive mode
        await bridge.run_interactive()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")


"""
USAGE:

Interactive mode:
    python agent_zero_vtube_manual.py

Command line mode:
    python agent_zero_vtube_manual.py "Hello, I am Agent Zero!"

This is the simplest approach - just copy/paste Agent-Zero's responses!
"""