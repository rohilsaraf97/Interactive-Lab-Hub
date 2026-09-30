# Synthesize to a file, then play it.
set -euo pipefail
VOICES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/voices"

python3 -m piper \
  --model en_US-amy-medium \
  --data-dir "$VOICES_DIR" \
  --output-file net_id_ques.wav \
  -- "What's your NetID?"
aplay net_id_ques.wav

arecord -d 5 -f cd -c 1 -r 16000 net_id.wav

python transcribe.py net_id.wav --model tiny.en