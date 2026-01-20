#!/bin/bash
# Production startup script for Videotto Backend

cd /home/ubuntu/videotto/Backend

# Activate virtual environment
source venv/bin/activate

# Run with gunicorn (4 workers, bind to all interfaces)
gunicorn -w 4 -b 0.0.0.0:5001 --timeout 300 app:app
