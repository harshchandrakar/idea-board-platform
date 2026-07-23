"""Advisory: a plain-English summary of what is shipping (posted on the run)."""
import subprocess

try:
    from .llm_client import GeminiClient
    from .prompts import render
except ImportError:
    from llm_client import GeminiClient
    from prompts import render


def git_changes():
    try:
        return subprocess.check_output(["git", "log", "--oneline", "-20"], text=True)
    except Exception:
        return "(git history unavailable)"


def main():
    prompt = render("summarize", changes=git_changes())
    try:
        print(GeminiClient(model="gemini-3.5-flash-lite").ask(prompt))
    except Exception:
        print("• Automated summary unavailable (AI rate-limited). See commit list.")


if __name__ == "__main__":
    main()
