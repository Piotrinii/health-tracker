from openai import OpenAI


def transcribe_voice(api_key: str, ogg_bytes: bytes, model: str = "whisper-1") -> str:
    client = OpenAI(api_key=api_key)
    transcript = client.audio.transcriptions.create(
        model=model,
        file=("voice.ogg", ogg_bytes, "audio/ogg"),
    )
    return transcript.text
