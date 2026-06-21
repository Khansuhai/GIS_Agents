"""
run.py -- Entry Point for the Himalayan GIS Agent System.

Usage:
    python run.py
"""

import sys


def main():
    print()
    print("=" * 48)
    print("    HIMALAYAN GIS AGENT SYSTEM")
    print("=" * 48)
    print("  Ollama : http://localhost:11434")
    print("  Models : qwen2.5-coder | llama3.2 | gemma3:4b")
    print("=" * 48)
    print()
    print("  [1] Text Mode")
    print("  [2] Voice Mode")
    print("  [3] Exit")
    print()

    try:
        choice = input("  Choose mode [1/2/3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")
        return

    if choice == "1":
        # -- Text Mode --------------------------------------------------------
        try:
            from core.orchestrator import main_loop
        except ImportError as exc:
            print(f"\n  [ERROR] Import error: {exc}")
            print("  Missing package. Run:")
            print("    pip install requests edge-tts pygame faster-whisper sounddevice numpy scipy")
            return
        main_loop()

    elif choice == "2":
        # -- Voice Mode -------------------------------------------------------
        try:
            from core.voice_engine import speak, listen
            from core.orchestrator import route_request
        except ImportError as exc:
            print(f"\n  [ERROR] Import error: {exc}")
            print("  Missing package. Run:")
            print("    pip install requests edge-tts pygame faster-whisper sounddevice numpy scipy")
            return

        print()
        print("  [MIC] Voice Mode active.  Say 'exit' to quit.")
        speak("Himalayan GIS Agent System is ready. Speak your command.")

        conversation_history: dict = {}
        while True:
            text = listen(duration=6)
            if not text:
                speak("I didn't catch that. Please try again.")
                continue

            print(f"\n  [YOU] {text}")

            if "exit" in text.lower() or "quit" in text.lower():
                speak("Goodbye.")
                break

            try:
                agent_name, response = route_request(text, conversation_history)
            except Exception as exc:
                speak(f"Sorry, an error occurred: {exc}")
                continue

            print(f"\n  [{agent_name}]")
            print(response)

            # Speak a truncated version (avoid reading huge code blocks)
            spoken = response[:500] if len(response) > 500 else response
            speak(spoken)

    elif choice == "3":
        print("  Goodbye.")

    else:
        print("  Invalid choice. Run again and pick 1, 2, or 3.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Interrupted. Goodbye.")
    except Exception as exc:
        print(f"\n  [FATAL] Error: {exc}")
        print("  If a package is missing, run:")
        print("    pip install requests edge-tts pygame faster-whisper sounddevice numpy scipy")
        sys.exit(1)
