//
//  TranslatorPipeline.swift
//  DesktopAudioTranslator
//
//  Orchestrates: capture backend → chunk processor → Whisper ASR →
//  Apple Translation → transcript store / UI.
//
//  Capture callbacks never run ASR/translation directly — chunks are
//  pushed through an AsyncStream and consumed by a sequential
//  processing task, preserving chunk order.
//

import Foundation
import Combine
import SwiftUI

@MainActor
final class TranslatorPipeline: ObservableObject {

    enum Mode: String {
        case listen // capture system/mic audio → show translated transcript
        case speak  // you speak → app speaks translation into virtual mic
    }

    enum Status: Equatable {
        case ready
        case loadingModels
        case listening
        case transcribing
        case translating
        case speaking
        case noAudio
        case permissionNeeded(String)
        case error(String)

        var label: String {
            switch self {
            case .ready: return "Ready"
            case .loadingModels: return "Loading models…"
            case .listening: return "Listening"
            case .transcribing: return "Transcribing…"
            case .translating: return "Translating…"
            case .speaking: return "Speaking…"
            case .noAudio: return "No audio detected"
            case .permissionNeeded: return "Permission needed"
            case .error: return "Error"
            }
        }

        var detail: String? {
            switch self {
            case .permissionNeeded(let message), .error(let message): return message
            default: return nil
            }
        }
    }

    // MARK: - Published state

    @Published private(set) var status: Status = .ready
    @Published private(set) var isRunning = false
    @Published private(set) var mode: Mode = .listen
    @Published private(set) var entries: [TranscriptEntry] = []
    @Published private(set) var lastPeak: Float = 0
    @Published private(set) var lastRMS: Float = 0
    @Published var hint: String?
    @Published private(set) var lastSavedURL: URL?
    /// Model download progress (0...1) while status == .loadingModels;
    /// nil during non-download phases (optimizing/loading).
    @Published private(set) var modelProgress: Double?
    /// Human-readable description of the current loading phase.
    @Published private(set) var loadingPhase: String?

    // MARK: - Dependencies

    let settings: AppSettings
    let translationBridge: TranslationBridge

    private let engine = TranscriptionEngine()
    private let processor = AudioChunkProcessor()
    private let speechOutput = SpeechOutputService()
    private var systemCapture: SystemAudioCapture?
    private var inputCapture: InputDeviceCapture?
    private var processingTask: Task<Void, Never>?
    private var chunkContinuation: AsyncStream<AudioChunk>.Continuation?
    private var sessionStart = Date()
    private var activeSource: CaptureSource?

    init(settings: AppSettings, translationBridge: TranslationBridge) {
        self.settings = settings
        self.translationBridge = translationBridge
    }

    // MARK: - Start / Stop

    func start(source: CaptureSource) async {
        guard !isRunning else { return }
        mode = .listen
        hint = nil
        lastPeak = 0
        lastRMS = 0

        // 1. Permissions.
        switch source {
        case .systemAudio:
            if !PermissionsManager.hasScreenRecordingPermission {
                PermissionsManager.requestScreenRecordingPermission()
                status = .permissionNeeded(CaptureError.screenRecordingPermissionDenied.localizedDescription)
                return
            }
        case .inputDevice:
            let granted = await PermissionsManager.requestMicrophonePermission()
            if !granted {
                status = .permissionNeeded(CaptureError.microphonePermissionDenied.localizedDescription)
                return
            }
        }

        // 2. Models.
        do {
            try await loadModels()
        } catch {
            status = .error("Failed to load Whisper model: \(error.localizedDescription)")
            return
        }
        translationBridge.setLanguagePair(
            sourceCode: settings.sourceLanguage == "auto" ? nil : settings.sourceLanguage,
            targetCode: settings.targetLanguage
        )

        // 3. Chunk stream: capture thread → sequential processing task.
        let (stream, continuation) = AsyncStream.makeStream(
            of: AudioChunk.self,
            bufferingPolicy: .bufferingNewest(16)
        )
        chunkContinuation = continuation
        // Microphones get an ambient-noise gate so room noise isn't
        // transcribed; system audio and virtual devices carry real
        // content at any level, so the gate stays off for them.
        let micGate: Float = {
            if case .inputDevice(let device) = source, !device.isVirtual {
                return Float(settings.micNoiseGate)
            }
            return 0
        }()
        processor.prepare(
            inputSampleRate: 48_000,
            chunkDuration: settings.chunkDuration,
            sourceName: source.displayName,
            noiseGateRMS: micGate
        )
        processor.onChunk = { chunk in
            continuation.yield(chunk)
        }
        let isVirtual: Bool = {
            if case .inputDevice(let device) = source { return device.isVirtual }
            return false
        }()
        let sourceName = source.displayName
        processor.onSilenceRun = { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.isRunning else { return }
                self.status = .noAudio
                self.hint = isVirtual
                    ? "No audio from \(sourceName). Make sure macOS sound output is routed to it (e.g. a Multi-Output Device that includes BlackHole), then play some audio. Select BlackHole 2ch as the app input — not the Multi-Output Device."
                    : "No audio detected from \(sourceName). Check that audio is actually playing and levels are up."
            }
        }

        // 4. Start capture backend.
        do {
            switch source {
            case .systemAudio:
                let capture = SystemAudioCapture(processor: processor)
                capture.onStreamError = { [weak self] error in
                    Task { @MainActor [weak self] in
                        guard let self, self.isRunning else { return }
                        self.status = .error("System audio stream stopped: \(error.localizedDescription)")
                        await self.stop(save: true)
                    }
                }
                try await capture.start(excludeCurrentProcess: settings.excludeAppAudio)
                systemCapture = capture
            case .inputDevice(let device):
                let capture = InputDeviceCapture(processor: processor)
                capture.onCaptureError = { [weak self] error in
                    Task { @MainActor [weak self] in
                        guard let self, self.isRunning else { return }
                        self.status = .error(error.localizedDescription)
                        await self.stop(save: true)
                    }
                }
                try capture.start(device: device)
                inputCapture = capture
                settings.selectedDeviceName = device.name
            }
        } catch {
            status = .error(error.localizedDescription)
            chunkContinuation?.finish()
            chunkContinuation = nil
            return
        }

        // 5. Sequential ASR → translation loop.
        activeSource = source
        settings.selectedSourceID = source.id
        settings.lastMode = "listen"
        sessionStart = Date()
        isRunning = true
        status = .listening

        processingTask = Task { [weak self] in
            guard let self else { return }
            for await chunk in stream {
                if Task.isCancelled { break }
                await self.process(chunk)
            }
        }
    }

    /// Start Speak Mode: you talk into `micDevice`, the app speaks the
    /// translation into `outputDevice` (e.g. BlackHole 2ch), which
    /// Slack/Zoom then use as their microphone.
    func startSpeakMode(micDevice: AudioInputDevice, outputDevice: AudioOutputDevice?) async {
        guard !isRunning else { return }
        mode = .speak
        hint = nil
        lastPeak = 0
        lastRMS = 0

        // 1. Microphone permission.
        let granted = await PermissionsManager.requestMicrophonePermission()
        guard granted else {
            status = .permissionNeeded(CaptureError.microphonePermissionDenied.localizedDescription)
            return
        }

        // 2. Models and language pair.
        do {
            try await loadModels()
        } catch {
            status = .error("Failed to load Whisper model: \(error.localizedDescription)")
            return
        }
        translationBridge.setLanguagePair(
            sourceCode: settings.speakSourceLanguage == "auto" ? nil : settings.speakSourceLanguage,
            targetCode: settings.speakTargetLanguage
        )

        // 3. Speech output routing.
        do {
            try speechOutput.start(
                outputDeviceID: outputDevice?.id,
                monitorOnDefaultDevice: settings.monitorSpokenAudio
            )
        } catch {
            status = .error(error.localizedDescription)
            return
        }

        // 4. Chunk stream and mic capture.
        let (stream, continuation) = AsyncStream.makeStream(
            of: AudioChunk.self,
            bufferingPolicy: .bufferingNewest(16)
        )
        chunkContinuation = continuation
        let sourceName = "Speak Mode – \(micDevice.name)"
        processor.prepare(
            inputSampleRate: 48_000,
            chunkDuration: settings.chunkDuration,
            sourceName: sourceName,
            noiseGateRMS: micDevice.isVirtual ? 0 : Float(settings.micNoiseGate)
        )
        processor.onChunk = { chunk in
            continuation.yield(chunk)
        }
        processor.onSilenceRun = { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.isRunning else { return }
                self.status = .noAudio
                self.hint = "No speech detected from \(micDevice.name). Check the mic and input levels."
            }
        }

        do {
            let capture = InputDeviceCapture(processor: processor)
            capture.onCaptureError = { [weak self] error in
                Task { @MainActor [weak self] in
                    guard let self, self.isRunning else { return }
                    self.status = .error(error.localizedDescription)
                    await self.stop(save: true)
                }
            }
            try capture.start(device: micDevice)
            inputCapture = capture
            settings.speakMicName = micDevice.name
            if let outputDevice {
                settings.speakOutputDeviceName = outputDevice.name
            }
        } catch {
            status = .error(error.localizedDescription)
            speechOutput.stop()
            chunkContinuation?.finish()
            chunkContinuation = nil
            return
        }

        // 5. Sequential ASR → translation → speech loop.
        activeSource = .inputDevice(micDevice)
        settings.lastMode = "speak"
        sessionStart = Date()
        isRunning = true
        status = .listening

        processingTask = Task { [weak self] in
            guard let self else { return }
            for await chunk in stream {
                if Task.isCancelled { break }
                await self.process(chunk)
            }
        }
    }

    func stop(save: Bool = true) async {
        guard isRunning else { return }
        isRunning = false

        await systemCapture?.stop()
        systemCapture = nil
        inputCapture?.stop()
        inputCapture = nil
        speechOutput.stop()

        chunkContinuation?.finish()
        chunkContinuation = nil
        processingTask?.cancel()
        processingTask = nil
        translationBridge.cancelPending()
        activeSource = nil

        if save {
            saveTranscript(showErrors: false)
        }
        // Preserve a visible error/permission status set just before stop.
        switch status {
        case .error, .permissionNeeded:
            break
        default:
            status = .ready
        }
    }

    // MARK: - Hotkey / menu-bar entry points (use saved selections)

    /// Resolve the last-used listen source (config.ini equivalent).
    func savedListenSource() -> CaptureSource {
        if settings.selectedSourceID != "system-audio",
           !settings.selectedDeviceName.isEmpty,
           let device = AudioDeviceManager.device(named: settings.selectedDeviceName) {
            return .inputDevice(device)
        }
        return .systemAudio
    }

    /// Resolve the saved Speak Mode devices (mic + virtual output).
    func savedSpeakDevices() -> (mic: AudioInputDevice?, output: AudioOutputDevice?) {
        let inputs = AudioDeviceManager.inputDevices()
        let mic = inputs.first { $0.name == settings.speakMicName }
            ?? inputs.first { !$0.isVirtual }
            ?? inputs.first
        let output = AudioDeviceManager.outputDevice(named: settings.speakOutputDeviceName)
            ?? AudioDeviceManager.outputDevices().first { $0.isVirtual }
        return (mic, output)
    }

    /// Start (or switch to) listen mode using the saved source.
    func startListeningWithSavedSource() async {
        if isRunning {
            guard mode != .listen else { return }
            await stop(save: true)
        }
        await start(source: savedListenSource())
    }

    /// Start (or switch to) speak mode using the saved devices.
    func startSpeakingWithSavedDevices() async {
        if isRunning {
            guard mode != .speak else { return }
            await stop(save: true)
        }
        let devices = savedSpeakDevices()
        guard let mic = devices.mic else {
            status = .error("No microphone available for Speak Mode.")
            return
        }
        await startSpeakMode(micDevice: mic, outputDevice: devices.output)
    }

    /// Hotkey behavior: idle → start the last-used mode; running →
    /// switch to the other mode. Always auto-starts.
    func toggleListenSpeak() async {
        if isRunning {
            if mode == .listen {
                await startSpeakingWithSavedDevices()
            } else {
                await startListeningWithSavedSource()
            }
        } else if settings.lastMode == "speak" {
            await startSpeakingWithSavedDevices()
        } else {
            await startListeningWithSavedSource()
        }
    }

    /// Load models with UI progress. Safe to call repeatedly — returns
    /// immediately if the configured model is already loaded.
    private func loadModels() async throws {
        status = .loadingModels
        let model = settings.whisperModel
        loadingPhase = "Preparing \(model) model…"
        defer {
            modelProgress = nil
            loadingPhase = nil
        }
        try await engine.load(model: model) { [weak self] phase in
            Task { @MainActor [weak self] in
                guard let self, self.status == .loadingModels else { return }
                switch phase {
                case .downloading(let fraction):
                    self.modelProgress = fraction
                    self.loadingPhase = "Downloading Whisper \(model) model — \(Int(fraction * 100))%"
                case .optimizing:
                    self.modelProgress = nil
                    self.loadingPhase = "Optimizing model for this Mac — first run can take a few minutes, cached afterwards"
                }
            }
        }
    }

    /// Warm the models in the background (called at launch) so pressing
    /// Start is instant instead of waiting for download/compile.
    func preloadModels() async {
        guard !isRunning else { return }
        do {
            try await loadModels()
            if !isRunning { status = .ready }
        } catch {
            // Preloading is opportunistic (e.g. may fail offline before
            // first download); Start will retry and surface errors.
            if !isRunning { status = .ready }
        }
    }

    func toggle(source: CaptureSource) async {
        if isRunning {
            await stop(save: true)
        } else {
            await start(source: source)
        }
    }

    // MARK: - Transcript management

    func saveTranscript(showErrors: Bool = true) {
        guard !entries.isEmpty else { return }
        do {
            let url = try TranscriptStore.save(
                entries: entries,
                to: settings.transcriptFolder,
                sessionStart: sessionStart,
                sourceLanguage: settings.sourceLanguage,
                targetLanguage: settings.targetLanguage,
                requiresSecurityScope: settings.usesCustomTranscriptFolder
            )
            lastSavedURL = url
        } catch {
            if showErrors {
                status = .error("Could not save transcript: \(error.localizedDescription)")
            }
        }
    }

    func clearTranscript() {
        entries.removeAll()
        lastSavedURL = nil
    }

    // MARK: - Chunk processing

    private func process(_ chunk: AudioChunk) async {
        lastPeak = chunk.peak
        lastRMS = chunk.rms
        if hint != nil { hint = nil }

        status = .transcribing
        let configuredSource = mode == .speak ? settings.speakSourceLanguage : settings.sourceLanguage
        let languageCode = configuredSource == "auto" ? nil : configuredSource
        let sourceText: String
        do {
            sourceText = try await engine.transcribe(chunk.samples, languageCode: languageCode)
        } catch {
            if isRunning { status = .listening }
            return
        }
        guard !sourceText.isEmpty else {
            if isRunning { status = .listening }
            return
        }

        if mode == .speak {
            await processSpeak(sourceText: sourceText, chunk: chunk)
            return
        }

        status = .translating
        // Append the source text immediately; fill the translation in
        // asynchronously so a slow/unavailable translation session can
        // never stall the ASR loop or drop chunks.
        let entry = TranscriptEntry(
            timestamp: chunk.timestamp,
            sourceText: sourceText,
            translatedText: "",
            sourceInfo: chunk.sourceName
        )
        entries.append(entry)
        let entryID = entry.id
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let translated = try await self.translationBridge.translate(sourceText)
                if let index = self.entries.firstIndex(where: { $0.id == entryID }) {
                    self.entries[index].translatedText = translated
                }
            } catch {
                // Keep the source text even if translation fails (e.g.
                // language pack not downloaded yet); surface a hint once.
                if self.isRunning && self.hint == nil {
                    self.hint = "Translation unavailable: \(error.localizedDescription)"
                }
            }
        }

        if isRunning { status = .listening }
    }

    /// Speak Mode: translation must complete before we can speak it, so
    /// this path awaits the translation inline (unlike listen mode).
    private func processSpeak(sourceText: String, chunk: AudioChunk) async {
        status = .translating
        var translatedText = ""
        do {
            translatedText = try await translationBridge.translate(sourceText)
        } catch {
            if isRunning && hint == nil {
                hint = "Translation unavailable: \(error.localizedDescription). Keep the main window open — it hosts the translation session."
            }
        }

        entries.append(TranscriptEntry(
            timestamp: chunk.timestamp,
            sourceText: sourceText,
            translatedText: translatedText,
            sourceInfo: chunk.sourceName
        ))

        if !translatedText.isEmpty {
            status = .speaking
            speechOutput.speak(
                translatedText,
                languageCode: settings.speakTargetLanguage,
                voiceIdentifier: settings.speakVoiceID
            )
        }
        if isRunning { status = .listening }
    }
}
