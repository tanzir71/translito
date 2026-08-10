//
//  MenuBarView.swift
//  DesktopAudioTranslator
//
//  Menu bar extra: quick status, start/stop, latest translation,
//  and shortcuts to the main window and transcript folder.
//

import SwiftUI
import AppKit

struct MenuBarView: View {
    @EnvironmentObject private var pipeline: TranslatorPipeline
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading) {
            Text(pipeline.status.label)

            if let latest = pipeline.entries.last {
                Divider()
                Text(latest.translatedText.isEmpty ? latest.sourceText : latest.translatedText)
                    .lineLimit(3)
            }

            Divider()

            Button(pipeline.isRunning ? "Stop" : "Start Listening") {
                Task {
                    if pipeline.isRunning {
                        await pipeline.stop(save: true)
                    } else {
                        await pipeline.startListeningWithSavedSource()
                    }
                }
            }
            .keyboardShortcut("s")

            if !pipeline.isRunning {
                Button("Start Speak Mode") {
                    Task { await pipeline.startSpeakingWithSavedDevices() }
                }
                .keyboardShortcut("k")
            }

            Button("Open Translator Window") {
                openWindow(id: "main")
                NSApp.activate(ignoringOtherApps: true)
            }
            .keyboardShortcut("o")

            Button("Save Transcript") {
                pipeline.saveTranscript()
            }
            .disabled(pipeline.entries.isEmpty)

            Divider()

            SettingsLink {
                Text("Settings…")
            }
            .keyboardShortcut(",", modifiers: .command)

            Button("Quit") {
                Task {
                    await pipeline.stop(save: true)
                    NSApp.terminate(nil)
                }
            }
            .keyboardShortcut("q")
        }
    }

}
