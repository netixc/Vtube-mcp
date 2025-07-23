# VTube MCP - Agent-Zero Integration

This branch contains the working integration between Agent-Zero and VTube for real-time avatar responses with emotions and lip-sync.

## Features

- ✅ Automatic response forwarding from Agent-Zero to VTube
- ✅ Emotion detection and expression mapping
- ✅ Text-to-Speech with Kokoro TTS
- ✅ Lip-sync animation
- ✅ No duplicate messages
- ✅ Clean TTS output (no emoji reading)

## Quick Start

### 1. Install the Agent-Zero Extension

Copy the extension to your Agent-Zero installation:
```bash
cp agent-zero-integration/vtube_extension.py /path/to/agent-zero/python/extensions/response_stream/_35_vtube_simple.py
```

### 2. Configure Settings

Update the extension with your settings:
- VTube API URL: `http://your-vtube-ip:12393/api/external_audio`
- Kokoro TTS URL: `http://your-tts-ip:8880/v1`
- Voice: `af_sky+af_bella` (or your preferred voice)

### 3. Start Services

1. Start VTube Studio
2. Start Kokoro TTS server
3. Start Agent-Zero
4. Chat normally - responses automatically appear on your avatar!

## Directory Structure

```
├── agent-zero-integration/
│   └── vtube_extension.py      # The Agent-Zero extension
├── examples/
│   ├── simple_chatbot.py       # Standalone chatbot example
│   ├── manual_bridge.py        # Manual testing tool
│   └── audio_integration_example.py  # Audio integration example
└── docs/
    └── setup_guide.md          # Detailed setup instructions
```

## How It Works

1. User sends message to Agent-Zero
2. Agent-Zero processes and generates response
3. Extension intercepts response
4. Adds emotion tags based on content
5. Generates audio with Kokoro TTS
6. Sends to VTube with audio + text + emotion
7. Avatar displays emotion and lip-syncs to audio

## Emotion Mapping

The extension automatically detects and maps emotions:
- `[joy]` - Happy, greetings, positive responses
- `[sadness]` - Apologies, unfortunate news
- `[anger]` - Errors, failures
- `[surprise]` - Amazing, wow
- `[neutral]` - Default state

## Requirements

- Agent-Zero
- VTube Studio with API enabled
- Kokoro TTS server
- Python 3.8+

## Configuration

Edit the extension file to change:
- API endpoints
- TTS voice
- Emotion keywords
- Response delay (default 0.5s)

## Troubleshooting

### Responses don't appear
- Check VTube is running and API is enabled
- Verify Kokoro TTS is accessible
- Check Agent-Zero logs for errors

### Multiple responses
- Restart Agent-Zero
- Ensure only one extension instance is active

### No audio
- Verify Kokoro TTS URL is correct
- Check TTS server is running
- Look for TTS errors in logs

## Examples

See the `examples/` directory for:
- Simple standalone chatbot
- Manual testing bridge
- Audio integration patterns

## License

MIT License - See LICENSE file