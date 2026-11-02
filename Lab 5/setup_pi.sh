#!/usr/bin/env bash
# One-time setup for Lab 5 + Dish Shame on the Pi. Safe to run again: it skips what is done.
#
#   cd ~/Interactive-Lab-Hub/"Lab 5"
#   bash setup_pi.sh
#
# Takes a while the first time (torch, Qwen models: a couple of GB).
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/6 locale fix (stops ultralytics' UnicodeEncodeError spam, see README Part A)"
if ! grep -q "PYTHONIOENCODING=utf-8" ~/.bashrc; then
  printf '%s\n' 'export LANG=C.UTF-8' 'export LC_ALL=C.UTF-8' 'export PYTHONIOENCODING=utf-8' >> ~/.bashrc
fi
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8

echo "== 2/6 system packages (tmux keeps the night running after ssh disconnects)"
sudo apt-get install -y tmux alsa-utils fonts-dejavu-core

echo "== 3/6 Python environment"
# --system-site-packages so the Pi's GPIO libraries (lgpio) are visible, like the Lab 4 venv
[ -d .venv ] || python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r dish_requirements.txt

echo "== 4/6 YOLO model"
if [ -d yolo26n_ncnn_model ]; then
  echo "yolo26n_ncnn_model already here"
else
  python -c "from ultralytics import YOLO; YOLO('yolo26n.pt').export(format='ncnn')"
fi

echo "== 5/6 Ollama + Qwen"
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
for m in qwen3.5:0.8b qwen3:0.6b; do
  ollama list | grep -q "^$m" || ollama pull "$m"
done
ollama list

echo "== 6/6 Piper voice for the morning report"
mkdir -p voices
[ -f voices/en_US-lessac-medium.onnx ] || python -m piper.download_voices en_US-lessac-medium --data-dir voices

echo
echo "Done. Quick checks:"
echo "  source .venv/bin/activate"
echo "  python dish_hw.py                        # screen, button, flag, voice"
echo "  python dish_detect.py                    # one look with the webcam -> look.jpg"
echo "  python dish_shame.py --fake 60 --interval 5 --once   # a one-minute fake night"
