#!/usr/bin/env bash
# Start Dish Shame inside tmux, so it keeps running after you close the laptop.
#
#   bash start_night.sh            # end the night with the button
#   bash start_night.sh 07:30      # ...or by itself at 7:30
#
# Watch it:  tmux attach -t dish     (leave again with Ctrl-b then d)
# Stop it:   tmux attach -t dish, then Ctrl-c
cd "$(dirname "$0")"
WAKE=${1:+--wake $1}
# No internet needed tonight: YOLO_OFFLINE stops ultralytics from trying to go online
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 YOLO_OFFLINE=1
if tmux has-session -t dish 2>/dev/null; then
  echo "Dish Shame is already running: tmux attach -t dish"
  exit 0
fi
tmux new-session -d -s dish \
  "source .venv/bin/activate && python -u dish_shame.py $WAKE 2>&1 | tee -a dish_shame.log; read -p 'stopped, press Enter'"
echo "Dish Shame started in tmux. Press the button when the counter is clean."
echo "Watch it with: tmux attach -t dish"
