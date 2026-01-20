"""
Videotto - Video Clip Analyzer
S3-based architecture: Upload to S3 -> Process on server -> Clips to S3
"""
import os
import json
import re
import threading
import subprocess
import tempfile
import uuid
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import boto3
from botocore.config import Config

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
CORS(app)

# S3 Configuration
S3_BUCKET = "videotto-storage"
S3_REGION = "ap-southeast-1"

s3_client = boto3.client(
    's3',
    region_name=S3_REGION,
    endpoint_url=f'https://s3.{S3_REGION}.amazonaws.com',
    config=Config(signature_version='s3v4')
)

# Global state for tracking progress
jobs = {}

# ============== S3 HELPERS ==============

def get_upload_url(filename: str, content_type: str = "video/mp4") -> dict:
    """Generate presigned URL for upload."""
    key = f"uploads/{uuid.uuid4()}/{filename}"
    
    presigned_url = s3_client.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': S3_BUCKET,
            'Key': key,
            'ContentType': content_type
        },
        ExpiresIn=3600  # 1 hour
    )
    
    return {"upload_url": presigned_url, "s3_key": key, "content_type": content_type}

def download_from_s3(s3_key: str, local_path: str):
    """Download file from S3 to local path."""
    print(f"[S3] Downloading {s3_key} to {local_path}")
    s3_client.download_file(S3_BUCKET, s3_key, local_path)
    print(f"[S3] Download complete: {os.path.getsize(local_path) / (1024*1024):.1f} MB")

def upload_to_s3(local_path: str, s3_key: str) -> str:
    """Upload file from local path to S3."""
    print(f"[S3] Uploading {local_path} to {s3_key}")
    s3_client.upload_file(local_path, S3_BUCKET, s3_key)
    
    # Generate presigned URL for download
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': S3_BUCKET, 'Key': s3_key},
        ExpiresIn=86400  # 24 hours
    )
    print(f"[S3] Upload complete")
    return url

# ============== TRANSCRIPTION ==============

def extract_audio(video_path: str) -> str:
    """Extract audio from video file for transcription."""
    audio_path = tempfile.mktemp(suffix=".mp3")
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        "-b:a", "64k",
        audio_path
    ]
    subprocess.run(cmd, capture_output=True)
    return audio_path

def transcribe_video(video_path: str) -> dict:
    """Transcribe video using Deepgram with speaker diarization."""
    audio_path = extract_audio(video_path)
    
    audio_size = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"[Transcription] Audio file size: {audio_size:.1f} MB")
    
    try:
        with open(audio_path, "rb") as audio_file:
            print(f"[Transcription] Sending to Deepgram...")
            response = requests.post(
                "https://api.deepgram.com/v1/listen",
                headers={
                    "Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}",
                    "Content-Type": "audio/mpeg"
                },
                params={
                    "model": "nova-2",
                    "diarize": "true",
                    "punctuate": "true",
                    "utterances": "true"
                },
                data=audio_file,
                timeout=300
            )
        
        print(f"[Transcription] Deepgram response status: {response.status_code}")
        result = response.json()
        
        if "error" in result:
            print(f"[Transcription] Deepgram error: {result}")
            return {"segments": []}
        
        segments = []
        utterances = result.get("results", {}).get("utterances", [])
        print(f"[Transcription] Got {len(utterances)} utterances")
        
        for utt in utterances:
            segments.append({
                "start": utt["start"],
                "end": utt["end"],
                "text": utt["transcript"],
                "speaker": utt.get("speaker", 0)
            })
        
        return {"segments": segments}
    except Exception as e:
        print(f"[Transcription] Error: {e}")
        return {"segments": []}
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)

# ============== CLIP ANALYSIS ==============

def parse_json_safely(content: str) -> dict:
    """Safely parse JSON from LLM response."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    
    content = content.strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    match = re.search(r'\{[\s\S]*\}', content)
    if match:
        json_str = match.group()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        fixed_json = re.sub(r',(\s*[}\]])', r'\1', json_str)
        try:
            return json.loads(fixed_json)
        except json.JSONDecodeError as e:
            print(f"[JSON Parse] Still failing: {e}")
    
    raise json.JSONDecodeError(f"Could not parse JSON", content, 0)


def analyze_transcript(transcript: dict) -> dict:
    """Send transcript to Claude for clip selection."""
    segments_text = ""
    for seg in transcript["segments"]:
        start = seg["start"]
        end = seg["end"]
        text = seg["text"].strip()
        segments_text += f"[{start:.1f}s - {end:.1f}s]: {text}\n"
    
    prompt = f"""You are analyzing a podcast transcript to find the top 3 clips that would go viral on TikTok/YouTube Shorts.

TRANSCRIPT:
{segments_text}

For each clip, evaluate based on:
1. Hook strength - Does it grab attention in the first 3 seconds?
2. Standalone clarity - Can someone understand this without context?
3. Emotional resonance - Is it surprising, funny, controversial, or inspiring?
4. Quotability - Does it have memorable phrasing?

IMPORTANT: Return ONLY valid JSON with NO additional text. Use double quotes for all strings.

Return this exact structure:
{{"clips": [{{"rank": 1, "start_time": 0.0, "end_time": 60.0, "transcript_excerpt": "quote here", "explanation": "why selected"}}, {{"rank": 2, "start_time": 0.0, "end_time": 60.0, "transcript_excerpt": "quote here", "explanation": "why selected"}}, {{"rank": 3, "start_time": 0.0, "end_time": 60.0, "transcript_excerpt": "quote here", "explanation": "why selected"}}]}}

Each clip should be 30-60 seconds long. Pick moments that would make someone stop scrolling."""

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json"
        },
        json={
            "model": "anthropic/claude-3.7-sonnet",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        }
    )
    
    result = response.json()
    content = result["choices"][0]["message"]["content"]
    print(f"[Analyze] Raw LLM response length: {len(content)} chars")
    
    return parse_json_safely(content)

# ============== CLIP EXTRACTION ==============

import cv2
from video_analyzer import analyze_clip_keyframes

def extract_clips(video_path: str, clips_data: dict, job_id: str) -> list:
    """Extract video clips and upload to S3."""
    temp_dir = tempfile.mkdtemp()
    
    cap = cv2.VideoCapture(video_path)
    orig_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    
    print(f"[ClipExtract] Video: {orig_width}x{orig_height}")
    
    target_width = int(orig_height * 9 / 16)
    max_x = orig_width - target_width
    
    extracted = []
    for clip in clips_data["clips"]:
        start = clip["start_time"]
        end = clip["end_time"]
        duration = end - start
        rank = clip["rank"]
        
        output_file = f"{temp_dir}/clip_{rank}.mp4"
        
        print(f"[ClipExtract] Clip {rank}: Analyzing keyframes...")
        keyframes = analyze_clip_keyframes(video_path, start, duration, num_keyframes=4)
        clip["keyframes"] = keyframes
        
        def cropx_to_pixels(cropx):
            crop_center = int(cropx * orig_width)
            return max(0, min(crop_center - target_width // 2, max_x))
        
        sorted_kf = sorted(keyframes, key=lambda k: k.get("time", 0))
        print(f"[ClipExtract] Clip {rank} keyframes: {sorted_kf}")
        
        if len(sorted_kf) == 1:
            crop_expr = str(cropx_to_pixels(sorted_kf[0].get("cropX", 0.5)))
        else:
            last_pos = cropx_to_pixels(sorted_kf[-1].get("cropX", 0.5))
            crop_expr = str(last_pos)
            
            for i in range(len(sorted_kf) - 2, -1, -1):
                t_next = sorted_kf[i + 1].get("time", 0)
                pos_curr = cropx_to_pixels(sorted_kf[i].get("cropX", 0.5))
                crop_expr = f"if(lt(t,{t_next}),{pos_curr},{crop_expr})"
        
        video_filter = f"crop={target_width}:{orig_height}:'{crop_expr}':0,scale=1080:1920"
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-vf", video_filter,
            "-c:v", "libx264", "-c:a", "aac", "-preset", "fast",
            output_file
        ]
        print(f"[ClipExtract] Running ffmpeg for clip {rank}")
        subprocess.run(cmd, capture_output=True)
        
        # Upload to S3
        s3_key = f"clips/{job_id}/clip_{rank}.mp4"
        clip_url = upload_to_s3(output_file, s3_key)
        
        # Clean up local file
        os.remove(output_file)
        
        extracted.append({
            "rank": rank,
            "s3_key": s3_key,
            "video_url": clip_url,
            "keyframes": keyframes
        })
    
    return extracted

# ============== JOB PROCESSING ==============

def process_video(job_id: str, s3_key: str):
    """Background job to process video from S3."""
    temp_video = None
    try:
        # Download video from S3
        jobs[job_id]["status"] = "downloading"
        jobs[job_id]["progress"] = "Downloading video from S3..."
        
        temp_video = tempfile.mktemp(suffix=".mp4")
        download_from_s3(s3_key, temp_video)
        
        # Transcribe
        jobs[job_id]["status"] = "transcribing"
        jobs[job_id]["progress"] = "Transcribing with speaker diarization..."
        
        transcript = transcribe_video(temp_video)
        
        jobs[job_id]["status"] = "analyzing"
        jobs[job_id]["progress"] = "Analyzing transcript for viral clips..."
        
        clips = analyze_transcript(transcript)
        
        full_transcript = []
        for seg in transcript["segments"]:
            full_transcript.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip()
            })
        
        jobs[job_id]["status"] = "extracting"
        jobs[job_id]["progress"] = "Extracting and uploading clips..."
        
        extracted_clips = extract_clips(temp_video, clips, job_id)
        
        # Update clip URLs
        for clip in clips["clips"]:
            for ext in extracted_clips:
                if clip["rank"] == ext["rank"]:
                    clip["video_url"] = ext["video_url"]
                    clip["s3_key"] = ext["s3_key"]
        
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = "Done!"
        jobs[job_id]["result"] = clips
        jobs[job_id]["transcript"] = full_transcript
        jobs[job_id]["source_s3_key"] = s3_key
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["progress"] = f"Error: {str(e)}"
        jobs[job_id]["error"] = str(e)
    finally:
        if temp_video and os.path.exists(temp_video):
            os.remove(temp_video)

# ============== API ROUTES ==============

@app.route("/")
def index():
    """API health check."""
    return jsonify({"status": "ok", "service": "videotto-api"})

@app.route("/get-upload-url", methods=["POST"])
def get_upload_url_route():
    """Get presigned URL for S3 upload."""
    data = request.json
    filename = data.get("filename", "video.mp4")
    content_type = data.get("content_type", "video/mp4")
    
    result = get_upload_url(filename, content_type)
    return jsonify(result)

@app.route("/analyze", methods=["POST"])
def analyze():
    """Start video analysis job from S3 key."""
    data = request.json
    s3_key = data.get("s3_key")
    
    if not s3_key:
        return jsonify({"error": "No s3_key provided"}), 400
    
    # Create job
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "queued",
        "progress": "Queued for processing...",
        "result": None,
        "error": None,
        "s3_key": s3_key
    }
    
    # Start background processing
    thread = threading.Thread(target=process_video, args=(job_id, s3_key))
    thread.start()
    
    return jsonify({"job_id": job_id})

@app.route("/status/<job_id>")
def status(job_id):
    """Get job status."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(jobs[job_id])

@app.route("/source-url/<job_id>")
def get_source_url(job_id):
    """Get presigned URL for source video (for crop editor)."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    
    s3_key = jobs[job_id].get("source_s3_key")
    if not s3_key:
        return jsonify({"error": "Source not found"}), 404
    
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': S3_BUCKET, 'Key': s3_key},
        ExpiresIn=3600
    )
    return jsonify({"url": url})

@app.route("/reexport", methods=["POST"])
def reexport_clip():
    """Re-export a clip with custom keyframes."""
    data = request.json
    job_id = data.get("job_id")
    clip_rank = data.get("clip_rank")
    keyframes = data.get("keyframes", [{"time": 0, "cropX": 0.5}])
    
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    
    job = jobs[job_id]
    s3_key = job.get("source_s3_key")
    result = job.get("result")
    
    if not s3_key or not result:
        return jsonify({"error": "Job data not found"}), 404
    
    clip = None
    for c in result.get("clips", []):
        if c["rank"] == clip_rank:
            clip = c
            break
    
    if not clip:
        return jsonify({"error": "Clip not found"}), 404
    
    # Download source video
    temp_video = tempfile.mktemp(suffix=".mp4")
    download_from_s3(s3_key, temp_video)
    
    try:
        cap = cv2.VideoCapture(temp_video)
        orig_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        
        target_width = int(orig_height * 9 / 16)
        max_x = orig_width - target_width
        
        temp_output = tempfile.mktemp(suffix=".mp4")
        
        start = clip["start_time"]
        duration = clip["end_time"] - start
        
        sorted_kf = sorted(keyframes, key=lambda k: k.get("time", 0))
        
        def cropx_to_pixels(cropx):
            crop_center = int(cropx * orig_width)
            return max(0, min(crop_center - target_width // 2, max_x))
        
        if len(sorted_kf) == 1:
            crop_expr = str(cropx_to_pixels(sorted_kf[0].get("cropX", 0.5)))
        else:
            last_pos = cropx_to_pixels(sorted_kf[-1].get("cropX", 0.5))
            crop_expr = str(last_pos)
            
            for i in range(len(sorted_kf) - 2, -1, -1):
                t_next = sorted_kf[i + 1].get("time", 0)
                pos_curr = cropx_to_pixels(sorted_kf[i].get("cropX", 0.5))
                crop_expr = f"if(lt(t,{t_next}),{pos_curr},{crop_expr})"
        
        print(f"[ReExport] Keyframes: {sorted_kf}")
        print(f"[ReExport] Crop expression: {crop_expr}")
        
        video_filter = f"crop={target_width}:{orig_height}:'{crop_expr}':0,scale=1080:1920"
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", temp_video,
            "-t", str(duration),
            "-vf", video_filter,
            "-c:v", "libx264", "-c:a", "aac", "-preset", "fast",
            temp_output
        ]
        
        result_proc = subprocess.run(cmd, capture_output=True, text=True)
        
        if result_proc.returncode != 0:
            print(f"[ReExport] ffmpeg error: {result_proc.stderr}")
            return jsonify({"error": "Export failed"}), 500
        
        # Upload to S3
        clip_s3_key = f"clips/{job_id}/clip_{clip_rank}.mp4"
        clip_url = upload_to_s3(temp_output, clip_s3_key)
        
        # Update job data
        clip["video_url"] = clip_url
        clip["keyframes"] = keyframes
        
        os.remove(temp_output)
        
        return jsonify({"video_url": clip_url})
    finally:
        if os.path.exists(temp_video):
            os.remove(temp_video)

if __name__ == "__main__":
    app.run(debug=True, port=5001)
