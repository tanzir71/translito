//
//  TranslationBridge.swift
//  DesktopAudioTranslator
//
//  On-device translation via Apple's Translation framework.
//  Replaces the Python app's Helsinki-NLP models.
//
//  The Translation framework only vends a TranslationSession inside a
//  SwiftUI `.translationTask` closure, so this bridge queues requests
//  and re-triggers the task (via configuration.invalidate()) to drain
//  them. ContentView hosts the hidden `.translationTask` and calls
//  `drain(session:)`.
//

import Foundation
import Combine
import Translation

@MainActor
final class TranslationBridge: ObservableObject {

    struct Request {
        let text: String
        let continuation: CheckedContinuation<String, Error>
    }

    nonisolated enum BridgeError: LocalizedError {
        case notConfigured
        case cancelled

        var errorDescription: String? {
            switch self {
            case .notConfigured:
                return "Translation is not configured yet."
            case .cancelled:
                return "Translation was cancelled."
            }
        }
    }

    /// Observed by ContentView's `.translationTask`. Changing it (or calling
    /// `invalidate()` on it) re-runs the task closure with a fresh session.
    @Published private(set) var configuration: TranslationSession.Configuration?

    private var pending: [Request] = []
    private var currentPairKey: String = ""

    /// Configure the language pair. `sourceCode`/`targetCode` are ISO codes
    /// like "ar" and "en". Pass nil source for auto-detection.
    func setLanguagePair(sourceCode: String?, targetCode: String) {
        let key = "\(sourceCode ?? "auto")->\(targetCode)"
        guard key != currentPairKey || configuration == nil else { return }
        currentPairKey = key
        let source = sourceCode.map { Locale.Language(identifier: $0) }
        let target = Locale.Language(identifier: targetCode)
        configuration = TranslationSession.Configuration(source: source, target: target)
    }

    /// Translate one string. Queues the request and pokes the translation
    /// task; resumes when the session has produced a result.
    func translate(_ text: String) async throws -> String {
        guard configuration != nil else { throw BridgeError.notConfigured }
        return try await withCheckedThrowingContinuation { continuation in
            pending.append(Request(text: text, continuation: continuation))
            // Re-run the .translationTask closure to drain the queue.
            configuration?.invalidate()
        }
    }

    /// Called from the `.translationTask` closure with a live session.
    func drain(session: TranslationSession) async {
        if pending.isEmpty {
            // First run after (re)configuration: trigger the language
            // asset download prompt if assets are missing.
            try? await session.prepareTranslation()
            return
        }
        while !pending.isEmpty {
            let request = pending.removeFirst()
            do {
                let response = try await session.translate(request.text)
                request.continuation.resume(returning: response.targetText)
            } catch {
                request.continuation.resume(throwing: error)
            }
        }
    }

    /// Fail any queued requests (e.g. on stop) so callers don't hang.
    func cancelPending() {
        let requests = pending
        pending.removeAll()
        for request in requests {
            request.continuation.resume(throwing: BridgeError.cancelled)
        }
    }
}
