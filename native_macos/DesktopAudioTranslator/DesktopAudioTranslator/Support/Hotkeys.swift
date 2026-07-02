//
//  Hotkeys.swift
//  DesktopAudioTranslator
//
//  System-wide configurable hotkeys (via the KeyboardShortcuts
//  package — Carbon hotkeys, no Accessibility permission needed).
//
//  Defaults:
//    ⌃⌥T  toggle listen ↔ speak (starts automatically from idle)
//    ⌃⌥L  start listening (saved source)
//    ⌃⌥S  start speaking (saved mic → virtual output)
//    ⌃⌥X  stop (saves the transcript)
//
//  All are re-recordable in Settings → Hotkeys.
//

import Foundation
import AppKit
import Combine
import KeyboardShortcuts

extension KeyboardShortcuts.Name {
    static let toggleListenSpeak = Self("toggleListenSpeak", default: .init(.t, modifiers: [.control, .option]))
    static let startListening = Self("startListening", default: .init(.l, modifiers: [.control, .option]))
    static let startSpeaking = Self("startSpeaking", default: .init(.s, modifiers: [.control, .option]))
    static let stopCapture = Self("stopCapture", default: .init(.x, modifiers: [.control, .option]))
}

@MainActor
final class HotkeyManager: ObservableObject {

    private let pipeline: TranslatorPipeline

    init(pipeline: TranslatorPipeline) {
        self.pipeline = pipeline

        KeyboardShortcuts.onKeyUp(for: .toggleListenSpeak) { [weak pipeline] in
            Task { @MainActor in await pipeline?.toggleListenSpeak() }
        }
        KeyboardShortcuts.onKeyUp(for: .startListening) { [weak pipeline] in
            Task { @MainActor in await pipeline?.startListeningWithSavedSource() }
        }
        KeyboardShortcuts.onKeyUp(for: .startSpeaking) { [weak pipeline] in
            Task { @MainActor in await pipeline?.startSpeakingWithSavedDevices() }
        }
        KeyboardShortcuts.onKeyUp(for: .stopCapture) { [weak pipeline] in
            Task { @MainActor in await pipeline?.stop(save: true) }
        }
    }
}
