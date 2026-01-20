"use client";

import { useState, useRef, useEffect, useCallback } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5001";

type Keyframe = {
  time: number;
  cropX: number;
};

type Clip = {
  rank: number;
  start_time: number;
  end_time: number;
  transcript_excerpt: string;
  explanation: string;
  video_url?: string;
  keyframes?: Keyframe[];
};

type TranscriptSegment = {
  start: number;
  end: number;
  text: string;
};

type JobStatus = {
  status: string;
  progress: string;
  result?: { clips: Clip[] };
  transcript?: TranscriptSegment[];
  error?: string;
};

function formatTime(seconds: number): string {
  const min = Math.floor(seconds / 60);
  const sec = Math.floor(seconds % 60);
  return `${min}:${sec.toString().padStart(2, "0")}`;
}

// ==================== CROP EDITOR ====================
function CropEditor({
  clip,
  videoSrc,
  onClose,
  onExport,
}: {
  clip: Clip;
  videoSrc: string;
  onClose: () => void;
  onExport: (keyframes: Keyframe[]) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  const [positions, setPositions] = useState<Keyframe[]>(
    clip.keyframes && clip.keyframes.length > 0
      ? clip.keyframes
      : [{ time: 0, cropX: 0.5 }]
  );
  const [currentTime, setCurrentTime] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);

  const clipDuration = clip.end_time - clip.start_time;

  const getCropAtTime = useCallback((time: number): number => {
    if (positions.length === 0) return 0.5;
    if (positions.length === 1) return positions[0].cropX;

    const sorted = [...positions].sort((a, b) => a.time - b.time);
    
    if (time <= sorted[0].time) return sorted[0].cropX;
    if (time >= sorted[sorted.length - 1].time) return sorted[sorted.length - 1].cropX;

    for (let i = 0; i < sorted.length - 1; i++) {
      if (time >= sorted[i].time && time <= sorted[i + 1].time) {
        const t = (time - sorted[i].time) / (sorted[i + 1].time - sorted[i].time);
        return sorted[i].cropX + t * (sorted[i + 1].cropX - sorted[i].cropX);
      }
    }
    return 0.5;
  }, [positions]);

  const currentCropX = getCropAtTime(currentTime);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.currentTime = clip.start_time;
    }
  }, [clip.start_time]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleTimeUpdate = () => {
      const relativeTime = video.currentTime - clip.start_time;
      setCurrentTime(Math.max(0, Math.min(relativeTime, clipDuration)));
      if (video.currentTime >= clip.end_time) {
        video.currentTime = clip.start_time;
      }
    };

    video.addEventListener("timeupdate", handleTimeUpdate);
    video.addEventListener("play", () => setIsPlaying(true));
    video.addEventListener("pause", () => setIsPlaying(false));

    return () => {
      video.removeEventListener("timeupdate", handleTimeUpdate);
      video.removeEventListener("play", () => setIsPlaying(true));
      video.removeEventListener("pause", () => setIsPlaying(false));
    };
  }, [clip.start_time, clip.end_time, clipDuration]);

  const handleVideoMouseDown = () => setIsDragging(true);
  
  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!isDragging || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const newCropX = Math.max(0.15, Math.min(0.85, x));
      
      setPositions(prev => {
        const existing = prev.findIndex(p => Math.abs(p.time - currentTime) < 0.5);
        if (existing >= 0) {
          return prev.map((p, i) => i === existing ? { ...p, cropX: newCropX } : p);
        }
        return [...prev, { time: currentTime, cropX: newCropX }].sort((a, b) => a.time - b.time);
      });
    },
    [isDragging, currentTime]
  );

  const handleMouseUp = useCallback(() => setIsDragging(false), []);

  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
      return () => {
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
      };
    }
  }, [isDragging, handleMouseMove, handleMouseUp]);

  const setPositionHere = (cropX: number) => {
    setPositions(prev => {
      const existing = prev.findIndex(p => Math.abs(p.time - currentTime) < 0.5);
      if (existing >= 0) {
        return prev.map((p, i) => i === existing ? { time: currentTime, cropX } : p);
      }
      return [...prev, { time: currentTime, cropX }].sort((a, b) => a.time - b.time);
    });
  };

  const deletePositionHere = () => {
    if (positions.length <= 1) return;
    setPositions(prev => {
      const idx = prev.findIndex(p => Math.abs(p.time - currentTime) < 1);
      if (idx >= 0) return prev.filter((_, i) => i !== idx);
      return prev;
    });
  };

  const seekTo = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = clip.start_time + time;
      setCurrentTime(time);
    }
  };

  const cropWidthPercent = (9 / 16) * (9 / 16) * 100;
  const hasPositionNearby = positions.some(p => Math.abs(p.time - currentTime) < 1);

  return (
    <div className="fixed inset-0 bg-[#050505] z-50 flex flex-col">
      <div className="flex items-center justify-between px-8 py-6 border-b border-[#1a1a1a]">
        <div>
          <h2 className="text-xl font-semibold mb-1">Adjust Crop Focus</h2>
          <p className="text-sm text-[#525252]">
            Drag on the video to set focus position
          </p>
        </div>
        <button onClick={onClose} className="text-[#404040] hover:text-white text-3xl px-3 transition-colors">×</button>
      </div>

      <div className="flex-1 p-8 overflow-hidden">
        <div className="max-w-4xl mx-auto flex flex-col h-full">
          <div
            ref={containerRef}
            className="relative bg-black rounded-2xl overflow-hidden cursor-crosshair flex-1 border border-[#1a1a1a]"
            onMouseDown={handleVideoMouseDown}
          >
            <video
              ref={videoRef}
              src={videoSrc}
              className="w-full h-full object-contain"
              crossOrigin="anonymous"
            />

            <div
              className="absolute top-0 bottom-0 left-0 bg-black/60 pointer-events-none transition-all duration-100"
              style={{ width: `${(currentCropX - cropWidthPercent / 200) * 100}%` }}
            />
            <div
              className="absolute top-0 bottom-0 right-0 bg-black/60 pointer-events-none transition-all duration-100"
              style={{ width: `${(1 - currentCropX - cropWidthPercent / 200) * 100}%` }}
            />
            <div
              className="absolute top-0 bottom-0 border-2 border-white/90 pointer-events-none transition-all duration-100"
              style={{
                left: `${(currentCropX - cropWidthPercent / 200) * 100}%`,
                width: `${cropWidthPercent}%`,
              }}
            >
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="bg-black/50 px-3 py-1 rounded text-xs text-white/70">
                  ← Drag to adjust →
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-4 mt-5">
            <button
              onClick={() => videoRef.current?.paused ? videoRef.current?.play() : videoRef.current?.pause()}
              className="w-14 h-14 flex items-center justify-center bg-white text-black rounded-full font-bold shrink-0 hover:scale-105 transition-transform shadow-lg shadow-white/10"
          >
              {isPlaying ? "⏸" : "▶"}
            </button>
            <div className="flex-1">
              <input
                type="range"
                min="0"
                max={clipDuration}
                step="0.1"
                value={currentTime}
                onChange={(e) => seekTo(parseFloat(e.target.value))}
                className="w-full h-1.5 bg-[#1a1a1a] rounded-full appearance-none cursor-pointer
                           [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 
                           [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:bg-white 
                           [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:shadow-lg
                           [&::-webkit-slider-thumb]:shadow-white/20"
              />
            </div>
            <span className="font-mono text-sm text-[#404040] w-24 text-right tabular-nums">
              {formatTime(currentTime)}
            </span>
          </div>

          <div className="flex gap-2 mt-5">
            <button
              onClick={() => setPositionHere(0.25)}
              className="flex-1 py-3.5 text-sm font-semibold bg-[#111] border border-[#262626] rounded-xl hover:bg-[#1a1a1a] hover:border-[#333] transition-all"
            >
              ← Left
            </button>
            <button
              onClick={() => setPositionHere(0.5)}
              className="flex-1 py-3.5 text-sm font-semibold bg-white text-black rounded-xl hover:bg-[#e5e5e5] transition-all"
            >
              Center
            </button>
            <button
              onClick={() => setPositionHere(0.75)}
              className="flex-1 py-3.5 text-sm font-semibold bg-[#111] border border-[#262626] rounded-xl hover:bg-[#1a1a1a] hover:border-[#333] transition-all"
            >
              Right →
            </button>
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            {positions.sort((a, b) => a.time - b.time).map((pos, i) => (
              <button
                key={i}
                onClick={() => seekTo(pos.time)}
                className={`px-4 py-2 text-xs font-medium rounded-xl transition-all ${
                  Math.abs(pos.time - currentTime) < 0.5
                    ? "bg-white text-black shadow-lg shadow-white/10"
                    : "bg-[#141414] text-[#737373] hover:bg-[#1a1a1a] hover:text-white border border-[#1f1f1f]"
                }`}
              >
                {formatTime(pos.time)} · {pos.cropX < 0.4 ? "L" : pos.cropX > 0.6 ? "R" : "C"}
              </button>
            ))}
            {hasPositionNearby && positions.length > 1 && (
              <button
                onClick={deletePositionHere}
                className="px-4 py-2 text-xs font-medium rounded-xl bg-[#2a1515] text-[#ff6b6b] hover:bg-[#3a1f1f] border border-[#3a2020] transition-all"
              >
                Remove
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="px-8 py-6 border-t border-[#1a1a1a] bg-[#050505]">
        <div className="flex items-center justify-between mb-5">
          <div className="text-sm text-[#525252]">
            {positions.length} focus point{positions.length > 1 ? "s" : ""} · Crop snaps at each
          </div>
          <button
            onClick={onClose}
            className="px-5 py-2 text-[#525252] hover:text-white transition-all text-sm rounded-xl hover:bg-[#111]"
          >
            Cancel
          </button>
        </div>
        <button
          onClick={() => onExport(positions)}
          className="w-full py-4 bg-white text-black rounded-xl font-bold text-base hover:bg-[#e5e5e5] transition-all"
        >
          Export with {positions.length} Focus Point{positions.length > 1 ? "s" : ""}
        </button>
      </div>
    </div>
  );
}

// ==================== MAIN PAGE ====================
export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string>("");
  const [progress, setProgress] = useState<string>("");
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [clips, setClips] = useState<Clip[]>([]);
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([]);
  const [showTranscript, setShowTranscript] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [editingClip, setEditingClip] = useState<Clip | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [sourceVideoUrl, setSourceVideoUrl] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem("videotto_state");
    if (saved) {
      try {
        const data = JSON.parse(saved);
        if (data.jobId) setJobId(data.jobId);
        if (data.clips) setClips(data.clips);
        if (data.transcript) setTranscript(data.transcript);
        if (data.status) setStatus(data.status);
        if (data.sourceVideoUrl) setSourceVideoUrl(data.sourceVideoUrl);
      } catch (e) {
        console.error("Failed to load saved state", e);
      }
    }
  }, []);

  // Save to localStorage when state changes
  useEffect(() => {
    if (jobId || clips.length > 0) {
      localStorage.setItem("videotto_state", JSON.stringify({
        jobId,
        clips,
        transcript,
        status,
        sourceVideoUrl,
      }));
    }
  }, [jobId, clips, transcript, status, sourceVideoUrl]);

  // Clear cache and start fresh
  const clearCache = () => {
    localStorage.removeItem("videotto_state");
    setFile(null);
    setStatus("");
    setProgress("");
    setUploadProgress(0);
    setClips([]);
    setTranscript([]);
    setJobId(null);
    setSourceVideoUrl("");
    setIsProcessing(false);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) {
      setFile(e.target.files[0]);
      setClips([]);
      setTranscript([]);
      setStatus("");
      setJobId(null);
      setUploadProgress(0);
    }
  };

  // Add ETA to progress messages
  const getProgressWithETA = (progress: string): string => {
    const etaMap: Record<string, string> = {
      "Queued for processing...": "~5 min total",
      "Downloading video from S3...": "~1 min",
      "Transcribing with speaker diarization...": "~2 min",
      "Analyzing transcript for viral clips...": "~30 sec",
      "Extracting and uploading clips...": "~2 min",
    };
    
    for (const [key, eta] of Object.entries(etaMap)) {
      if (progress?.includes(key.replace("...", ""))) {
        return `${progress} (${eta})`;
      }
    }
    return progress;
  };

  const pollStatus = async (id: string) => {
    const res = await fetch(`${API_URL}/status/${id}`);
    const data: JobStatus = await res.json();

    setProgress(getProgressWithETA(data.progress));

    if (data.status === "completed") {
      setStatus("completed");
      setClips(data.result?.clips || []);
      setTranscript(data.transcript || []);
      setIsProcessing(false);
      
      // Get source video URL for crop editor
      const sourceRes = await fetch(`${API_URL}/source-url/${id}`);
      if (sourceRes.ok) {
        const sourceData = await sourceRes.json();
        setSourceVideoUrl(sourceData.url);
      }
    } else if (data.status === "failed") {
      setStatus("failed");
      setProgress(data.error || "Unknown error");
      setIsProcessing(false);
    } else {
      setTimeout(() => pollStatus(id), 2000);
    }
  };

  const handleSubmit = async () => {
    if (!file) return;

    setIsProcessing(true);
    setStatus("uploading");
    setProgress("Getting upload URL...");
    setClips([]);
    setUploadProgress(0);

    try {
      // Step 1: Get presigned URL from backend
      const contentType = file.type || "video/mp4";
      const urlRes = await fetch(`${API_URL}/get-upload-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, content_type: contentType }),
      });
      const { upload_url, s3_key, content_type } = await urlRes.json();

      // Step 2: Upload directly to S3 with progress tracking and retry
      const maxRetries = 3;
      let attempt = 0;
      
      while (attempt < maxRetries) {
        attempt++;
        setProgress(attempt > 1 ? `Retrying upload (attempt ${attempt}/${maxRetries})...` : "Uploading to S3...");
        const uploadStart = Date.now();
        
        try {
          await new Promise<void>((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.timeout = 0;
            
            xhr.upload.addEventListener("progress", (e) => {
              if (e.lengthComputable && e.loaded > 0) {
                const percent = Math.round((e.loaded / e.total) * 100);
                setUploadProgress(percent);
                const elapsed = (Date.now() - uploadStart) / 1000;
                const speed = e.loaded / elapsed;
                const remaining = Math.ceil((e.total - e.loaded) / speed);
                const mins = Math.floor(remaining / 60);
                const secs = remaining % 60;
                const eta = mins > 0 ? `~${mins}m ${secs}s` : `~${secs}s`;
                const retryText = attempt > 1 ? ` [retry ${attempt}]` : "";
                setProgress(`Uploading... ${percent}% (${eta} remaining)${retryText}`);
              }
            });
            
            xhr.addEventListener("load", () => {
              if (xhr.status >= 200 && xhr.status < 300) {
                resolve();
              } else {
                reject(new Error(`Status ${xhr.status}`));
              }
            });
            
            xhr.addEventListener("error", () => reject(new Error("Network error")));
            xhr.addEventListener("abort", () => reject(new Error("Aborted")));
            
            xhr.open("PUT", upload_url);
            xhr.setRequestHeader("Content-Type", content_type);
            xhr.send(file);
          });
          break; // Success, exit retry loop
        } catch (err) {
          if (attempt >= maxRetries) {
            throw new Error(`Upload failed after ${maxRetries} attempts. Check your connection and try again.`);
          }
          setProgress(`Upload failed, retrying in 3s... (attempt ${attempt}/${maxRetries})`);
          await new Promise(r => setTimeout(r, 3000));
          setUploadProgress(0);
        }
      }

      setProgress("Upload complete! Starting analysis...");

      // Step 3: Tell backend to process the S3 file
      const analyzeRes = await fetch(`${API_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ s3_key }),
      });
      const data = await analyzeRes.json();
      
      setJobId(data.job_id);
      setStatus("processing");
      pollStatus(data.job_id);
    } catch (err) {
      setStatus("failed");
      setProgress(err instanceof Error ? err.message : "Failed to upload");
      setIsProcessing(false);
    }
  };

  const handleExport = async (keyframes: Keyframe[]) => {
    if (!editingClip || !jobId) return;

    setEditingClip(null);
    setProgress(`Exporting clip ${editingClip.rank} with ${keyframes.length} focus point(s)...`);

    try {
      const res = await fetch(`${API_URL}/reexport`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          clip_rank: editingClip.rank,
          keyframes: keyframes,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setClips((prev) =>
          prev.map((c) =>
            c.rank === editingClip.rank ? { ...c, video_url: data.video_url, keyframes } : c
          )
        );
        setProgress("");
      } else {
        setProgress("Export failed");
        setTimeout(() => setProgress(""), 3000);
      }
    } catch {
      setProgress("Export failed");
      setTimeout(() => setProgress(""), 3000);
    }
  };

  return (
    <main className="min-h-screen p-8 max-w-4xl mx-auto">
      {editingClip && sourceVideoUrl && (
        <CropEditor
          clip={editingClip}
          videoSrc={sourceVideoUrl}
          onClose={() => setEditingClip(null)}
          onExport={handleExport}
        />
      )}

      <header className="mb-16 pt-12">
        <div className="flex items-start justify-between">
          <div className="fade-in">
            <h1 className="text-5xl font-semibold tracking-tight mb-3">Videotto</h1>
            <p className="text-[#737373] text-lg">Find viral clips in your videos</p>
          </div>
          {(clips.length > 0 || jobId) && (
            <button
              onClick={clearCache}
              className="text-sm text-[#525252] hover:text-white transition-all px-4 py-2 border border-[#262626] rounded-xl hover:border-[#404040] hover:bg-[#111] fade-in"
            >
              ↻ New Video
            </button>
          )}
        </div>
      </header>

      <section className="mb-12 fade-in" style={{ animationDelay: '0.1s' }}>
        <div
          onClick={() => fileInputRef.current?.click()}
          className="shine-border glow-hover border border-[#1f1f1f] rounded-2xl p-14 text-center cursor-pointer bg-[#0d0d0d] transition-all"
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            onChange={handleFileChange}
            className="hidden"
          />
          {file ? (
            <div>
              <p className="text-xl font-medium mb-2">{file.name}</p>
              <p className="text-[#737373]">
                {(file.size / (1024 * 1024)).toFixed(1)} MB
              </p>
            </div>
          ) : (
            <div>
              <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[#1a1a1a] flex items-center justify-center">
                <span className="text-2xl">↑</span>
              </div>
              <p className="text-[#a1a1a1] mb-2">Drop a video file or click to browse</p>
              <p className="text-[#404040] text-sm">MP4, MOV, AVI supported</p>
            </div>
          )}
        </div>

        <button
          onClick={handleSubmit}
          disabled={!file || isProcessing}
          className="mt-5 w-full bg-white text-black py-4 rounded-xl font-semibold disabled:opacity-20 disabled:cursor-not-allowed hover:bg-[#f0f0f0] transition-all relative overflow-hidden"
        >
          {isProcessing ? "Processing..." : "Analyze Video"}
        </button>
      </section>

      {(status && status !== "completed") || progress ? (
        <section className="mb-12 p-5 border border-[#1f1f1f] rounded-2xl bg-[#0d0d0d] fade-in">
          <div className="flex items-center gap-4">
            {isProcessing && (
              <div className="relative w-5 h-5">
                <div className="absolute inset-0 border-2 border-[#333] rounded-full" />
                <div className="absolute inset-0 border-2 border-white border-t-transparent rounded-full animate-spin" />
              </div>
            )}
            <span className="text-[#a1a1a1] font-medium">{progress}</span>
          </div>
          {uploadProgress > 0 && uploadProgress < 100 && (
            <div className="mt-4 h-1.5 bg-[#1a1a1a] rounded-full overflow-hidden">
              <div
                className="h-full bg-white rounded-full transition-all duration-300 ease-out"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          )}
        </section>
      ) : null}

      {clips.length > 0 && (
        <section className="fade-in">
          <h2 className="text-2xl font-semibold mb-8">Top Clips</h2>

          <div className="space-y-8 stagger">
            {clips.map((clip, index) => (
              <div 
                key={clip.rank} 
                className="shine-border glow-hover border border-[#1f1f1f] rounded-2xl overflow-hidden bg-[#0d0d0d] fade-in"
                style={{ animationDelay: `${index * 0.1}s` }}
              >
                {clip.video_url && (
                  <video
                    controls
                    className="w-full aspect-[9/16] max-h-[500px] bg-black object-contain"
                    src={`${clip.video_url}`}
                    crossOrigin="anonymous"
                  />
                )}

                <div className="p-6">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-semibold px-2.5 py-1 bg-white text-black rounded-full">
                        #{clip.rank}
                      </span>
                      <span className="text-sm font-mono text-[#737373]">
                        {formatTime(clip.start_time)} — {formatTime(clip.end_time)}
                      </span>
                    </div>
                    <div className="flex gap-1">
                      <button
                        onClick={() => setEditingClip(clip)}
                        className="text-sm text-[#737373] hover:text-white transition-all px-3 py-1.5 rounded-lg hover:bg-[#1a1a1a]"
                      >
                        Adjust
                      </button>
                      {clip.video_url && (
                        <a
                          href={clip.video_url}
                          download
                          className="text-sm text-[#737373] hover:text-white transition-all px-3 py-1.5 rounded-lg hover:bg-[#1a1a1a]"
                        >
                          Download
                        </a>
                      )}
                    </div>
                  </div>

                  <p className="text-[#a1a1a1] text-sm mb-4 italic leading-relaxed">
                    &ldquo;{clip.transcript_excerpt}&rdquo;
                  </p>

                  <p className="text-sm leading-relaxed text-[#d4d4d4]">{clip.explanation}</p>
                </div>
              </div>
            ))}
          </div>

          {transcript.length > 0 && (
            <div className="mt-10 border border-[#1f1f1f] rounded-2xl bg-[#0d0d0d] overflow-hidden">
              <button
                onClick={() => setShowTranscript(!showTranscript)}
                className="w-full p-5 flex items-center justify-between hover:bg-[#111] transition-all"
              >
                <span className="font-semibold">Full Transcript</span>
                <span className="text-[#525252] text-xl">{showTranscript ? "−" : "+"}</span>
              </button>

              {showTranscript && (
                <div className="px-5 pb-5 max-h-96 overflow-y-auto border-t border-[#1a1a1a]">
                  {transcript.map((seg, i) => (
                    <div key={i} className="py-3 flex gap-5 border-b border-[#141414] last:border-0">
                      <span className="text-[#404040] font-mono text-xs shrink-0 pt-0.5">
                        {formatTime(seg.start)}
                      </span>
                      <span className="text-[#a1a1a1] text-sm leading-relaxed">{seg.text}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </main>
  );
}
