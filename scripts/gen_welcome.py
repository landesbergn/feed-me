"""Generate the Feed Me welcome episode MP3 (~30s, OpenAI TTS, shimmer voice).

Run from project root with OPENAI_API_KEY set:
    OPENAI_API_KEY=sk-... uv run python scripts/gen_welcome.py

Writes: static/welcome.mp3

Re-run when the script text changes; commit both this script and the new
MP3 output together. Production never executes this — the MP3 is read
once at app startup and seeded into each new user's directory.
"""
import os
import sys
from pathlib import Path

from openai import OpenAI

OUTPUT = Path(__file__).parent.parent / "static" / "welcome.mp3"
SCRIPT = (
    "Welcome to Feed Me. This is your private podcast feed for articles you "
    "want to listen to instead of read. Open an article on your phone, tap "
    "the Share button, then tap Feed Me to send it to your feed. A new "
    "episode shows up here in about a minute. Enjoy!"
)


def main():
    client = OpenAI()
    response = client.audio.speech.create(
        model="tts-1",
        voice="shimmer",
        input=SCRIPT,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(response.content)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)
    main()
