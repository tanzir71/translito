#!/bin/zsh

set -u

APP_DIR="${0:A:h}"
PYTHON=""

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

cd "$APP_DIR" || exit 1

if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
  PYTHON="$APP_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  osascript -e 'display dialog "Python 3 was not found. Install Python 3, then run this launcher again." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1
  exit 1
fi

if [[ ! -f "$APP_DIR/gui.py" ]]; then
  osascript -e 'display dialog "gui.py was not found next to this launcher." buttons {"OK"} default button "OK" with icon stop' >/dev/null 2>&1
  exit 1
fi

echo "Starting macOS Desktop Audio Translator..."
echo "App folder: $APP_DIR"
echo "Python: $PYTHON"
echo ""

"$PYTHON" "$APP_DIR/gui.py"
status=$?

if [[ $status -ne 0 ]]; then
  echo ""
  echo "The app exited with status $status."
  echo ""
  echo "If this is the first run, install dependencies with:"
  echo "  cd \"$APP_DIR\""
  echo "  \"$PYTHON\" -m pip install -r requirements.txt"
  echo ""
  read -k 1 "?Press any key to close this window..."
fi

exit $status
