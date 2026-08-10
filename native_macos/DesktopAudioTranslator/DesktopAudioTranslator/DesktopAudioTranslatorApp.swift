//
//  TranslitoApp.swift
//  Translito
//
//  Native macOS audio translator: captures system audio
//  (ScreenCaptureKit) or microphone/virtual devices (AVAudioEngine),
//  transcribes on-device with WhisperKit, translates on-device with
//  Apple's Translation framework.
//

import SwiftUI

@main
struct TranslitoApp: App {
    @StateObject private var settings: AppSettings
    @StateObject private var translationBridge: TranslationBridge
    @StateObject private var pipeline: TranslatorPipeline
    @StateObject private var hotkeys: HotkeyManager

    init() {
        let settings = AppSettings()
        let bridge = TranslationBridge()
        let pipeline = TranslatorPipeline(
            settings: settings,
            translationBridge: bridge
        )
        _settings = StateObject(wrappedValue: settings)
        _translationBridge = StateObject(wrappedValue: bridge)
        _pipeline = StateObject(wrappedValue: pipeline)
        _hotkeys = StateObject(wrappedValue: HotkeyManager(pipeline: pipeline))
        // Keep device pickers in sync with hardware changes.
        AudioDeviceObserver.shared.start()
    }

    var body: some Scene {
        Window("Translito", id: "main") {
            ContentView()
                .environmentObject(settings)
                .environmentObject(translationBridge)
                .environmentObject(pipeline)
        }
        .defaultSize(width: 760, height: 560)

        MenuBarExtra {
            MenuBarView()
                .environmentObject(settings)
                .environmentObject(pipeline)
        } label: {
            Image(systemName: pipeline.isRunning
                  ? "waveform.circle.fill"
                  : "waveform.circle")
        }

        Settings {
            SettingsView()
                .environmentObject(settings)
                .environmentObject(pipeline)
        }
    }
}
