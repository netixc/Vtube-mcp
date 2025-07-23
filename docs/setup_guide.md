# Detailed Setup Guide

## Prerequisites

1. **Agent-Zero** installed and working
2. **VTube Studio** with Shizuku model
3. **Kokoro TTS** server running
4. Python 3.8+ with required packages

## Step-by-Step Installation

### 1. VTube Setup

1. Start VTube Studio
2. Load your avatar model (Shizuku recommended)
3. Enable API in settings
4. Note your VTube IP and port (default: 12393)

### 2. Kokoro TTS Setup

1. Start your Kokoro TTS server
2. Verify it's accessible at `http://your-ip:8880/v1`
3. Test with:
   ```bash
   curl http://localhost:8880/v1/models
   ```

### 3. Agent-Zero Extension Installation

1. Navigate to your Agent-Zero directory:
   ```bash
   cd /path/to/agent-zero
   ```

2. Copy the extension:
   ```bash
   cp /path/to/vtube-mcp/agent-zero-integration/vtube_extension.py \
      python/extensions/response_stream/_35_vtube_simple.py
   ```

3. Edit the extension to update your settings:
   ```python
   # Line 153: Update VTube URL
   "http://192.168.50.67:12393/api/external_audio"
   
   # Line 193: Update Kokoro TTS URL
   base_url="http://192.168.50.60:8880/v1"
   ```

4. Install required Python packages:
   ```bash
   pip install openai requests aiohttp
   ```

### 4. Testing

1. Start all services (VTube, Kokoro TTS, Agent-Zero)
2. Send a test message to Agent-Zero
3. Check VTube - the avatar should speak the response

### 5. Configuration Options

#### Emotion Keywords

Edit the `_get_emotion()` method to customize emotion detection:

```python
# Add your keywords
if any(w in text_lower for w in ["hello", "hi", "happy"]):
    return "[joy]"
```

#### TTS Voice

Change the voice in `_generate_audio()`:
```python
voice="af_sky+af_bella",  # Change to your preferred voice
```

#### Response Delay

Adjust the delay before sending (line 66):
```python
await asyncio.sleep(0.5)  # Increase for slower streaming
```

## Troubleshooting

### "No module named 'openai'"
```bash
pip install openai
```

### VTube not receiving messages
1. Check VTube console for errors
2. Verify API is enabled
3. Test with manual bridge: `python examples/manual_bridge.py`

### No audio playback
1. Check Kokoro TTS logs
2. Verify TTS is accessible
3. Test TTS directly with curl

### Duplicate messages
1. Restart Agent-Zero
2. Check only one extension file exists
3. Clear browser cache if using web UI

## Performance Tuning

- Reduce response delay for faster responses
- Adjust volume levels in `_send_to_vtube()`
- Modify emotion keywords for your use case

## Advanced Configuration

### Custom Emotions

Add new emotions to the mapping:
```python
emotion_map = {
    '[neutral]': 0,
    '[fear]': 1,
    '[sadness]': 1,
    '[anger]': 2,
    '[joy]': 3,
    '[custom]': 4,  # Add your custom emotion
}
```

### Multiple TTS Servers

To use different TTS servers:
```python
self.tts_base_url = os.getenv("KOKORO_URL", "http://localhost:8880/v1")
```

Then set environment variable:
```bash
export KOKORO_URL=http://your-tts:8880/v1
```