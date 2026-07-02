//
//  Languages.swift
//  DesktopAudioTranslator
//
//  Language choices shared by ASR (Whisper) and translation (Apple
//  Translation framework). Codes are ISO 639-1.
//

import Foundation

struct LanguageOption: Identifiable, Hashable {
    let code: String
    let name: String
    var id: String { code }
}

enum Languages {

    /// Source (spoken) languages for Whisper. "auto" lets Whisper detect.
    static let source: [LanguageOption] = [
        LanguageOption(code: "auto", name: "Auto-detect"),
        LanguageOption(code: "ar", name: "Arabic"),
        LanguageOption(code: "en", name: "English"),
        LanguageOption(code: "zh", name: "Chinese"),
        LanguageOption(code: "nl", name: "Dutch"),
        LanguageOption(code: "fr", name: "French"),
        LanguageOption(code: "de", name: "German"),
        LanguageOption(code: "hi", name: "Hindi"),
        LanguageOption(code: "id", name: "Indonesian"),
        LanguageOption(code: "it", name: "Italian"),
        LanguageOption(code: "ja", name: "Japanese"),
        LanguageOption(code: "ko", name: "Korean"),
        LanguageOption(code: "pl", name: "Polish"),
        LanguageOption(code: "pt", name: "Portuguese"),
        LanguageOption(code: "ru", name: "Russian"),
        LanguageOption(code: "es", name: "Spanish"),
        LanguageOption(code: "th", name: "Thai"),
        LanguageOption(code: "tr", name: "Turkish"),
        LanguageOption(code: "uk", name: "Ukrainian"),
        LanguageOption(code: "vi", name: "Vietnamese"),
    ]

    /// Target languages supported by Apple's Translation framework.
    static let target: [LanguageOption] = [
        LanguageOption(code: "en", name: "English"),
        LanguageOption(code: "ar", name: "Arabic"),
        LanguageOption(code: "zh", name: "Chinese (Simplified)"),
        LanguageOption(code: "nl", name: "Dutch"),
        LanguageOption(code: "fr", name: "French"),
        LanguageOption(code: "de", name: "German"),
        LanguageOption(code: "hi", name: "Hindi"),
        LanguageOption(code: "id", name: "Indonesian"),
        LanguageOption(code: "it", name: "Italian"),
        LanguageOption(code: "ja", name: "Japanese"),
        LanguageOption(code: "ko", name: "Korean"),
        LanguageOption(code: "pl", name: "Polish"),
        LanguageOption(code: "pt", name: "Portuguese"),
        LanguageOption(code: "ru", name: "Russian"),
        LanguageOption(code: "es", name: "Spanish"),
        LanguageOption(code: "th", name: "Thai"),
        LanguageOption(code: "tr", name: "Turkish"),
        LanguageOption(code: "uk", name: "Ukrainian"),
        LanguageOption(code: "vi", name: "Vietnamese"),
    ]

    static func name(for code: String) -> String {
        (source + target).first { $0.code == code }?.name ?? code
    }

    /// Right-to-left scripts get RTL text alignment in the transcript view.
    static func isRightToLeft(_ code: String) -> Bool {
        ["ar", "he", "fa", "ur"].contains(code)
    }
}
