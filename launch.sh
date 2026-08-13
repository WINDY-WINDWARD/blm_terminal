#!/bin/bash
cd "$(dirname "$0")"

echo "Starting BLM Backend in a new window (Production Mode)..."

# Determine python command
PY_CMD=$(command -v python3 &>/dev/null && echo python3 || echo python)

# Define the backend commands (always install, no --reload)
BACKEND_CMD="cd backend && if [ ! -d '.venv' ]; then $PY_CMD -m venv .venv; fi && source .venv/bin/activate && pip install -e . && uvicorn main:app --port 4455"

# Try to open a new terminal window using common Linux terminal emulators
if command -v gnome-terminal &> /dev/null; then
    gnome-terminal -- bash -c "$BACKEND_CMD; exec bash"
elif command -v konsole &> /dev/null; then
    konsole -e bash -c "$BACKEND_CMD; exec bash" &
elif command -v x-terminal-emulator &> /dev/null; then
    x-terminal-emulator -e bash -c "$BACKEND_CMD; exec bash" &
elif command -v xterm &> /dev/null; then
    xterm -e bash -c "$BACKEND_CMD; exec bash" &
else
    echo "Could not find a standard terminal emulator. Running backend in the background instead..."
    bash -c "$BACKEND_CMD" &
    BACKEND_PID=$!
    # Ensure backend is killed if the frontend script is stopped
    trap 'kill $BACKEND_PID 2>/dev/null' INT TERM EXIT
fi

echo "Setting up and starting BLM Frontend..."
npm install && npm run build && npm start
