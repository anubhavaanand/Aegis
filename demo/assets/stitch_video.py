import subprocess
import os

def stitch():
    slides_file = "/home/anubhavanand/Aegis/demo/assets/slides.txt"
    with open(slides_file, "w") as f:
        f.write(
            "file '/home/anubhavanand/Aegis/demo/assets/aegis_cover_image.png'\n"
            "duration 12.0\n"
            "file '/home/anubhavanand/Aegis/demo/assets/reconciliation_report.png'\n"
            "duration 35.0\n"
            "file '/home/anubhavanand/Aegis/demo/assets/approval_gate.png'\n"
            "duration 13.0\n"
            "file '/home/anubhavanand/Aegis/demo/assets/corrected_status.png'\n"
            "duration 14.35\n"
            "file '/home/anubhavanand/Aegis/demo/assets/corrected_status.png'\n"
        )
    
    output_video = "/home/anubhavanand/Aegis/demo/assets/aegis_demo_video.mp4"
    audio_path = "/home/anubhavanand/Aegis/demo/assets/aegis_narration.mp3"
    
    # FFmpeg command:
    # -f concat: concat demuxer
    # -safe 0: allow absolute paths
    # -i slides.txt: input slides file list
    # -i narration.mp3: audio input
    # -c:v libx264: H.264 video codec
    # -pix_fmt yuv420p: Pixel format for universal compatibility (QuickTime, browser, YouTube)
    # -c:a aac: AAC audio codec
    # -shortest: stop when shortest input completes
    # -y: overwrite existing file
    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", slides_file,
        "-i", audio_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-y",
        output_video
    ]
    
    print("Running FFmpeg to stitch slides and audio...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Successfully generated demo video: {output_video}")
    else:
        print("FFmpeg failed with error:")
        print(res.stderr)

if __name__ == "__main__":
    stitch()
