//
//  AppSettings.swift
//  DesktopAudioTranslator
//
//  Persisted user preferences. The native replacement for config.ini —
//  device/language/model choices survive relaunches.
//

import Foundation
import Combine
import SwiftUI

@MainActor
final class AppSettings: ObservableObject {

    private enum Keys {
        static let sourceLanguage = "sourceLanguage"
        static let targetLanguage = "targetLanguage"
        static let whisperModel = "whisperModel"
        static let chunkDuration = "chunkDuration"
        static let excludeAppAudio = "excludeAppAudio"
        static let selectedSourceID = "selectedSourceID"
        static let selectedDeviceName = "selectedDeviceName"
        static let transcriptFolderBookmark = "transcriptFolderBookmark"
        // Speak Mode
        static let speakSourceLanguage = "speakSourceLanguage"
        static let speakTargetLanguage = "speakTargetLanguage"
        static let speakMicName = "speakMicName"
        static let speakOutputDeviceName = "speakOutputDeviceName"
        static let speakVoiceID = "speakVoiceID"
        static let monitorSpokenAudio = "monitorSpokenAudio"
        static let micNoiseGate = "micNoiseGate"
        static let lastMode = "lastMode"
    }

    private let defaults = UserDefaults.standard

    @Published var sourceLanguage: String {
        didSet { defaults.set(sourceLanguage, forKey: Keys.sourceLanguage) }
    }
    @Published var targetLanguage: String {
        didSet { defaults.set(targetLanguage, forKey: Keys.targetLanguage) }
    }
    @Published var whisperModel: String {
        didSet { defaults.set(whisperModel, forKey: Keys.whisperModel) }
    }
    @Published var chunkDuration: Double {
        didSet { defaults.set(chunkDuration, forKey: Keys.chunkDuration) }
    }
    @Published var excludeAppAudio: Bool {
        didSet { defaults.set(excludeAppAudio, forKey: Keys.excludeAppAudio) }
    }
    /// "system-audio" or "device-<name>", used to restore the last source.
    @Published var selectedSourceID: String {
        didSet { defaults.set(selectedSourceID, forKey: Keys.selectedSourceID) }
    }
    @Published var selectedDeviceName: String {
        didSet { defaults.set(selectedDeviceName, forKey: Keys.selectedDeviceName) }
    }

    // MARK: Speak Mode (you speak → app speaks the translation into a
    // virtual output device that conferencing apps use as their mic)

    @Published var speakSourceLanguage: String {
        didSet { defaults.set(speakSourceLanguage, forKey: Keys.speakSourceLanguage) }
    }
    @Published var speakTargetLanguage: String {
        didSet { defaults.set(speakTargetLanguage, forKey: Keys.speakTargetLanguage) }
    }
    @Published var speakMicName: String {
        didSet { defaults.set(speakMicName, forKey: Keys.speakMicName) }
    }
    @Published var speakOutputDeviceName: String {
        didSet { defaults.set(speakOutputDeviceName, forKey: Keys.speakOutputDeviceName) }
    }
    /// AVSpeechSynthesisVoice identifier, empty = automatic for language.
    @Published var speakVoiceID: String {
        didSet { defaults.set(speakVoiceID, forKey: Keys.speakVoiceID) }
    }
    /// Also play the synthesized speech through the default output so
    /// the user hears what participants hear.
    @Published var monitorSpokenAudio: Bool {
        didSet { defaults.set(monitorSpokenAudio, forKey: Keys.monitorSpokenAudio) }
    }
    /// Ambient-noise gate for microphone capture (RMS threshold).
    /// 0 disables the gate. Higher values ignore more background noise
    /// but may clip very soft speech. Never applied to system audio or
    /// virtual devices.
    @Published var micNoiseGate: Double {
        didSet { defaults.set(micNoiseGate, forKey: Keys.micNoiseGate) }
    }
    /// Last capture mode ("listen" / "speak"), used by the toggle hotkey
    /// to pick what to start from idle.
    @Published var lastMode: String {
        didSet { defaults.set(lastMode, forKey: Keys.lastMode) }
    }

    init() {
        sourceLanguage = defaults.string(forKey: Keys.sourceLanguage) ?? "ar"
        targetLanguage = defaults.string(forKey: Keys.targetLanguage) ?? "en"
        whisperModel = defaults.string(forKey: Keys.whisperModel) ?? "small"
        let storedChunk = defaults.double(forKey: Keys.chunkDuration)
        chunkDuration = storedChunk > 0 ? storedChunk : 6.0
        excludeAppAudio = defaults.object(forKey: Keys.excludeAppAudio) as? Bool ?? true
        selectedSourceID = defaults.string(forKey: Keys.selectedSourceID) ?? "system-audio"
        selectedDeviceName = defaults.string(forKey: Keys.selectedDeviceName) ?? ""
        speakSourceLanguage = defaults.string(forKey: Keys.speakSourceLanguage) ?? "en"
        speakTargetLanguage = defaults.string(forKey: Keys.speakTargetLanguage) ?? "ar"
        speakMicName = defaults.string(forKey: Keys.speakMicName) ?? ""
        speakOutputDeviceName = defaults.string(forKey: Keys.speakOutputDeviceName) ?? ""
        speakVoiceID = defaults.string(forKey: Keys.speakVoiceID) ?? ""
        monitorSpokenAudio = defaults.object(forKey: Keys.monitorSpokenAudio) as? Bool ?? false
        // 0 is a valid value (gate off), so only fall back to the
        // default when the key has never been written.
        micNoiseGate = defaults.object(forKey: Keys.micNoiseGate) as? Double ?? 0.002
        lastMode = defaults.string(forKey: Keys.lastMode) ?? "listen"
    }

    // MARK: - Transcript folder (security-scoped bookmark)

    /// User-chosen transcript folder, restored via security-scoped bookmark.
    /// Falls back to the app container's Documents/Transcripts.
    var transcriptFolder: URL {
        if let data = defaults.data(forKey: Keys.transcriptFolderBookmark) {
            var isStale = false
            if let url = try? URL(
                resolvingBookmarkData: data,
                options: [.withSecurityScope],
                relativeTo: nil,
                bookmarkDataIsStale: &isStale
            ), !isStale {
                return url
            }
        }
        return Self.defaultTranscriptFolder
    }

    var usesCustomTranscriptFolder: Bool {
        defaults.data(forKey: Keys.transcriptFolderBookmark) != nil
    }

    func setTranscriptFolder(_ url: URL) {
        if let data = try? url.bookmarkData(
            options: [.withSecurityScope],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        ) {
            defaults.set(data, forKey: Keys.transcriptFolderBookmark)
            objectWillChange.send()
        }
    }

    func resetTranscriptFolder() {
        defaults.removeObject(forKey: Keys.transcriptFolderBookmark)
        objectWillChange.send()
    }

    static var defaultTranscriptFolder: URL {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return documents.appendingPathComponent("Transcripts", isDirectory: true)
    }
}
