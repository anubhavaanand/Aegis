import os
from gtts import gTTS

def generate_narration():
    # Narration text
    text = (
        "This is Aegis: a post-execution truth layer for AI agents. "
        "When an agent claims complete success, how do you verify its outcomes? "
        "In this run, a developer agent is tasked with fixing a bug, updating documentation, and creating a pull request. "
        "The agent executes, terminates, and claims complete success. "
        "However, Aegis ingests the OpenTelemetry traces, audits the workspace state, and detects execution drift. "
        "The documentation was not updated, and no pull request was created. "
        "Aegis also flags two missed capabilities: the doc updater skill and the git pull request tool. "
        "Instead of failing the entire run, Aegis proposes a minimal corrective repair plan. "
        "Once reviewed and approved by the user, Aegis executes the repair pass. "
        "Final verification confirms all conditions are met, returning a status of CORRECTED. "
        "Aegis brings trust, state reconciliation, and closed-loop compliance to agent execution."
    )

    print("Synthesizing narration audio using gTTS...")
    tts = gTTS(text=text, lang="en", tld="com")

    # Ensure destination folder exists
    output_dir = "/home/anubhavanand/Aegis/demo/assets"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "aegis_narration.mp3")

    # Save audio to output file
    tts.save(output_path)
    print(f"Audio content written to {output_path}")

    # Also write text script
    text_path = os.path.join(output_dir, "aegis_narration_script.txt")
    with open(text_path, "w") as f:
        f.write(text)
        print(f"Script text written to {text_path}")

if __name__ == "__main__":
    generate_narration()
