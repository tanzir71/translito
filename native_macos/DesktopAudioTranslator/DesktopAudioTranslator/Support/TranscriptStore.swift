//
//  TranscriptStore.swift
//  DesktopAudioTranslator
//
//  Human-readable transcript persistence, matching the Python app's
//  transcripts/transcript_<timestamp>.txt format.
//

import Foundation

struct TranscriptEntry: Identifiable, Hashable {
    let id = UUID()
    let timestamp: Date
    let sourceText: String
    /// Filled in asynchronously once the translation session responds.
    var translatedText: String
    let sourceInfo: String
}

enum TranscriptStore {

    /// Write entries to `folder` as transcript_yyyyMMdd_HHmmss.txt.
    /// Handles security-scoped access for user-selected folders.
    @discardableResult
    static func save(
        entries: [TranscriptEntry],
        to folder: URL,
        sessionStart: Date,
        sourceLanguage: String,
        targetLanguage: String,
        requiresSecurityScope: Bool
    ) throws -> URL {
        guard !entries.isEmpty else {
            throw TranscriptStoreError.nothingToSave
        }

        var didStartAccess = false
        if requiresSecurityScope {
            didStartAccess = folder.startAccessingSecurityScopedResource()
        }
        defer {
            if didStartAccess { folder.stopAccessingSecurityScopedResource() }
        }

        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)

        let fileStamp = Self.fileNameFormatter.string(from: sessionStart)
        let fileURL = folder.appendingPathComponent("transcript_\(fileStamp).txt")

        var lines: [String] = []
        lines.append("=" * 60)
        lines.append("Translito — Transcript")
        lines.append("Session Start: \(Self.headerFormatter.string(from: sessionStart))")
        lines.append("Saved: \(Self.headerFormatter.string(from: Date()))")
        lines.append("Languages: \(Languages.name(for: sourceLanguage)) → \(Languages.name(for: targetLanguage))")
        lines.append("Total Entries: \(entries.count)")
        lines.append("=" * 60)
        lines.append("")

        for (index, entry) in entries.enumerated() {
            lines.append("[\(index + 1)] \(Self.entryFormatter.string(from: entry.timestamp))  (\(entry.sourceInfo))")
            lines.append("Source:      \(entry.sourceText)")
            lines.append("Translation: \(entry.translatedText)")
            lines.append("")
        }

        try lines.joined(separator: "\n").write(to: fileURL, atomically: true, encoding: .utf8)
        return fileURL
    }

    // MARK: - Formatters

    private static let fileNameFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()

    private static let headerFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()

    private static let entryFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()
}

nonisolated enum TranscriptStoreError: LocalizedError {
    case nothingToSave

    var errorDescription: String? {
        switch self {
        case .nothingToSave: return "There are no transcript entries to save."
        }
    }
}

// Small convenience for header rules.
private func * (lhs: String, rhs: Int) -> String {
    String(repeating: lhs, count: rhs)
}
