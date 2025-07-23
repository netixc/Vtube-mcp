# External Audio Integration for VTube

## Overview

This document describes the changes made to VTube to support external audio sources with lip-sync data. These changes allow external applications (like chatbots) to send pre-generated audio with lip-sync information to VTube for playback and avatar animation.

## Changes Made

### 1. Modified `/src/open_llm_vtuber/routes.py`

#### Added Import
```python
from fastapi import Request  # Added to existing imports
```

#### Added New Endpoint
Added a new POST endpoint `/api/external_audio` to receive audio from external sources:

```python
@router.post("/api/external_audio")
async def receive_external_audio(request: Request):
    """
    Receive audio with lip-sync data from external sources (like chatbots).
    
    This endpoint allows external applications to send audio with lip-sync data
    that will be broadcast to all connected VTube clients.
    """
```

## API Specification

### Endpoint
`POST /api/external_audio`

### Request Format
```json
{
    "type": "external_audio",
    "audio": "base64_encoded_wav_string",
    "volumes": [0.1, 0.5, 0.8, ...],  // Normalized RMS values (0-1)
    "slice_length": 20,                // Milliseconds per chunk
    "display_text": {
        "text": "Hello world",
        "duration": 2.5                // Duration in seconds
    },
    "actions": {                      // Optional: Live2D expressions
        "expressions": [3]            // Expression indices (e.g., 3 = joy)
    },
    "source": "chatbot"               // Identifies the source
}
```

### Response Format

#### Success Response
```json
{
    "status": "success",
    "message": "Audio sent to 1/1 clients",
    "clients_total": 1,
    "clients_success": 1
}
```

#### Error Responses
```json
{
    "status": "error",
    "message": "Missing audio data"
}
```

```json
{
    "status": "warning",
    "message": "No clients connected"
}
```

## How It Works

1. **External Application** generates audio with TTS
2. **Audio Processing** calculates volume levels for lip-sync (20ms chunks)
3. **Expression Detection** (optional) extracts emotions from text
4. **HTTP POST** sends audio + volumes + expressions to `/api/external_audio`
5. **VTube Server** receives and validates the data
6. **WebSocket Broadcast** sends to all connected browser clients
7. **Live2D Animation** uses volume data for mouth movements and expression indices for facial expressions

## Expression Support

### Expression Indices (for shizuku model)
```json
{
    "neutral": 0,
    "anger": 2,
    "disgust": 2,
    "fear": 1,
    "joy": 3,
    "smirk": 3,
    "sadness": 1,
    "surprise": 3
}
```

### Including Expressions
To show expressions with your audio:
```json
"actions": {
    "expressions": [3]     // Single expression (joy)
    // or
    "expressions": [0, 3]  // Multiple expressions in sequence
}
```

## Integration Example

```python
import requests
import base64
from pydub import AudioSegment
from pydub.utils import make_chunks

# Generate audio (example with OpenAI TTS)
audio_data = generate_tts("Hello world")  # Returns WAV bytes

# Calculate lip-sync volumes
audio = AudioSegment.from_wav(io.BytesIO(audio_data))
chunks = make_chunks(audio, 20)  # 20ms chunks
volumes = [chunk.rms for chunk in chunks]
max_vol = max(volumes)
volumes = [v/max_vol for v in volumes]  # Normalize to 0-1

# Create payload
payload = {
    "type": "external_audio",
    "audio": base64.b64encode(audio_data).decode('utf-8'),
    "volumes": volumes,
    "slice_length": 20,
    "display_text": {
        "text": "Hello world",
        "duration": len(audio) / 1000.0
    },
    "source": "my_chatbot"
}

# Send to VTube
response = requests.post(
    "http://localhost:12393/api/external_audio",
    json=payload
)
```

## Benefits

1. **Flexible TTS** - Use any TTS engine or service
2. **External Control** - Control VTube from external applications
3. **No Double Audio** - Bypass VTube's built-in TTS
4. **Consistent Voice** - Use your preferred voice/model
5. **Scalability** - Can handle multiple external sources

## Security Considerations

For production use, consider:
- Adding authentication (API keys, JWT tokens)
- Rate limiting to prevent abuse
- Input validation for audio size limits
- CORS configuration for web security

## Backward Compatibility

These changes are fully backward compatible:
- Existing VTube functionality remains unchanged
- The new endpoint is optional
- No changes to existing WebSocket protocol
- No changes to frontend code required

## Testing

To test the integration:

1. Start VTube server:
   ```bash
   cd /root/avatar/Vtube-mcp
   uv run python run_server.py
   ```

2. Open VTube in browser (http://localhost:12393)

3. Send test audio:
   ```bash
   curl -X POST http://localhost:12393/api/external_audio \
     -H "Content-Type: application/json" \
     -d '{"audio": "...", "volumes": [...], ...}'
   ```

## Future Enhancements

Potential improvements for future versions:
- WebSocket endpoint for streaming audio
- Support for multiple audio formats
- Audio queue management
- Priority system for multiple sources
- Event callbacks for playback status