//
//  ContentView.swift
//  DesktopAudioTranslator
//
//  Main window: source/language/model selection, live status and levels,
//  transcript list, and transcript actions. Also hosts the hidden
//  `.translationTask` that powers the Apple Translation bridge.
//

import SwiftUI
import AppKit
import Combine
import Translation

struct ContentView: View {
    @EnvironmentObject private var pipeline: TranslatorPipeline
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var translationBridge: TranslationBridge

    @State private var sources: [CaptureSource] = [.systemAudio]
    @State private var selectedSourceID: String = "system-audio"
    @State private var uiMode: TranslatorPipeline.Mode = .listen
    @State private var inputDevices: [AudioInputDevice] = []
    @State private var outputDevices: [AudioOutputDevice] = []
    @State private var selectedMicName: String = ""
    @State private var selectedOutputName: String = ""

    private var selectedSource: CaptureSource {
        sources.first { $0.id == selectedSourceID } ?? .systemAudio
    }

    private var selectedMic: AudioInputDevice? {
        inputDevices.first { $0.name == selectedMicName } ?? inputDevices.first { !$0.isVirtual }
    }

    private var selectedOutput: AudioOutputDevice? {
        outputDevices.first { $0.name == selectedOutputName }
    }

    var body: some View {
        VStack(spacing: 0) {
            modeBar
            Divider()
            if uiMode == .speak {
                speakControlBar
                speakRoutingBanner
            } else {
                controlBar
            }
            Divider()
            statusBar
            if let hint = pipeline.hint {
                hintBanner(hint)
            }
            if let detail = pipeline.status.detail {
                errorBanner(detail)
            }
            Divider()
            transcriptList
            Divider()
            bottomBar
        }
        .frame(minWidth: 640, minHeight: 480)
        .onAppear {
            refreshSources()
            restoreSelection()
            restoreMode()
            // Warm the ASR model in the background so Start is instant.
            Task { await pipeline.preloadModels() }
        }
        // Auto-refresh pickers when devices appear/disappear (headphones,
        // USB mics, BlackHole) — no restart or manual refresh needed.
        .onReceive(NotificationCenter.default.publisher(for: .audioDevicesDidChange)) { _ in
            refreshSources()
        }
        .onChange(of: uiMode) {
            if !pipeline.isRunning {
                settings.lastMode = uiMode.rawValue
            }
        }
        .onChange(of: pipeline.mode) {
            if pipeline.isRunning {
                uiMode = pipeline.mode
            }
        }
        // Hidden bridge to Apple's Translation framework. The session is
        // only valid inside this closure, so the bridge queues requests
        // and drains them here.
        .translationTask(translationBridge.configuration) { session in
            await translationBridge.drain(session: session)
        }
    }

    // MARK: - Mode

    private var modeBar: some View {
        HStack {
            Picker("Mode", selection: $uiMode) {
                Text("Translate Audio").tag(TranslatorPipeline.Mode.listen)
                Text("Speak Translation").tag(TranslatorPipeline.Mode.speak)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(maxWidth: 320)
            .disabled(pipeline.isRunning)
            Spacer()

            SettingsLink {
                Label("Settings", systemImage: "gearshape")
                    .labelStyle(.iconOnly)
            }
            .help("Settings")
        }
        .padding(.trailing, 12)
        .padding(.top, 10)
        .padding(.bottom, 4)
    }

    // MARK: - Speak Mode controls

    private var speakControlBar: some View {
        HStack(spacing: 12) {
            Picker("Mic", selection: $selectedMicName) {
                ForEach(inputDevices.filter { !$0.isVirtual }) { device in
                    Text(device.name).tag(device.name)
                }
            }
            .frame(maxWidth: 220)
            .disabled(pipeline.isRunning)

            Picker("Speak to", selection: $selectedOutputName) {
                ForEach(outputDevices) { device in
                    Text(device.isVirtual ? "\(device.name) (virtual)" : device.name)
                        .tag(device.name)
                }
            }
            .frame(maxWidth: 240)
            .disabled(pipeline.isRunning)

            Button {
                refreshSources()
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .help("Refresh audio devices")
            .disabled(pipeline.isRunning)

            Picker("From", selection: $settings.speakSourceLanguage) {
                ForEach(Languages.source) { language in
                    Text(language.name).tag(language.code)
                }
            }
            .frame(maxWidth: 160)
            .disabled(pipeline.isRunning)

            Picker("To", selection: $settings.speakTargetLanguage) {
                ForEach(Languages.target) { language in
                    Text(language.name).tag(language.code)
                }
            }
            .frame(maxWidth: 150)
            .disabled(pipeline.isRunning)

            Spacer()

            Button {
                let mic = selectedMic
                let output = selectedOutput
                Task {
                    if pipeline.isRunning {
                        await pipeline.stop(save: true)
                    } else if let mic {
                        await pipeline.startSpeakMode(micDevice: mic, outputDevice: output)
                    }
                }
            } label: {
                Label(
                    pipeline.isRunning ? "Stop" : "Start",
                    systemImage: pipeline.isRunning ? "stop.circle.fill" : "mic.circle.fill"
                )
                .frame(minWidth: 70)
            }
            .keyboardShortcut(.space, modifiers: [.command])
            .buttonStyle(.borderedProminent)
            .tint(pipeline.isRunning ? .red : .accentColor)
            .disabled(!pipeline.isRunning && selectedMic == nil)
        }
        .padding(12)
    }

    /// Routing guidance so the translated voice reaches Slack/Zoom.
    @ViewBuilder
    private var speakRoutingBanner: some View {
        if let output = selectedOutput, output.isVirtual {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "checkmark.circle")
                Text("In Slack/Zoom/Meet, set the **microphone** to \"\(output.name)\". Your translated voice will play into it. Use headphones so your mic doesn't pick up the room.")
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
            }
            .font(.callout)
            .padding(10)
            .background(.green.opacity(0.1))
        } else {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.circle")
                Text("To use this in Slack/Zoom, install [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole), pick it under \"Speak to\", then select \"BlackHole 2ch\" as the microphone in your conferencing app. Without it, speech plays to the selected output device only.")
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
            }
            .font(.callout)
            .padding(10)
            .background(.yellow.opacity(0.15))
        }
    }

    // MARK: - Controls

    private var controlBar: some View {
        HStack(spacing: 12) {
            Picker("Source", selection: $selectedSourceID) {
                ForEach(sources) { source in
                    Text(source.displayName).tag(source.id)
                }
            }
            .frame(maxWidth: 260)
            .disabled(pipeline.isRunning)

            Button {
                refreshSources()
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .help("Refresh audio devices")
            .disabled(pipeline.isRunning)

            Picker("From", selection: $settings.sourceLanguage) {
                ForEach(Languages.source) { language in
                    Text(language.name).tag(language.code)
                }
            }
            .frame(maxWidth: 170)
            .disabled(pipeline.isRunning)

            Picker("To", selection: $settings.targetLanguage) {
                ForEach(Languages.target) { language in
                    Text(language.name).tag(language.code)
                }
            }
            .frame(maxWidth: 160)
            .disabled(pipeline.isRunning)

            Spacer()

            Button {
                let source = selectedSource
                Task { await pipeline.toggle(source: source) }
            } label: {
                Label(
                    pipeline.isRunning ? "Stop" : "Start",
                    systemImage: pipeline.isRunning ? "stop.circle.fill" : "play.circle.fill"
                )
                .frame(minWidth: 70)
            }
            .keyboardShortcut(.space, modifiers: [.command])
            .buttonStyle(.borderedProminent)
            .tint(pipeline.isRunning ? .red : .accentColor)
        }
        .padding(12)
    }

    // MARK: - Status

    private var statusBar: some View {
        HStack(spacing: 12) {
            Circle()
                .fill(statusColor)
                .frame(width: 10, height: 10)

            if pipeline.status == .loadingModels {
                if let progress = pipeline.modelProgress {
                    ProgressView(value: progress)
                        .progressViewStyle(.linear)
                        .frame(width: 140)
                } else {
                    ProgressView()
                        .controlSize(.small)
                }
                Text(pipeline.loadingPhase ?? pipeline.status.label)
                    .font(.callout.weight(.medium))
                    .lineLimit(1)
                    .truncationMode(.tail)
            } else {
                Text(pipeline.status.label)
                    .font(.callout.weight(.medium))
            }

            if case .permissionNeeded = pipeline.status {
                permissionButtons
            }

            Spacer()

            if pipeline.isRunning {
                levelMeter
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    private var statusColor: Color {
        switch pipeline.status {
        case .ready: return .gray
        case .loadingModels: return .orange
        case .listening: return .green
        case .transcribing, .translating: return .blue
        case .speaking: return .purple
        case .noAudio: return .yellow
        case .permissionNeeded, .error: return .red
        }
    }

    private var permissionButtons: some View {
        HStack(spacing: 8) {
            if uiMode == .listen, case .systemAudio = selectedSource {
                Button("Open Screen Recording Settings") {
                    PermissionsManager.openScreenRecordingSettings()
                }
            } else {
                Button("Open Microphone Settings") {
                    PermissionsManager.openMicrophoneSettings()
                }
            }
        }
        .buttonStyle(.link)
    }

    private var levelMeter: some View {
        HStack(spacing: 6) {
            Image(systemName: "waveform")
                .foregroundStyle(.secondary)
            ProgressView(value: min(1.0, Double(pipeline.lastPeak)))
                .progressViewStyle(.linear)
                .frame(width: 120)
            Text(String(format: "peak %.4f", pipeline.lastPeak))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
    }

    private func hintBanner(_ hint: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lightbulb")
            Text(hint)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
        }
        .font(.callout)
        .padding(10)
        .background(.yellow.opacity(0.15))
    }

    private func errorBanner(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle")
            Text(message)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
        }
        .font(.callout)
        .foregroundStyle(.red)
        .padding(10)
        .background(.red.opacity(0.08))
    }

    // MARK: - Transcript

    private var transcriptList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if pipeline.entries.isEmpty {
                        emptyState
                    }
                    ForEach(pipeline.entries) { entry in
                        TranscriptRow(
                            entry: entry,
                            sourceIsRTL: Languages.isRightToLeft(settings.sourceLanguage),
                            targetIsRTL: Languages.isRightToLeft(settings.targetLanguage)
                        )
                        .id(entry.id)
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: pipeline.entries.count) {
                if let last = pipeline.entries.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "text.bubble")
                .font(.largeTitle)
                .foregroundStyle(.tertiary)
            Text("Transcripts will appear here")
                .foregroundStyle(.secondary)
            Text("Pick a source and press Start. System Audio captures whatever your Mac is playing — no BlackHole required.")
                .font(.callout)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 60)
    }

    // MARK: - Bottom bar

    private var bottomBar: some View {
        HStack(spacing: 12) {
            Text("\(pipeline.entries.count) entries")
                .font(.callout)
                .foregroundStyle(.secondary)

            Spacer()

            Button("Clear") {
                pipeline.clearTranscript()
            }
            .disabled(pipeline.entries.isEmpty)

            Button("Save Transcript") {
                pipeline.saveTranscript()
            }
            .disabled(pipeline.entries.isEmpty)

            Button("Show in Finder") {
                revealTranscripts()
            }
        }
        .padding(12)
    }

    // MARK: - Helpers

    private func refreshSources() {
        inputDevices = AudioDeviceManager.inputDevices()
        outputDevices = AudioDeviceManager.outputDevices()

        var list: [CaptureSource] = [.systemAudio]
        list.append(contentsOf: inputDevices.map { .inputDevice($0) })
        sources = list
        if !sources.contains(where: { $0.id == selectedSourceID }) {
            selectedSourceID = "system-audio"
        }

        // Speak Mode defaults: real mic in, virtual device (BlackHole) out.
        if !inputDevices.contains(where: { $0.name == selectedMicName }) {
            selectedMicName = inputDevices.first { $0.name == settings.speakMicName }?.name
                ?? inputDevices.first { !$0.isVirtual }?.name
                ?? inputDevices.first?.name
                ?? ""
        }
        if !outputDevices.contains(where: { $0.name == selectedOutputName }) {
            selectedOutputName = outputDevices.first { $0.name == settings.speakOutputDeviceName }?.name
                ?? outputDevices.first { $0.isVirtual }?.name
                ?? outputDevices.first?.name
                ?? ""
        }
    }

    private func restoreSelection() {
        // Restore last-used source (config.ini equivalent).
        if sources.contains(where: { $0.id == settings.selectedSourceID }) {
            selectedSourceID = settings.selectedSourceID
        } else if !settings.selectedDeviceName.isEmpty,
                  let match = sources.first(where: {
                      if case .inputDevice(let device) = $0 { return device.name == settings.selectedDeviceName }
                      return false
                  }) {
            selectedSourceID = match.id
        }
    }

    private func restoreMode() {
        if pipeline.isRunning {
            uiMode = pipeline.mode
        } else {
            uiMode = settings.lastMode == TranslatorPipeline.Mode.speak.rawValue ? .speak : .listen
        }
    }

    private func revealTranscripts() {
        if let saved = pipeline.lastSavedURL {
            NSWorkspace.shared.activateFileViewerSelecting([saved])
        } else {
            let folder = settings.transcriptFolder
            try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            NSWorkspace.shared.open(folder)
        }
    }
}

// MARK: - Transcript row

private struct TranscriptRow: View {
    let entry: TranscriptEntry
    let sourceIsRTL: Bool
    let targetIsRTL: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(entry.timestamp, style: .time)
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                Text(entry.sourceInfo)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
            Text(entry.sourceText)
                .font(.body)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: sourceIsRTL ? .trailing : .leading)
                .environment(\.layoutDirection, sourceIsRTL ? .rightToLeft : .leftToRight)
            if !entry.translatedText.isEmpty {
                Text(entry.translatedText)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: targetIsRTL ? .trailing : .leading)
                    .environment(\.layoutDirection, targetIsRTL ? .rightToLeft : .leftToRight)
            }
        }
        .padding(10)
        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
    }
}
