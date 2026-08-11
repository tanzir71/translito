#!/bin/zsh
set -euo pipefail

ROOT_DIR="${0:A:h}"
APP_NAME="Translito"
PROJECT_PATH="$ROOT_DIR/DesktopAudioTranslator/DesktopAudioTranslator.xcodeproj"
SCHEME="DesktopAudioTranslator"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"
APP_BUILD="$DIST_DIR/$APP_NAME.app"
DMG_STAGING="$DIST_DIR/dmg-staging"
DMG_PATH="$ROOT_DIR/$APP_NAME.dmg"
ICON_PATH="$ROOT_DIR/branding/Translito.icns"
ENTITLEMENTS_PATH="$ROOT_DIR/DesktopAudioTranslator/DesktopAudioTranslator/DesktopAudioTranslator.entitlements"

SOURCE_APP=""
PREBUILT_MODE=0

if [[ $# -eq 2 && "$1" == "--prebuilt" ]]; then
  SOURCE_APP="$2"
  PREBUILT_MODE=1
elif [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--prebuilt /path/to/App.app]" >&2
  exit 2
fi

if [[ -z "$SOURCE_APP" ]]; then
  DEVELOPER_PATH="${DEVELOPER_DIR:-$(xcode-select -p 2>/dev/null || true)}"
  XCODEBUILD_PATH="$DEVELOPER_PATH/usr/bin/xcodebuild"
  if [[ ! -x "$XCODEBUILD_PATH" ]]; then
    echo "Xcode is required to compile Translito. Install Xcode or pass --prebuilt with an existing native app bundle." >&2
    exit 1
  fi

  "$XCODEBUILD_PATH" \
    -project "$PROJECT_PATH" \
    -scheme "$SCHEME" \
    -configuration Release \
    -derivedDataPath "$BUILD_DIR" \
    ARCHS="arm64 x86_64" \
    ONLY_ACTIVE_ARCH=NO \
    CODE_SIGNING_ALLOWED=NO \
    build
  SOURCE_APP="$BUILD_DIR/Build/Products/Release/$APP_NAME.app"
fi

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "App bundle not found: $SOURCE_APP" >&2
  exit 1
fi

rm -rf "$APP_BUILD" "$DMG_STAGING"
rm -f "$DMG_PATH"
mkdir -p "$DIST_DIR"
cp -R "$SOURCE_APP" "$APP_BUILD"

PLIST="$APP_BUILD/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $APP_NAME" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string $APP_NAME" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleName $APP_NAME" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier tanziro.Translito" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :NSMicrophoneUsageDescription Translito needs microphone access to transcribe and translate speech from your microphone or virtual audio devices like BlackHole." "$PLIST"

# The checked-in native snapshot predates the rebrand. Its only user-visible
# legacy literals are the window title and transcript heading in both slices of
# the universal binary. This byte-for-byte replacement preserves Mach-O layout.
if [[ $PREBUILT_MODE -eq 1 ]]; then
  EXECUTABLE_NAME="$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$PLIST")"
  EXECUTABLE_PATH="$APP_BUILD/Contents/MacOS/$EXECUTABLE_NAME"
  if [[ -f "$EXECUTABLE_PATH" ]]; then
    /usr/bin/perl -0pi -e 's/Desktop Audio Translator/Translito \xE2\x80\x94 Translator/g' "$EXECUTABLE_PATH"
  fi
fi

if [[ -f "$ICON_PATH" ]]; then
  mkdir -p "$APP_BUILD/Contents/Resources"
  cp "$ICON_PATH" "$APP_BUILD/Contents/Resources/Translito.icns"
  /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile Translito.icns" "$PLIST" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string Translito.icns" "$PLIST"
fi

/usr/bin/codesign \
  --force \
  --deep \
  --sign - \
  --options runtime \
  --entitlements "$ENTITLEMENTS_PATH" \
  "$APP_BUILD"

mkdir -p "$DMG_STAGING"
cp -R "$APP_BUILD" "$DMG_STAGING/$APP_NAME.app"
ln -s /Applications "$DMG_STAGING/Applications"

/usr/bin/hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$DMG_STAGING" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

rm -rf "$DMG_STAGING"

echo "Built $APP_BUILD"
echo "Built $DMG_PATH"
