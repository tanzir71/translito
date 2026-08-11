//
//  MenuBarView.swift
//  DesktopAudioTranslator
//
//  Compact menu-bar control center for choosing a translation mode,
//  starting or stopping capture, and reviewing recent translations.
//

import SwiftUI
import AppKit

struct MenuBarView: View {
    @EnvironmentObject private var pipeline: TranslatorPipeline
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.openWindow) private var openWindow

    @State private var isChangingRunState = false

    private var selectedMode: TranslatorPipeline.Mode {
        if pipeline.isRunning {
            return pipeline.mode
        }
        return settings.lastMode == TranslatorPipeline.Mode.speak.rawValue ? .speak : .listen
    }

    private var recentEntries: [TranscriptEntry] {
        Array(pipeline.entries.suffix(3).reversed())
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            controls
            Divider()
            translations
            Divider()
            footer
        }
        .frame(width: 360)
        .background(.regularMaterial)
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: 10) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .scaledToFit()
                .frame(width: 32, height: 32)
                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))

            VStack(alignment: .leading, spacing: 1) {
                Text("Translito")
                    .font(.headline)
                Text(languagePair)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            HStack(spacing: 6) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 7, height: 7)
                Text(pipeline.status.label)
                    .lineLimit(1)
            }
            .font(.caption.weight(.medium))
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .background(.primary.opacity(0.06), in: Capsule())
        }
        .padding(14)
    }

    // MARK: - Controls

    private var controls: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("MODE")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)

            HStack(spacing: 8) {
                modeButton(
                    .listen,
                    title: "Listen",
                    subtitle: "Translate audio",
                    systemImage: "headphones"
                )
                modeButton(
                    .speak,
                    title: "Speak",
                    subtitle: "Voice translation",
                    systemImage: "waveform.and.mic"
                )
            }

            HStack(spacing: 8) {
                Image(systemName: selectedMode == .listen ? "speaker.wave.2" : "arrow.triangle.2.circlepath")
                    .foregroundStyle(.secondary)
                    .frame(width: 16)
                Text(routeSummary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer()
            }

            Button(action: toggleRunning) {
                HStack(spacing: 8) {
                    if isChangingRunState || pipeline.status == .loadingModels {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: pipeline.isRunning ? "stop.fill" : "play.fill")
                    }
                    Text(primaryActionTitle)
                        .fontWeight(.semibold)
                }
                .frame(maxWidth: .infinity)
                .frame(height: 26)
            }
            .buttonStyle(.borderedProminent)
            .tint(pipeline.isRunning ? .red : .accentColor)
            .controlSize(.large)
            .keyboardShortcut(.space, modifiers: [.command])
            .disabled(isChangingRunState)

            if pipeline.status == .loadingModels, let progress = pipeline.modelProgress {
                ProgressView(value: progress)
                    .progressViewStyle(.linear)
            }

            if let message = pipeline.status.detail ?? pipeline.hint {
                Label(message, systemImage: pipeline.status.detail == nil ? "lightbulb" : "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(pipeline.status.detail == nil ? Color.secondary : Color.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
    }

    private func modeButton(
        _ mode: TranslatorPipeline.Mode,
        title: String,
        subtitle: String,
        systemImage: String
    ) -> some View {
        let isSelected = selectedMode == mode

        return Button {
            selectMode(mode)
        } label: {
            HStack(spacing: 9) {
                Image(systemName: systemImage)
                    .font(.system(size: 15, weight: .semibold))
                    .frame(width: 20)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title)
                        .font(.callout.weight(.semibold))
                    Text(subtitle)
                        .font(.caption2)
                        .foregroundStyle(isSelected ? Color.white.opacity(0.8) : Color.secondary)
                }
                Spacer(minLength: 0)
            }
            .foregroundStyle(isSelected ? Color.white : Color.primary)
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(
                isSelected ? Color.accentColor : Color.primary.opacity(0.055),
                in: RoundedRectangle(cornerRadius: 9, style: .continuous)
            )
            .overlay {
                if !isSelected {
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .stroke(.primary.opacity(0.08))
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(isChangingRunState)
    }

    // MARK: - Translations

    private var translations: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("RECENT TRANSLATIONS")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                if !pipeline.entries.isEmpty {
                    Text("\(pipeline.entries.count)")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }

            if recentEntries.isEmpty {
                HStack(spacing: 10) {
                    Image(systemName: "text.bubble")
                        .font(.title3)
                        .foregroundStyle(.tertiary)
                    Text("Translations will appear here while Translito is running.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(.vertical, 12)
            } else {
                VStack(spacing: 7) {
                    ForEach(recentEntries) { entry in
                        translationRow(entry)
                    }
                }
            }
        }
        .padding(14)
    }

    private func translationRow(_ entry: TranscriptEntry) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(entry.translatedText.isEmpty ? "Translating…" : entry.translatedText)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(entry.translatedText.isEmpty ? Color.secondary : Color.primary)
                    .lineLimit(2)
                Spacer(minLength: 4)
                Text(entry.timestamp, style: .time)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.tertiary)
            }

            Text(entry.sourceText)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .contextMenu {
            Button("Copy Translation") {
                copyToPasteboard(entry.translatedText.isEmpty ? entry.sourceText : entry.translatedText)
            }
            Button("Copy Source") {
                copyToPasteboard(entry.sourceText)
            }
        }
    }

    // MARK: - Footer

    private var footer: some View {
        HStack(spacing: 6) {
            Button(action: openTranslatorWindow) {
                Label("Open Translito", systemImage: "macwindow")
            }
            .keyboardShortcut("o", modifiers: .command)

            Spacer()

            Button {
                pipeline.saveTranscript()
            } label: {
                Image(systemName: "square.and.arrow.down")
            }
            .help("Save transcript")
            .disabled(pipeline.entries.isEmpty)

            SettingsLink {
                Image(systemName: "gearshape")
            }
            .help("Settings")
            .keyboardShortcut(",", modifiers: .command)

            Menu {
                Button("Quit Translito") {
                    Task {
                        await pipeline.stop(save: true)
                        NSApp.terminate(nil)
                    }
                }
                .keyboardShortcut("q", modifiers: .command)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .help("More")
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
    }

    // MARK: - Actions and display state

    private func selectMode(_ mode: TranslatorPipeline.Mode) {
        guard mode != selectedMode else { return }
        settings.lastMode = mode.rawValue
        guard pipeline.isRunning else { return }

        isChangingRunState = true
        Task {
            if mode == .listen {
                await pipeline.startListeningWithSavedSource()
            } else {
                await pipeline.startSpeakingWithSavedDevices()
            }
            isChangingRunState = false
        }
    }

    private func toggleRunning() {
        isChangingRunState = true
        Task {
            if pipeline.isRunning {
                await pipeline.stop(save: true)
            } else if selectedMode == .listen {
                await pipeline.startListeningWithSavedSource()
            } else {
                await pipeline.startSpeakingWithSavedDevices()
            }
            isChangingRunState = false
        }
    }

    private func openTranslatorWindow() {
        openWindow(id: "main")
        NSApp.activate(ignoringOtherApps: true)
    }

    private func copyToPasteboard(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    private var primaryActionTitle: String {
        if isChangingRunState {
            return pipeline.isRunning ? "Stopping…" : "Starting…"
        }
        if pipeline.isRunning {
            return selectedMode == .listen ? "Stop Listening" : "Stop Speaking"
        }
        return selectedMode == .listen ? "Start Listening" : "Start Speaking"
    }

    private var languagePair: String {
        let sourceCode = selectedMode == .listen ? settings.sourceLanguage : settings.speakSourceLanguage
        let targetCode = selectedMode == .listen ? settings.targetLanguage : settings.speakTargetLanguage
        return "\(Languages.name(for: sourceCode)) → \(Languages.name(for: targetCode))"
    }

    private var routeSummary: String {
        if selectedMode == .listen {
            if settings.selectedSourceID == "system-audio" {
                return "Listening to System Audio"
            }
            return "Listening to \(settings.selectedDeviceName.isEmpty ? "saved input" : settings.selectedDeviceName)"
        }

        let mic = settings.speakMicName.isEmpty ? "Default microphone" : settings.speakMicName
        let output = settings.speakOutputDeviceName.isEmpty ? "Default output" : settings.speakOutputDeviceName
        return "\(mic) → \(output)"
    }

    private var statusColor: Color {
        switch pipeline.status {
        case .ready: return .secondary
        case .loadingModels, .noAudio: return .orange
        case .listening: return .green
        case .transcribing, .translating: return .blue
        case .speaking: return .purple
        case .permissionNeeded, .error: return .red
        }
    }
}
