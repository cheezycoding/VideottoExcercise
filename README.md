# Videotto

Turn long podcast videos into viral vertical clips. Upload → AI picks the best moments → Auto-crops to follow the speaker → Done.

## How It Works

1. **Transcribe** - Deepgram Nova-2 with speaker diarization
2. **Find clips** - Claude 3.5 Sonnet picks the 3 most viral-worthy 30-60s moments
3. **Smart crop** - Claude Sonnet 4 detects speaker positions, auto-crops to 9:16
4. **Manual adjust (WIP)** - Slide the 9:16 crop window over your desired area, set focus points at different timestamps
5. **Export** - Clips uploaded to S3, ready to download

## Cost Per Video

| Service | ~10 min video |
|---------|---------------|
| Deepgram (transcription) | $0.04 |
| Claude (clip selection) | $0.10 |
| Claude (speaker detection, ~12 frames) | $0.80 |
| **Total** | **~$1/video** |

## Run Locally

```bash
# Backend
cd Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Add to .env: DEEPGRAM_API_KEY, OPENROUTER_API_KEY, AWS credentials
python app.py

# Frontend
cd frontend
npm install && npm run dev
```

## Architecture

- **Frontend**: Next.js → uploads to S3 directly
- **Backend**: Flask on EC2 → downloads from S3, processes, uploads clips to S3
- **Storage**: S3 bucket (ap-southeast-1)

## Tradeoffs

| Choice | Why |
|--------|-----|
| LLM for clip selection | Understands context, humor, drama better than rules |
| LLM for speaker detection | Quick to implement, decent accuracy |
| Single gunicorn worker | Simpler state management for demo |

## Future Improvements

- **Better speaker tracking**: Use [fast-asd](https://github.com/sieve-community/fast-asd) - an optimized active speaker detection model. Faster, cheaper, more accurate than LLM-based frame analysis.
- **Persistent job state**: Redis instead of in-memory
- **YouTube/URL input**: Download from link
- **Auto-captions**: Burn subtitles into clips

---

Built for Videotto Engineering Internship Exercise.
