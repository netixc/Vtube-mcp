"""
Agent-Zero VTube Audio Integration (Simple Version)

Works without pydub - generates dummy volume data for lip-sync.
"""

import asyncio
import aiohttp
import json
import base64
import re
from openai import OpenAI
import os
import wave
import struct


class Config:
    # Agent-Zero
    AGENT_ZERO_URL = "http://192.168.50.67:50006"
    
    # Your TTS (same as working example)
    TTS_MODEL = "kokoro"
    TTS_BASE_URL = 'http://192.168.50.60:8880/v1'
    TTS_VOICE = "af_sky+af_bella"
    
    # VTube API
    VTUBE_API_URL = "http://192.168.50.67:12393"
    
    # Debug
    DEBUG = True


def debug_print(message):
    if Config.DEBUG:
        print(f"\033[90m[DEBUG] {message}\033[0m", flush=True)


class AgentZeroVTubeAudio:
    """Connects Agent-Zero to VTube using audio approach"""
    
    def __init__(self):
        # TTS client
        self.tts_client = OpenAI(
            api_key="not-needed",
            base_url=Config.TTS_BASE_URL
        )
        
        # Agent-Zero state
        self.context_id = None
        self.last_message_count = 0
        self.last_response = ""
        
    def add_emotion_tags(self, text: str) -> str:
        """Add emotion tags if not present"""
        if re.search(r'\[(joy|sadness|anger|surprise|fear|neutral|smirk)\]', text):
            return text
        
        # Simple emotion detection
        emotion = "[neutral]"
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["hello", "hi", "great", "wonderful", "happy"]):
            emotion = "[joy]"
        elif any(word in text_lower for word in ["sorry", "unfortunately", "sad"]):
            emotion = "[sadness]"
        elif any(word in text_lower for word in ["error", "failed", "problem"]):
            emotion = "[anger]"
        elif any(word in text_lower for word in ["wow", "amazing", "incredible"]):
            emotion = "[surprise]"
        elif any(word in text_lower for word in ["hmm", "think", "consider"]):
            emotion = "[smirk]"
        
        return f"{emotion} {text}"
    
    def clean_text_for_tts(self, text: str) -> str:
        """Remove emotion tags for TTS"""
        cleaned = re.sub(r'\[\w+\]', '', text)
        cleaned = ' '.join(cleaned.split())
        return cleaned.strip()
    
    async def generate_audio(self, text: str) -> bytes:
        """Generate audio using your TTS"""
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
            debug_print(f"TTS error: {e}")
            return None
    
    def calculate_volumes_simple(self, audio_data: bytes) -> list:
        """Simple volume calculation without pydub"""
        try:
            # Get audio duration from WAV header
            import io
            audio_file = io.BytesIO(audio_data)
            
            # Read WAV header
            with wave.open(audio_file, 'rb') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                duration_ms = (frames / rate) * 1000
                
            # Generate dummy volumes (20ms chunks)
            chunk_count = int(duration_ms / 20)
            
            # Create a simple volume pattern
            volumes = []
            for i in range(chunk_count):
                # Simple pattern: varies between 0.3 and 0.8
                volume = 0.5 + 0.3 * abs((i % 20) - 10) / 10
                volumes.append(volume)
            
            return volumes
            
        except Exception as e:
            debug_print(f"Volume calculation error: {e}")
            # Return default volumes for ~2 seconds
            return [0.5] * 100
    
    async def send_to_vtube(self, text: str, audio_data: bytes) -> bool:
        """Send audio to VTube"""
        try:
            # Calculate volumes
            volumes = self.calculate_volumes_simple(audio_data)
            
            # Prepare payload
            payload = {
                "type": "external_audio",
                "audio": base64.b64encode(audio_data).decode('utf-8'),
                "volumes": volumes,
                "slice_length": 20,
                "display_text": {
                    "text": text,  # With emotion tags
                    "duration": len(volumes) * 0.02  # 20ms per chunk
                },
                "source": "agent_zero_integration"
            }
            
            # Send to VTube
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{Config.VTUBE_API_URL}/api/external_audio",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        print(f"✓ Sent to VTube: {text[:60]}...")
                        return True
                    else:
                        error = await response.text()
                        debug_print(f"VTube error: {error}")
                        return False
                        
        except Exception as e:
            debug_print(f"Send error: {e}")
            return False
    
    async def get_agent_zero_messages(self):
        """Get messages from Agent-Zero"""
        try:
            async with aiohttp.ClientSession() as session:
                # Get or create context
                if not self.context_id:
                    debug_print(f"Getting contexts from {Config.AGENT_ZERO_URL}/api/contexts")
                    async with session.get(f"{Config.AGENT_ZERO_URL}/api/contexts") as resp:
                        debug_print(f"Contexts response: {resp.status}")
                        if resp.status == 200:
                            contexts = await resp.json()
                            debug_print(f"Contexts data: {contexts}")
                            
                            if contexts and isinstance(contexts, list) and len(contexts) > 0:
                                # Try different possible field names
                                self.context_id = (contexts[-1].get("id") or 
                                                 contexts[-1].get("context_id") or
                                                 contexts[-1].get("contextId"))
                                debug_print(f"Found context ID: {self.context_id}")
                            else:
                                debug_print("No contexts found")
                
                if not self.context_id:
                    return []
                
                # Get messages
                url = f"{Config.AGENT_ZERO_URL}/api/contexts/{self.context_id}/messages"
                debug_print(f"Getting messages from {url}")
                
                async with session.get(url) as resp:
                    debug_print(f"Messages response: {resp.status}")
                    if resp.status == 200:
                        messages = await resp.json()
                        debug_print(f"Got {len(messages) if isinstance(messages, list) else 0} messages")
                        return messages if isinstance(messages, list) else []
                    else:
                        error_text = await resp.text()
                        debug_print(f"Error getting messages: {error_text}")
                        
        except Exception as e:
            debug_print(f"Agent-Zero error: {type(e).__name__}: {e}")
        
        return []
    
    async def monitor_agent_zero(self):
        """Monitor Agent-Zero and send to VTube"""
        print("\nMonitoring Agent-Zero for responses...")
        print("Chat with Agent-Zero and responses will appear on VTube!\n")
        
        # Initial check
        print("Checking Agent-Zero connection...")
        initial_messages = await self.get_agent_zero_messages()
        if self.context_id:
            print(f"✓ Found context: {self.context_id}")
            print(f"✓ Current messages: {len(initial_messages)}")
        else:
            print("⚠️  No context found. Chat with Agent-Zero to create one.")
        print()
        
        check_counter = 0
        
        while True:
            try:
                check_counter += 1
                if check_counter % 10 == 0:  # Every 10 seconds
                    debug_print(f"Still monitoring... (checks: {check_counter})")
                
                messages = await self.get_agent_zero_messages()
                
                # Debug: Show when we get new messages
                if len(messages) != self.last_message_count:
                    debug_print(f"Message count changed: {self.last_message_count} → {len(messages)}")
                
                if len(messages) > self.last_message_count:
                    # Process new messages
                    for msg in messages[self.last_message_count:]:
                        debug_print(f"New message: role={msg.get('role')}, content_length={len(msg.get('content', ''))}")
                        
                        if msg.get("role") == "assistant":
                            content = msg.get("content", "").strip()
                            
                            if content and content != self.last_response:
                                self.last_response = content
                                
                                # Add emotions
                                text_with_emotions = self.add_emotion_tags(content)
                                
                                # Generate audio
                                print(f"\nAgent-Zero: {text_with_emotions}")
                                print("Generating audio...")
                                
                                audio_data = await self.generate_audio(text_with_emotions)
                                
                                if audio_data:
                                    # Send to VTube
                                    await self.send_to_vtube(text_with_emotions, audio_data)
                                else:
                                    print("Failed to generate audio")
                        else:
                            debug_print(f"Skipping {msg.get('role')} message")
                    
                    self.last_message_count = len(messages)
                
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                await asyncio.sleep(2)
    
    async def test_vtube(self):
        """Test VTube connection"""
        print("Testing VTube connection...")
        
        test_text = "[joy] Hello! Agent-Zero is now connected to VTube!"
        audio_data = await self.generate_audio(test_text)
        
        if audio_data:
            success = await self.send_to_vtube(test_text, audio_data)
            if success:
                print("✓ VTube test successful!\n")
                await asyncio.sleep(3)  # Give time to see the test
                return True
        
        print("✗ VTube test failed!\n")
        return False
    
    async def run(self):
        """Run the integration"""
        print("\n=== Agent-Zero → VTube Audio Integration ===")
        print("\nThis integration:")
        print("• Monitors Agent-Zero for responses")
        print("• Generates audio with your TTS")
        print("• Sends to VTube with emotions")
        print("• Works with all connected browsers!")
        
        print(f"\nUsing:")
        print(f"• Agent-Zero: {Config.AGENT_ZERO_URL}")
        print(f"• TTS: {Config.TTS_MODEL} at {Config.TTS_BASE_URL}")
        print(f"• VTube: {Config.VTUBE_API_URL}")
        
        print("\nMake sure:")
        print("1. VTube is running")
        print("2. Browser is open at http://192.168.50.67:12393")
        print("3. Agent-Zero is running\n")
        
        # Test VTube
        if not await self.test_vtube():
            print("Make sure VTube is running!")
            return
        
        # Start monitoring
        try:
            await self.monitor_agent_zero()
        except KeyboardInterrupt:
            print("\n\nShutting down...")


async def main():
    integration = AgentZeroVTubeAudio()
    await integration.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")


"""
This simplified version:
1. Works without pydub (Python 3.13 compatible)
2. Generates simple volume data for lip-sync
3. Uses the same approach as your working example
4. Should work with all browsers!
"""