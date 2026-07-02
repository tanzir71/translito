//
//  TranscriptionEngine.swift
//  DesktopAudioTranslator
//
//  On-device Whisper ASR via WhisperKit (Core ML, Apple Silicon optimized).
//  Replaces the Python app's Transformers Whisper pipeline.
//
//  Expects the AudioChunkProcessor contract: mono Float32 @ 16 kHz.
//

import Foundation
import WhisperKit

actor TranscriptionEngine {

    /// Whisper model choices, smallest to largest.
    /// Mirrors the Python app's openai/whisper-* options.
    static let availableModels = ["tiny", "base", "small", "medium", "large-v3"]

    /// Loading phases reported to the UI.
    nonisolated enum LoadPhase: Sendable {
        /// Downloading model files; fraction is 0...1.
        case downloading(Double)
        /// Core ML specialization — slow on first run, cached afterwards.
        case optimizing
    }

    private var whisperKit: WhisperKit?
    private var loadedModel: String?

    var isLoaded: Bool { whisperKit != nil }

    /// Load (or switch) the Whisper model. Downloads on first use, then
    /// runs fully offline. Reports progress through `onProgress`.
    func load(model: String, onProgress: (@Sendable (LoadPhase) -> Void)? = nil) async throws {
        if loadedModel == model, whisperKit != nil { return }
        whisperKit = nil
        loadedModel = nil

        // Download (or verify) the model files with progress.
        let modelFolder = try await WhisperKit.download(variant: model) { progress in
            onProgress?(.downloading(progress.fractionCompleted))
        }

        // Compile/load. First run per model triggers Core ML
        // specialization for this machine and can take minutes;
        // afterwards it's cached and fast.
        onProgress?(.optimizing)
        let config = WhisperKitConfig(
            model: model,
            modelFolder: modelFolder.path,
            prewarm: true,
            load: true,
            download: false
        )
        whisperKit = try await WhisperKit(config)
        loadedModel = model
    }

    func unload() {
        whisperKit = nil
        loadedModel = nil
    }

    /// Transcribe one normalized audio chunk.
    /// - Parameters:
    ///   - samples: mono Float32 PCM at 16 kHz.
    ///   - languageCode: ISO 639-1 code ("ar", "en", ...) or nil for auto-detect.
    /// - Returns: trimmed transcription text (may be empty).
    func transcribe(_ samples: [Float], languageCode: String?) async throws -> String {
        guard let whisperKit else {
            throw TranscriptionError.modelNotLoaded
        }
        let options = DecodingOptions(
            task: .transcribe,
            language: languageCode,
            temperature: 0.0,
            usePrefillPrompt: languageCode != nil,
            detectLanguage: languageCode == nil,
            skipSpecialTokens: true,
            withoutTimestamps: true,
            // Suppress hallucinations on noise/non-speech audio (car
            // horns, keyboard clatter): drop windows Whisper itself
            // judges as no-speech or low-confidence.
            compressionRatioThreshold: 2.4,
            logProbThreshold: -1.0,
            noSpeechThreshold: 0.6
        )
        let results = try await whisperKit.transcribe(audioArray: samples, decodeOptions: options)
        let text = results
            .map { $0.text }
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return Self.cleaned(text)
    }

    /// Strip leftover special tokens and skip pure-punctuation output.
    private static func cleaned(_ text: String) -> String {
        var result = text
        // Remove any residual <|...|> tokens.
        while let start = result.range(of: "<|"), let end = result.range(of: "|>", range: start.upperBound..<result.endIndex) {
            result.removeSubrange(start.lowerBound..<end.upperBound)
        }
        result = result.trimmingCharacters(in: .whitespacesAndNewlines)
        let meaningful = result.unicodeScalars.contains {
            CharacterSet.alphanumerics.contains($0)
        }
        return meaningful ? result : ""
    }
}

nonisolated enum TranscriptionError: LocalizedError {
    case modelNotLoaded

    var errorDescription: String? {
        switch self {
        case .modelNotLoaded:
            return "The speech recognition model is not loaded yet."
        }
    }
}
