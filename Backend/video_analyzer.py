"""
Video Analyzer - Uses LLM to analyze video and tune face tracking parameters.
Sends sample frames to LLM without bias to get optimal CV parameters.
"""
import cv2
import base64
import requests
import json
import os


def sample_clip_frames(video_path: str, start: float, duration: float, num_frames: int = 8) -> list:
    """Sample frames from a specific clip segment."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    frames = []
    for i in range(num_frames):
        t = start + (duration * i / (num_frames - 1))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret:
            frame = cv2.resize(frame, (480, 270))  # Smaller for faster upload
            frames.append(frame)
    
    cap.release()
    return frames


def frames_to_base64(frames: list) -> list:
    """Convert frames to base64."""
    encoded = []
    for frame in frames:
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        encoded.append(base64.b64encode(buffer).decode('utf-8'))
    return encoded


def analyze_clip_for_speaker(video_path: str, start: float, duration: float) -> float:
    """
    Analyze a specific clip segment with LLM to find the active speaker position.
    Returns normalized X position (0.0-1.0) of the active speaker.
    """
    keyframes = analyze_clip_keyframes(video_path, start, duration, num_keyframes=1)
    if keyframes:
        return keyframes[0].get("cropX", 0.5)
    return 0.5


def analyze_clip_keyframes(video_path: str, start: float, duration: float, num_keyframes: int = 4) -> list:
    """
    Analyze a clip at multiple timestamps and return keyframes with speaker positions.
    Returns list of {"time": <seconds from clip start>, "cropX": <0.0-1.0>}
    """
    # Sample more frames for keyframe analysis
    num_frames = max(num_keyframes * 2, 6)
    frames = sample_clip_frames(video_path, start, duration, num_frames=num_frames)
    
    if not frames:
        return [{"time": 0, "cropX": 0.5}]
    
    encoded_frames = frames_to_base64(frames)
    
    # Calculate timestamps for each frame
    frame_times = [duration * i / (num_frames - 1) for i in range(num_frames)]
    
    prompt = f"""I'm showing you {num_frames} frames from a video clip, sampled at regular intervals.
The clip is {duration:.1f} seconds long.

Frame timestamps (seconds from start): {', '.join([f'{t:.1f}s' for t in frame_times])}

For each frame, identify where the ACTIVE SPEAKER is positioned horizontally.
Look for: mouth movement, hand gestures, body language, eye gaze of listeners.

Return ONLY this JSON with speaker positions at key moments:
{{
    "keyframes": [
        {{"time": 0.0, "cropX": <0.0-1.0>, "notes": "<who is speaking>"}},
        {{"time": <seconds>, "cropX": <0.0-1.0>, "notes": "<who is speaking>"}},
        ...
    ]
}}

Guidelines for cropX:
- 0.0 = speaker at left edge
- 0.5 = speaker at center  
- 1.0 = speaker at right edge

Include a keyframe whenever the active speaker CHANGES or MOVES significantly.
Minimum 2 keyframes, maximum {num_keyframes} keyframes.
Only add keyframes where there's a meaningful change in speaker position."""

    content = [{"type": "text", "text": prompt}]
    for i, b64 in enumerate(encoded_frames):
        content.append({"type": "text", "text": f"Frame {i+1} ({frame_times[i]:.1f}s):"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2
            },
            timeout=60
        )
        
        result = response.json()
        response_text = result["choices"][0]["message"]["content"]
        
        # Parse JSON
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        import re
        match = re.search(r'\{[\s\S]*\}', response_text)
        if match:
            data = json.loads(match.group())
            keyframes = data.get("keyframes", [])
            
            # Validate and clean keyframes
            valid_keyframes = []
            for kf in keyframes:
                time = float(kf.get("time", 0))
                cropX = float(kf.get("cropX", 0.5))
                # Clamp values
                time = max(0, min(duration, time))
                cropX = max(0.1, min(0.9, cropX))
                valid_keyframes.append({"time": time, "cropX": cropX})
            
            if valid_keyframes:
                # Sort by time
                valid_keyframes.sort(key=lambda k: k["time"])
                print(f"[VideoAnalyzer] LLM detected {len(valid_keyframes)} keyframes")
                for kf in valid_keyframes:
                    print(f"  - {kf['time']:.1f}s: cropX={kf['cropX']:.2f}")
                return valid_keyframes
            
    except Exception as e:
        print(f"[VideoAnalyzer] LLM keyframe analysis failed: {e}")
    
    # Default: single keyframe at center
    return [{"time": 0, "cropX": 0.5}]


def analyze_video_with_llm(video_path: str) -> dict:
    """
    Analyze video to get optimal face tracking parameters.
    Returns tuned CV parameters based on video characteristics.
    """
    # Sample frames from different parts of video
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0
    
    # Get 5 representative frames
    frames = []
    for pct in [0.1, 0.3, 0.5, 0.7, 0.9]:
        frame_idx = int(total_frames * pct)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            frame = cv2.resize(frame, (480, 270))
            frames.append(frame)
    cap.release()
    
    if not frames:
        return get_default_params()
    
    encoded_frames = frames_to_base64(frames)
    
    # Unbiased prompt for CV parameter tuning
    prompt = """Analyze these video frames to help tune face detection parameters.

I'm using OpenCV's Haar Cascade face detector with these tunable parameters:
- scaleFactor (1.01-1.3): Lower = more thorough but slower. Default 1.1
- minNeighbors (1-6): Lower = more sensitive, more false positives. Default 3
- minSize (20-80): Minimum face size in pixels. Default 40

Look at the frames and assess:
1. How many people are visible? Where are they positioned?
2. Are there challenging conditions? (hats, beards, glasses, side profiles, lighting)
3. Is the background busy with face-like patterns?
4. What parameter values would work best?

Return ONLY this JSON:
{"scale_factor": <float>, "min_neighbors": <int>, "min_size": <int>, "num_people": <int>, "challenges": "<brief list>", "notes": "<recommendation>"}

Be aggressive with detection (lower scale_factor, lower min_neighbors) if faces are hard to detect.
Be conservative (higher values) if background has many false positive triggers."""

    content = [{"type": "text", "text": prompt}]
    for b64 in encoded_frames:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2
            },
            timeout=60
        )
        
        result = response.json()
        response_text = result["choices"][0]["message"]["content"]
        
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        import re
        match = re.search(r'\{[\s\S]*\}', response_text)
        if match:
            params = json.loads(match.group())
            validated = validate_params(params)
            print(f"[VideoAnalyzer] LLM tuned params: {validated}")
            return validated
            
    except Exception as e:
        print(f"[VideoAnalyzer] LLM analysis failed: {e}")
    
    return get_default_params()


def get_default_params() -> dict:
    """Return default face tracking parameters."""
    return {
        "scale_factor": 1.05,
        "min_neighbors": 2,
        "min_size": 30,
        "notes": "Using defaults"
    }


def validate_params(params: dict) -> dict:
    """Validate and clamp parameters to valid ranges."""
    defaults = get_default_params()
    
    return {
        "scale_factor": max(1.01, min(1.3, float(params.get("scale_factor", defaults["scale_factor"])))),
        "min_neighbors": max(1, min(6, int(params.get("min_neighbors", defaults["min_neighbors"])))),
        "min_size": max(20, min(80, int(params.get("min_size", defaults["min_size"])))),
        "notes": params.get("notes", "")
    }
