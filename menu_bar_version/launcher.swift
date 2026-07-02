import Foundation

let executablePath = CommandLine.arguments[0]
let executableURL = URL(fileURLWithPath: executablePath).resolvingSymlinksInPath()
let macOSDir = executableURL.deletingLastPathComponent()
let contentsDir = macOSDir.deletingLastPathComponent()
let appBundle = contentsDir.deletingLastPathComponent()
let resourcesDir = contentsDir.appendingPathComponent("Resources")
let launcherScript = resourcesDir.appendingPathComponent("menubar_app.py")
let logDir = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library")
    .appendingPathComponent("Logs")
    .appendingPathComponent("Desktop Audio Translator Menu Bar")
let logFile = logDir.appendingPathComponent("menu-bar.log")

func isExecutable(_ path: String) -> Bool {
    return FileManager.default.isExecutableFile(atPath: path)
}

func firstExistingPython() -> String? {
    let bundledPython = resourcesDir.appendingPathComponent(".venv/bin/python").path
    if isExecutable(bundledPython) {
        return bundledPython
    }

    let candidates = [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
        "/usr/bin/python3",
    ]

    for candidate in candidates {
        if isExecutable(candidate) {
            return candidate
        }
    }

    return nil
}

func showDialog(_ message: String, icon: String = "caution") {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    process.arguments = [
        "-e",
        "display dialog \"\(message)\" buttons {\"OK\"} default button \"OK\" with icon \(icon)",
    ]
    try? process.run()
    process.waitUntilExit()
}

guard FileManager.default.fileExists(atPath: launcherScript.path) else {
    showDialog("The menu bar launcher is missing from this app bundle.", icon: "stop")
    exit(1)
}

guard let python = firstExistingPython() else {
    showDialog("Python 3 was not found. Install Python 3, then open Desktop Audio Translator Menu Bar again.")
    exit(1)
}

var environment = ProcessInfo.processInfo.environment
let defaultPath = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
environment["PATH"] = "\(defaultPath):\(environment["PATH"] ?? "")"
environment["DAT_APP_BUNDLE"] = appBundle.path
environment["DAT_SOURCE_DIR"] = resourcesDir.appendingPathComponent("src").path
environment["DAT_DISABLE_KEYBOARD"] = "1"
environment["PYTHONDONTWRITEBYTECODE"] = "1"

let process = Process()
process.executableURL = URL(fileURLWithPath: python)
process.arguments = [launcherScript.path]
process.currentDirectoryURL = resourcesDir
process.environment = environment

try? FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true)
if !FileManager.default.fileExists(atPath: logFile.path) {
    FileManager.default.createFile(atPath: logFile.path, contents: nil)
}
let logHandle = try? FileHandle(forWritingTo: logFile)
logHandle?.seekToEndOfFile()
process.standardOutput = logHandle
process.standardError = logHandle

do {
    try process.run()
    process.waitUntilExit()
    logHandle?.closeFile()
    exit(process.terminationStatus)
} catch {
    logHandle?.closeFile()
    showDialog("Desktop Audio Translator Menu Bar could not start: \(error.localizedDescription)")
    exit(1)
}
