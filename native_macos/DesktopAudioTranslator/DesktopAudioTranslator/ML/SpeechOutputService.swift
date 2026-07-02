//
//  SpeechOutputService.swift
//  DesktopAudioTranslator
//
//  Speak Mode output: synthesizes translated text with
//  AVSpeechSynthesizer and plays the PCM buffers through an
//  AVAudioEngine bound to a specific Core Audio *output* device —
//  typically BlackHole 2ch, which Slack/Zoom/Meet then select as
//  their microphone.
//
//  Optionally mirrors the speech to the default output device so the
//  user can hear what participants hear.
//

import Foundation
import AVFoundation
import AudioToolbox
import CoreAudio

@MainActor
final class SpeechOutputService: NSObject {

    private let synthesizer = AVSpeechSynthesizer()
    private let hub = SpeechOutputHub()
    private(set) var isActive = false

    /// Start routing. Pass nil `outputDeviceID` to use the default output.
    /// - Parameters:
    ///   - outputDeviceID: target device (BlackHole for conferencing).
    ///   - monitorOnDefaultDevice: also play through the default output.
    func start(outputDeviceID: AudioDeviceID?, monitorOnDefaultDevice: Bool) throws {
        stop()
        var outputs: [DeviceOutput] = []
        let primary = DeviceOutput()
        if let outputDeviceID {
            try primary.bind(deviceID: outputDeviceID)
        }
        outputs.append(primary)
        if monitorOnDefaultDevice && outputDeviceID != nil {
            outputs.append(DeviceOutput()) // default device
        }
        hub.set(outputs)
        isActive = true
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        hub.clear()
        isActive = false
    }

    /// Queue one utterance. Utterances are synthesized and played in
    /// order; buffers stream to all bound outputs as they're produced.
    func speak(_ text: String, languageCode: String, voiceIdentifier: String?) {
        guard isActive, !text.isEmpty else { return }
        let utterance = AVSpeechUtterance(string: text)
        if let voiceIdentifier,
           !voiceIdentifier.isEmpty,
           let voice = AVSpeechSynthesisVoice(identifier: voiceIdentifier) {
            utterance.voice = voice
        } else {
            utterance.voice = AVSpeechSynthesisVoice(language: languageCode)
        }
        let hub = self.hub
        synthesizer.write(utterance) { buffer in
            guard let pcmBuffer = buffer as? AVAudioPCMBuffer,
                  pcmBuffer.frameLength > 0 else { return }
            hub.schedule(pcmBuffer)
        }
    }

    /// Voices installed for a language (for the Settings picker).
    static func voices(forLanguageCode code: String) -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.lowercased().hasPrefix(code.lowercased()) }
            .sorted { $0.name < $1.name }
    }
}

// MARK: - Output plumbing (thread-safe: synthesizer buffer callbacks
// may arrive off the main thread)

nonisolated private final class SpeechOutputHub: @unchecked Sendable {
    private let lock = NSLock()
    private var outputs: [DeviceOutput] = []

    func set(_ newOutputs: [DeviceOutput]) {
        lock.lock()
        let old = outputs
        outputs = newOutputs
        lock.unlock()
        old.forEach { $0.shutdown() }
    }

    func clear() { set([]) }

    func schedule(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        let targets = outputs
        lock.unlock()
        for target in targets {
            target.schedule(buffer)
        }
    }
}

/// One AVAudioEngine + player bound to a specific output device.
/// The player is connected lazily using the first buffer's format;
/// the engine's mixer handles any rate/channel conversion.
///
/// IMPORTANT: the device binding is (re)applied every time the engine
/// starts, not just once up front. Bluetooth headsets activating their
/// mic (HFP) trigger a route reconfiguration that resets the output
/// unit's device — binding at start-of-engine keeps TTS going to the
/// chosen device (e.g. BlackHole) instead of falling back to the
/// default output (your headphones).
nonisolated private final class DeviceOutput: @unchecked Sendable {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let lock = NSLock()
    private var connectedFormat: AVAudioFormat?
    private var boundDeviceID: AudioDeviceID?

    init() {
        engine.attach(player)
    }

    /// Remember the target device; validated on first apply.
    func bind(deviceID: AudioDeviceID) throws {
        lock.lock()
        boundDeviceID = deviceID
        lock.unlock()
        // Fail fast at start if the device can't be set at all.
        try applyDeviceBinding(required: true)
    }

    /// Set kAudioOutputUnitProperty_CurrentDevice on the output unit.
    /// Called before every engine start so route changes can't undo it.
    @discardableResult
    private func applyDeviceBinding(required: Bool = false) throws -> Bool {
        guard let deviceID = boundDeviceID else { return true }
        guard let audioUnit = engine.outputNode.audioUnit else {
            if required {
                throw CaptureError.engineStartFailed("Speech output engine has no audio unit.")
            }
            return false
        }
        var device = deviceID
        let status = AudioUnitSetProperty(
            audioUnit,
            kAudioOutputUnitProperty_CurrentDevice,
            kAudioUnitScope_Global,
            0,
            &device,
            UInt32(MemoryLayout<AudioDeviceID>.size))
        if status != noErr, required {
            throw CaptureError.engineStartFailed("Could not bind the speech output device.")
        }
        return status == noErr
    }

    func schedule(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        defer { lock.unlock() }
        if connectedFormat != buffer.format {
            player.stop()
            engine.stop()
            engine.connect(player, to: engine.mainMixerNode, format: buffer.format)
            connectedFormat = buffer.format
        }
        if !engine.isRunning {
            // Re-apply the device binding on every (re)start — engine
            // reconfigurations and Bluetooth route changes reset it.
            _ = try? applyDeviceBinding()
            engine.prepare()
            guard (try? engine.start()) != nil else { return }
            // Some route transitions only accept the binding once the
            // unit is initialized; apply again and restart if needed.
            if (try? applyDeviceBinding()) == false {
                engine.stop()
                _ = try? applyDeviceBinding()
                engine.prepare()
                guard (try? engine.start()) != nil else { return }
            }
        }
        player.scheduleBuffer(buffer, completionHandler: nil)
        if !player.isPlaying {
            player.play()
        }
    }

    func shutdown() {
        lock.lock()
        defer { lock.unlock() }
        player.stop()
        engine.stop()
        connectedFormat = nil
    }
}
