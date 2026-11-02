#!/usr/bin/env bash
# Make Dish Shame start at boot instead of the Lab 2 IP screen (piscreen.service).
# The waiting screen shows the IP too, so you don't lose it.
#
#   bash install_service.sh            # install and start it now
#   bash install_service.sh --remove   # undo: back to the IP screen
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--remove" ]; then
  sudo systemctl disable --now dish-shame.service || true
  sudo rm -f /etc/systemd/system/dish-shame.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now piscreen.service
  echo "Dish Shame removed, IP screen is back."
  exit 0
fi

sudo systemctl disable --now piscreen.service || true
sudo cp dish-shame.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dish-shame.service
sudo systemctl restart dish-shame.service
sleep 3
systemctl --no-pager status dish-shame.service | head -5
echo
echo "Dish Shame is running and waits for the button."
echo "  live log:      journalctl -u dish-shame -f"
echo "  voice off/on:  touch quiet / rm quiet"
echo "  stop / start:  sudo systemctl stop dish-shame / sudo systemctl start dish-shame"
