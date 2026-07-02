//
//  AudioDeviceObserver.swift
//  DesktopAudioTranslator
//
//  Posts a notification whenever the set of Core Audio devices changes
//  (headphones plugged in, BlackHole installed, USB mic connected), so
//  the UI can refresh its device pickers without a restart.
//

import Foundation
import CoreAudio

extension Notification.Name {
    static let audioDevicesDidChange = Notification.Name("AudioDevicesDidChange")
}

nonisolated final class AudioDeviceObserver: @unchecked Sendable {

    static let shared = AudioDeviceObserver()

    private var started = false
    private let lock = NSLock()

    private init() {}

    /// Start listening for device-list changes. Safe to call repeatedly.
    func start() {
        lock.lock()
        defer { lock.unlock() }
        guard !started else { return }

        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        let status = AudioObjectAddPropertyListenerBlock(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            DispatchQueue.main
        ) { _, _ in
            NotificationCenter.default.post(name: .audioDevicesDidChange, object: nil)
        }
        started = (status == noErr)
    }
}
