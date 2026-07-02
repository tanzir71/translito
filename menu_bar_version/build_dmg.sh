#!/bin/zsh
set -euo pipefail

ROOT_DIR="${0:A:h}"
APP_NAME="Desktop Audio Translator Menu Bar"
APP_EXECUTABLE="MenuBarLauncher"
APP_TEMPLATE="$ROOT_DIR/app"
APP_BUILD="$ROOT_DIR/dist/$APP_NAME.app"
DMG_STAGING="$ROOT_DIR/dist/dmg-staging"
DMG_PATH="$ROOT_DIR/dist/Desktop_Audio_Translator_Menu_Bar.dmg"

rm -rf "$APP_BUILD" "$DMG_STAGING" "$DMG_PATH"
mkdir -p "$ROOT_DIR/dist"

cp -R "$APP_TEMPLATE" "$APP_BUILD"
mkdir -p "$APP_BUILD/Contents/Resources/src"
cp "$ROOT_DIR/src/gui.py" "$APP_BUILD/Contents/Resources/src/gui.py"
cp "$ROOT_DIR/src/main.py" "$APP_BUILD/Contents/Resources/src/main.py"
cp "$ROOT_DIR/src/requirements.txt" "$APP_BUILD/Contents/Resources/src/requirements.txt"
if [[ -f "$ROOT_DIR/src/config.ini" ]]; then
  cp "$ROOT_DIR/src/config.ini" "$APP_BUILD/Contents/Resources/src/config.ini"
fi
rm -f "$APP_BUILD/Contents/MacOS/$APP_NAME"
swiftc "$ROOT_DIR/launcher.swift" -o "$APP_BUILD/Contents/MacOS/$APP_EXECUTABLE"
chmod +x "$APP_BUILD/Contents/MacOS/$APP_EXECUTABLE"
find "$APP_BUILD" -name .DS_Store -type f -delete
find "$APP_BUILD" -name __pycache__ -type d -prune -exec rm -rf {} +
codesign --force --deep --sign - "$APP_BUILD" >/dev/null

mkdir -p "$DMG_STAGING"
cp -R "$APP_BUILD" "$DMG_STAGING/$APP_NAME.app"
ln -s /Applications "$DMG_STAGING/Applications"
find "$DMG_STAGING" -name .DS_Store -type f -delete

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$DMG_STAGING" \
  -ov \
  -format UDZO \
  "$DMG_PATH"
rm -rf "$DMG_STAGING"

echo "Built:"
echo "  $APP_BUILD"
echo "  $DMG_PATH"
