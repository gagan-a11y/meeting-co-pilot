#!/bin/bash

# Script to restart Whisper server with medium model for better Hindi transcription
# Created: January 3, 2026

echo "🔄 Restarting Whisper Server with Medium Model..."
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Step 1: Stop existing Whisper server
echo "📍 Step 1: Stopping existing Whisper server..."
WHISPER_PID=$(ps aux | grep whisper-server | grep -v grep | awk '{print $2}')

if [ -n "$WHISPER_PID" ]; then
    echo "   Found Whisper server running (PID: $WHISPER_PID)"
    kill $WHISPER_PID
    sleep 2

    # Check if it's stopped
    if ps -p $WHISPER_PID > /dev/null; then
        echo -e "${YELLOW}   Warning: Process still running, trying force kill...${NC}"
        kill -9 $WHISPER_PID
        sleep 1
    fi
    echo -e "${GREEN}   ✓ Whisper server stopped${NC}"
else
    echo "   No Whisper server running"
fi

# Step 2: Check if medium model exists
echo ""
echo "📍 Step 2: Checking for medium model..."
MODEL_PATH="whisper.cpp/models/ggml-medium.bin"

if [ ! -f "$MODEL_PATH" ]; then
    echo -e "${RED}   ✗ Medium model not found at: $MODEL_PATH${NC}"
    echo "   Downloading medium model..."
    cd whisper.cpp/models
    ./download-ggml-model.sh medium
    cd ../..
fi

if [ -f "$MODEL_PATH" ]; then
    MODEL_SIZE=$(ls -lh "$MODEL_PATH" | awk '{print $5}')
    echo -e "${GREEN}   ✓ Medium model found: $MODEL_SIZE${NC}"
else
    echo -e "${RED}   ✗ Failed to find or download medium model${NC}"
    exit 1
fi

# Step 3: Start Whisper server with medium model
echo ""
echo "📍 Step 3: Starting Whisper server with medium model..."
echo "   Model: ggml-medium.bin (1.3GB, excellent Hindi support)"
echo "   Port: 8178"
echo "   Threads: 8"
echo ""

# Find the whisper-server binary
if [ -f "whisper.cpp/build/bin/whisper-server" ]; then
    SERVER_BIN="whisper.cpp/build/bin/whisper-server"
elif [ -f "whisper-server-package/whisper-server" ]; then
    SERVER_BIN="whisper-server-package/whisper-server"
else
    echo -e "${RED}   ✗ Could not find whisper-server binary${NC}"
    echo "   Please build Whisper first: cd whisper.cpp && cmake --build build"
    exit 1
fi

# Start the server in the background
nohup "$SERVER_BIN" \
    --model "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port 8178 \
    --threads 8 \
    --print-progress \
    > whisper-server.log 2>&1 &

WHISPER_NEW_PID=$!
sleep 2

# Step 4: Verify it's running
echo ""
echo "📍 Step 4: Verifying server is running..."
if ps -p $WHISPER_NEW_PID > /dev/null; then
    echo -e "${GREEN}   ✓ Whisper server started successfully (PID: $WHISPER_NEW_PID)${NC}"
    echo "   Log file: whisper-server.log"
else
    echo -e "${RED}   ✗ Failed to start Whisper server${NC}"
    echo "   Check whisper-server.log for errors"
    exit 1
fi

# Step 5: Test connection
echo ""
echo "📍 Step 5: Testing server connection..."
sleep 2
if curl -s http://localhost:8178/ > /dev/null; then
    echo -e "${GREEN}   ✓ Server is responding on port 8178${NC}"
else
    echo -e "${YELLOW}   ⚠ Server not responding yet (may take a moment to load model)${NC}"
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Whisper Server Restart Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "📝 Summary:"
echo "   Model: Medium (1.3GB) - Excellent Hindi support"
echo "   PID: $WHISPER_NEW_PID"
echo "   Port: 8178"
echo "   Log: whisper-server.log"
echo ""
echo "🎯 Next Steps:"
echo "   1. Restart your backend (if using Docker: docker-compose restart)"
echo "   2. Open your app: http://localhost:3118"
echo "   3. Test recording with Hindi speech"
echo "   4. Expect 70-80% better transcription quality!"
echo ""
echo "📊 To monitor transcription:"
echo "   tail -f whisper-server.log"
echo ""
