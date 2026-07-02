//
//  InputDeviceCapture.swift
//  DesktopAudioTranslator
//
//  AVAudioEngine capture for microphones and virtual input devices
//  (BlackHole etc.). This is the fallback/mic path — it captures
//  whatever macOS exposes as an *input* device. It cannot capture
//  speaker output by itself; that's what SystemAudioCapture is for.
//

import Foundation
import AVFAudio
import AudioToolbox
import CoreAudio
import Accelerate

@MainActor
final class InputDeviceCapture {

    let processor: AudioChunkProcessor
    private var engine: AVAudioEngine?
    private var configChangeObserver: NSObjectProtocol?
    private var runningDeviceID: AudioDeviceID?

    /// Reported when the engine stops due to a configuration change it
    /// could not recover from.
    var onCaptureError: (@Sendable (Error) -> Void)?

    init(processor: AudioChunkProcessor) {
        self.processor = processor
    }

    var currentSampleRate: Double {
        engine?.inputNode.inputFormat(forBus: 0).sampleRate ?? 48_000
    }

    func start(device: AudioInputDevice?) throws {
        guard engine == nil else { return }

        let engine = AVAudioEngine()
        let inputNode = engine.inputNode

        // Bind the engine input to the selected Core Audio device.
        if let device, let audioUnit = inputNode.audioUnit {
            var deviceID = device.id
            let status = AudioUnitSetProperty(
                audioUnit,
                kAudioOutputUnitProperty_CurrentDevice,
                kAudioUnitScope_Global,
                0,
                &deviceID,
                UInt32(MemoryLayout<AudioDeviceID>.size))
            guard status == noErr else {
                throw CaptureError.deviceNotFound(device.name)
            }
            runningDeviceID = device.id
        }

        let format = inputNode.inputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw CaptureError.engineStartFailed("Input device reports an invalid format.")
        }

        let processor = self.processor
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
            Self.forward(buffer: buffer, to: processor)
        }

        engine.prepare()
        do {
            try engine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            throw CaptureError.engineStartFailed(error.localizedDescription)
        }
        self.engine = engine

        // Recover from device format/route changes by restarting the tap.
        configChangeObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.handleConfigurationChange()
            }
        }
    }

    func stop() {
        if let observer = configChangeObserver {
            NotificationCenter.default.removeObserver(observer)
            configChangeObserver = nil
        }
        guard let engine else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        self.engine = nil
        runningDeviceID = nil
        processor.flush()
    }

    // MARK: - Private

    private func handleConfigurationChange() {
        guard let engine, !engine.isRunning else { return }
        let inputNode = engine.inputNode
        inputNode.removeTap(onBus: 0)
        let format = inputNode.inputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            onCaptureError?(CaptureError.engineStartFailed(
                "Input device changed and no valid format is available."))
            return
        }
        let processor = self.processor
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
            Self.forward(buffer: buffer, to: processor)
        }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            onCaptureError?(CaptureError.engineStartFailed(error.localizedDescription))
        }
    }

    /// Downmix an input buffer to mono and hand it to the chunk processor.
    /// Runs on the audio render thread — keep it allocation-light and never
    /// call back into the main actor.
    private nonisolated static func forward(buffer: AVAudioPCMBuffer, to processor: AudioChunkProcessor) {
        guard let channelData = buffer.floatChannelData else { return }
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return }
        let channelCount = Int(buffer.format.channelCount)
        let sampleRate = buffer.format.sampleRate

        if channelCount == 1 {
            let samples = UnsafeBufferPointer(start: channelData[0], count: frameCount)
            processor.ingestMono(samples, sampleRate: sampleRate)
        } else {
            var mono = [Float](repeating: 0, count: frameCount)
            mono.withUnsafeMutableBufferPointer { monoPointer in
                for channel in 0..<channelCount {
                    vDSP_vadd(monoPointer.baseAddress!, 1, channelData[channel], 1,
                              monoPointer.baseAddress!, 1, vDSP_Length(frameCount))
                }
                var scale = 1.0 / Float(channelCount)
                vDSP_vsmul(monoPointer.baseAddress!, 1, &scale,
                           monoPointer.baseAddress!, 1, vDSP_Length(frameCount))
            }
            mono.withUnsafeBufferPointer {
                processor.ingestMono($0, sampleRate: sampleRate)
            }
        }
    }
}
