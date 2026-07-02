//
//  SettingsView.swift
//  DesktopAudioTranslator
//
//  App settings: languages, Whisper model, chunking, capture options,
//  and the transcript folder.
//

import SwiftUI
import AppKit
import AVFoundation
import ServiceManagement
import KeyboardShortcuts

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var pipeline: TranslatorPipeline
    @State private var openAtLogin = SMAppService.mainApp.status == .enabled
    @State private var loginItemError: String?

    var body: some View {
        Form {
            Section("General") {
                Toggle("Open at login", isOn: $openAtLogin)
                    .onChange(of: openAtLogin) { _, enable in
                        do {
                            if enable {
                                try SMAppService.mainApp.register()
                            } else {
                                try SMAppService.mainApp.unregister()
                            }
                            loginItemError = nil
                        } catch {
                            loginItemError = error.localizedDescription
                            openAtLogin = SMAppService.mainApp.status == .enabled
                        }
                    }
                if let loginItemError {
                    Text(loginItemError)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }

            Section("Hotkeys") {
                KeyboardShortcuts.Recorder("Toggle Listen / Speak", name: .toggleListenSpeak)
                KeyboardShortcuts.Recorder("Start Listening", name: .startListening)
                KeyboardShortcuts.Recorder("Start Speaking", name: .startSpeaking)
                KeyboardShortcuts.Recorder("Stop", name: .stopCapture)
                Text("Hotkeys work system-wide, even while you're in Slack or Zoom. Toggle starts automatically: from idle it starts your last-used mode; while running it switches between listening and speaking. Start hotkeys use your saved devices.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Languages") {
                Picker("Source language", selection: $settings.sourceLanguage) {
                    ForEach(Languages.source) { language in
                        Text(language.name).tag(language.code)
                    }
                }
                Picker("Target language", selection: $settings.targetLanguage) {
                    ForEach(Languages.target) { language in
                        Text(language.name).tag(language.code)
                    }
                }
                Text("Translation runs on-device with Apple's Translation framework. macOS may prompt once to download a language pack.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Speech Recognition") {
                Picker("Whisper model", selection: $settings.whisperModel) {
                    ForEach(TranscriptionEngine.availableModels, id: \.self) { model in
                        Text(model).tag(model)
                    }
                }
                Text("Models download once on first use (via WhisperKit), then run fully offline. \"small\" matches the Python app's default; larger models are more accurate but slower.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                LabeledContent("Chunk length") {
                    HStack {
                        Slider(value: $settings.chunkDuration, in: 3...15, step: 1)
                            .frame(width: 180)
                        Text("\(Int(settings.chunkDuration)) s")
                            .monospacedDigit()
                    }
                }
            }

            Section("Capture") {
                Toggle("Exclude this app's own audio (System Audio mode)", isOn: $settings.excludeAppAudio)

                LabeledContent("Mic noise gate") {
                    HStack {
                        Slider(value: $settings.micNoiseGate, in: 0...0.008)
                            .frame(width: 180)
                        Text(noiseGateLabel)
                            .frame(width: 70, alignment: .leading)
                            .monospacedDigit()
                    }
                }
                Text("Ignores microphone audio quieter than this level (background noise, distant sounds). Raise it in noisy rooms; lower it if soft speech gets cut off. Off transcribes everything. Applies only to microphones — never to System Audio or virtual devices.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Text("System Audio uses ScreenCaptureKit and needs Screen Recording permission. Microphone and virtual devices (BlackHole) use the standard input path and need Microphone permission.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Speak Mode") {
                Picker("Voice", selection: $settings.speakVoiceID) {
                    Text("Automatic (\(Languages.name(for: settings.speakTargetLanguage)))").tag("")
                    ForEach(SpeechOutputService.voices(forLanguageCode: settings.speakTargetLanguage), id: \.identifier) { voice in
                        Text("\(voice.name) (\(voice.language))").tag(voice.identifier)
                    }
                }
                Toggle("Also play spoken translation through my speakers", isOn: $settings.monitorSpokenAudio)
                Text("Speak Mode turns your speech into spoken translation on a chosen output device. Route it into Slack/Zoom by installing BlackHole 2ch, speaking to it here, and selecting it as the microphone in the conferencing app. Higher-quality voices can be added in System Settings → Accessibility → Spoken Content.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Transcripts") {
                LabeledContent("Folder") {
                    Text(settings.transcriptFolder.path)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Button("Choose Folder…") { chooseFolder() }
                    if settings.usesCustomTranscriptFolder {
                        Button("Use Default") { settings.resetTranscriptFolder() }
                    }
                    Button("Open Folder") {
                        let folder = settings.transcriptFolder
                        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                        NSWorkspace.shared.open(folder)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 520)
        .disabled(pipeline.isRunning)
        .overlay(alignment: .top) {
            if pipeline.isRunning {
                Text("Stop capture to change settings.")
                    .font(.callout)
                    .padding(8)
                    .background(.yellow.opacity(0.2), in: Capsule())
                    .padding(.top, 8)
            }
        }
    }

    private var noiseGateLabel: String {
        switch settings.micNoiseGate {
        case 0: return "Off"
        case ..<0.0015: return "Low"
        case ..<0.003: return "Medium"
        default: return "High"
        }
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Choose"
        if panel.runModal() == .OK, let url = panel.url {
            settings.setTranscriptFolder(url)
        }
    }
}
