# TTS Disable Feature

## Overview

This feature allows you to disable VTube's built-in Text-to-Speech (TTS) generation while keeping all other functionality intact. This is useful when:

- Using external audio sources (like chatbots with their own TTS)
- Avoiding duplicate TTS generation
- Running VTube as a display-only system
- Testing or debugging without audio

## Configuration

### Option 1: Edit conf.yaml

Add or modify the `tts_enabled` setting in your `conf.yaml`:

```yaml
agent_config:
  agent_settings:
    basic_memory_agent:
      # ... other settings ...
      # Enable or disable TTS generation
      # Set to false to disable VTube's built-in TTS
      tts_enabled: false  # Default is true
```

### Option 2: Create a new character configuration

Create a new character config file in the `characters` folder with TTS disabled:

```yaml
# characters/silent_character.yaml
agent_config:
  agent_settings:
    basic_memory_agent:
      llm_provider: "openai_compatible_llm"
      tts_enabled: false  # This character won't generate audio
```

## How It Works

When `tts_enabled` is set to `false`:

1. **Text responses continue normally** - The AI agent still generates text responses
2. **No audio files are created** - TTS engine is not called
3. **Frontend receives text-only messages** - Display updates without audio
4. **Live2D animations still work** - Expressions and idle animations continue
5. **External audio can be sent** - Use the `/api/external_audio` endpoint

## Implementation Details

The feature is implemented through:

1. **Configuration** (`config_manager/agent.py`):
   - Added `tts_enabled` field to `BasicMemoryAgentConfig`
   - Defaults to `true` for backward compatibility

2. **Agent Factory** (`agent/agent_factory.py`):
   - Passes `tts_enabled` to agent initialization

3. **Agent** (`agent/agents/basic_memory_agent.py`):
   - Stores `tts_enabled` as instance variable

4. **Conversation Handlers**:
   - `conversation_utils.py`: Checks `tts_enabled` before TTS generation
   - `single_conversation.py`: Passes flag to output processor
   - `group_conversation.py`: Handles group chat without TTS

## Use Cases

### 1. External Chatbot Integration

```yaml
# Disable VTube's TTS when using external chatbot
tts_enabled: false
```

Then send audio from your chatbot:
```python
# Your chatbot sends audio to VTube
requests.post("http://localhost:12393/api/external_audio", json=payload)
```

### 2. Silent Operation

Run VTube without any audio generation:
```yaml
tts_enabled: false
```

### 3. Testing and Development

Quickly test AI responses without waiting for TTS:
```yaml
tts_enabled: false  # Faster response times during development
```

## Messages Without TTS

When TTS is disabled, the frontend receives:
```json
{
  "type": "full-text",
  "text": "AI response text here"
}
```

Instead of:
```json
{
  "type": "audio",
  "audio": "base64_audio_data",
  "volumes": [...],
  "display_text": {...}
}
```

## Switching TTS On/Off

To toggle TTS:
1. Edit `conf.yaml`
2. Change `tts_enabled: true` to `tts_enabled: false` (or vice versa)
3. Restart VTube server

## Compatibility

- **Backward Compatible**: Existing configs work without changes (defaults to `true`)
- **Frontend Compatible**: No frontend changes required
- **API Compatible**: All existing APIs continue to work

## Related Features

- **External Audio Integration**: Send audio from external sources via `/api/external_audio`
- **Multiple Characters**: Different characters can have different TTS settings
- **Dynamic Control**: Future enhancement could allow runtime TTS toggling