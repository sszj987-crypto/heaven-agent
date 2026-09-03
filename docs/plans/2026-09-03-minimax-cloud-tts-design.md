# MiniMax Cloud TTS Design

## Goal

Add MiniMax as the first cloud TTS provider while preserving the existing local
CosyVoice implementation. A user can configure MiniMax in Settings, upload a
10–30 second voice sample from the Soul profile, create and activate a cloned
voice, and explicitly generate speech from an assistant message.

The first version remains a local, single-user product with one active Soul, but
cloud voice metadata stays scoped by `soul_id`.

## Decisions

- Supported providers are `local` and `minimax`.
- MiniMax uses an independent API key; it never reuses the LLM key.
- Cloud configuration lives in Settings. Voice creation and current voice state
  remain in the Soul profile.
- The Soul profile shows only the current provider state and the relevant action.
- Cloud synthesis failures are surfaced to the user and never fall back to local
  TTS automatically.
- A newly cloned MiniMax voice is activated immediately with a short synthesis.
  This verifies the voice and prevents the temporary clone from expiring after
  seven days without a formal synthesis.
- Assistant text remains visible and audio remains click-to-generate.

## Why MiniMax

MiniMax accepts the voice sample as a multipart file upload and returns a
`file_id`; it does not require the local-only app to expose the recording through
a public URL or configure OSS. Its synchronous HTTP synthesis endpoint matches
the current click-to-generate interaction and can produce WAV output.

The supported sample constraints—MP3/M4A/WAV, 10 seconds to 5 minutes, and at
most 20 MB—cover the project's existing 10–30 second recording guidance.

References:

- [Upload clone audio](https://platform.minimaxi.com/docs/api-reference/voice-cloning-uploadcloneaudio)
- [Clone voice](https://platform.minimaxi.com/docs/api-reference/voice-cloning-clone)
- [Synchronous TTS](https://platform.minimaxi.com/docs/api-reference/speech-t2a-http)
- [Delete uploaded file](https://platform.minimaxi.com/docs/api-reference/file-management-delete)
- [Delete cloned voice](https://platform.minimaxi.com/docs/api-reference/voice-management-delete)

## Configuration

Add an ignored `config/tts.json` managed by the existing Settings service:

```json
{
  "provider": "local",
  "minimax": {
    "base_url": "https://api.minimaxi.com",
    "api_key": "",
    "model": "speech-2.8-hd"
  }
}
```

The settings response never returns the API key. It returns
`api_key_configured` instead. Update semantics match the LLM settings contract:
omitting the key keeps it, and an explicit empty string clears it.

Changing the provider hot-swaps the voice service in the application container.
Selecting MiniMax does not require local voice dependencies or a downloaded
model.

## Soul Voice State

Store provider-specific metadata at:

```text
data/souls/{soul_id}/voice/cloud.json
```

The document contains the provider, `voice_id`, model, creation timestamp,
source fingerprint, status, and any remote IDs awaiting cleanup. The reference
recording and activation preview remain inside the same Soul voice directory.
Writes use the existing atomic file utilities and Soul lock.

Provider-aware status values are:

- Local: not installed, no voice, ready, failed.
- MiniMax: not configured, no voice, creating, ready, failed.

`voice_ready` and chat `has_voice` always describe the selected provider. A
MiniMax provider must not display the local package installer as a prerequisite.

## Voice Creation Flow

1. Accept the existing multipart audio upload.
2. Validate that the body is non-empty and within the project upload limit.
3. Preserve the source recording in the Soul voice directory.
4. Upload the sample to MiniMax `/v1/files/upload` with
   `purpose=voice_clone`.
5. Create a unique provider voice ID and call `/v1/voice_clone`.
6. Call `/v1/t2a_v2` with a short neutral activation phrase, WAV output, and the
   new voice ID.
7. Reject empty, malformed, or provider-error audio and retain the old voice.
8. Save the verified preview and atomically activate the new metadata.
9. Delete the temporary MiniMax file.
10. After the new voice is active, delete the previous remote cloned voice.

Remote cleanup failures do not invalidate a verified new voice. Failed cleanup
IDs are persisted and retried on a later safe operation. If activation fails,
the new clone is deleted best-effort and the previously active voice remains.

The UI explains before upload that the sample is sent to MiniMax and that the
activation synthesis can incur the provider's first-use cloning/synthesis fee.

## Speech Synthesis

`MiniMaxTTSService` implements the same interface used by local services:

```python
async def speak(text: str, config: TTSConfig | None = None) -> AsyncGenerator[bytes, None]
```

The adapter calls `/v1/t2a_v2` in non-streaming mode, requests mono WAV, decodes
the returned hex audio, validates that bytes are present, and yields the complete
audio. Network I/O uses an asynchronous HTTP client with bounded connect/read
timeouts.

The existing LLM produces a free-form Chinese `instruct_text`. The MiniMax
adapter maps known terms deterministically to the provider's supported emotions:
`happy`, `sad`, `angry`, `fearful`, `disgusted`, `surprised`, `calm`, and
`whisper`. Unknown instructions use `calm`. No second LLM call is introduced and
the spoken reply text is not rewritten.

## API and UI Changes

- Extend `GET /settings` and `PUT /settings` with optional `tts` configuration.
- Add a TTS connection check that validates credentials without synthesizing
  billable audio.
- Extend `GET /settings/voice/status` with the selected provider and one current
  provider-aware state/message while retaining readiness capabilities.
- Keep the existing voice upload endpoint and route it to the selected provider.
- Settings adds a compact Voice Service section for provider, API key, model,
  save, and test.
- Soul `VoicePanel` renders the current state and upload/recreate action. Local
  mode retains the package installer; MiniMax mode does not show it.
- Chat endpoints and the text-first, click-to-generate message behavior stay
  unchanged.

## Error Handling and Privacy

- Authentication, quota/rate limit, timeout, invalid sample, expired voice, and
  provider failures map to safe Chinese errors with retryability preserved where
  relevant.
- There is no automatic local fallback.
- API keys, recordings, full conversation text, and provider response bodies are
  excluded from default logs.
- Logs may contain request ID, provider, operation, duration, HTTP status, and
  exception type.
- The MiniMax API key and local runtime voice data remain ignored by Git.
- Deleting or replacing a cloud voice performs best-effort remote deletion and
  preserves cleanup state when the provider is unavailable.

## Testing

- Unit tests cover configuration masking/update semantics, provider construction,
  emotion mapping, hex WAV decoding, metadata persistence, and cleanup state.
- Adapter tests use a fake HTTP transport for upload, clone, activation,
  synthesis, provider errors, timeout, and deletion; they never call MiniMax.
- API integration tests cover Settings, provider-aware status, upload success,
  activation failure retaining the old voice, and chat audio failures without
  fallback.
- Frontend tests cover configuration payloads and provider-aware VoicePanel state.
- Regression verification includes backend tests, frontend tests, ESLint,
  TypeScript, production build, and a manual configured-provider smoke test.

