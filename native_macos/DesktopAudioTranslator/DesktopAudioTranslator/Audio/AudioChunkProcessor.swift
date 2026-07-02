//
//  AudioChunkProcessor.swift
//  DesktopAudioTranslator
//
//  Normalizes capture output into the ASR contract shared with the
//  working Windows app:
//
//    Float32 PCM, mono, 16 kHz, 6-second chunks,
//    peak/rms silence detection, gain for quiet chunks.
//
//  Thread-safe: `ingestMono` is called from capture callbacks
//  (ScreenCaptureKit sample queue or the AVAudioEngine render thread).
//  Never block this path with ASR/translation work — chunks are handed
//  off through the `onChunk` callback.
//

import Foundation
@preconcurrency import AVFAudio
import Accelerate

nonisolated final class AudioChunkProcessor: @unchecked Sendable {

    // Silence thresholds and gain rules copied from main.py process_audio().
    private static let silencePeakThreshold: Float = 0.000001
    private static let silenceRMSThreshold: Float = 0.0000005
    private static let quietPeakThreshold: Float = 0.05
    private static let maxGain: Float = 200.0
    private static let silenceRunHintCount = 5

    static let targetSampleRate: Double = 16_000

    // Pause-based early emission: don't always wait the full chunk
    // duration — if the user has spoken and then paused, ship the chunk
    // immediately. Cuts perceived latency dramatically for speech.
    private static let earlyEmitMinSpeechSeconds = 1.5
    private static let earlyEmitTailSeconds = 0.7
    private static let earlyEmitBodyPeakFloor: Float = 0.005
    private static let earlyEmitDropRatio: Float = 2.5

    private let lock = NSLock()
    private var pending: [Float] = []
    private var inputSampleRate: Double = 48_000
    private var chunkDuration: Double = 6.0
    private var sourceName: String = ""
    private var silenceRun = 0
    private var chunkIndex = 0
    /// Chunks whose RMS is below this are dropped as ambient noise.
    /// 0 disables the gate (system audio / virtual devices, where quiet
    /// content is real content). Microphone sources use a non-zero gate
    /// so room noise and distant sounds never reach Whisper.
    private var noiseGateRMS: Float = 0

    /// Called with each normalized chunk. Set before starting capture.
    /// Invoked on the capture thread — hand off immediately.
    var onChunk: (@Sendable (AudioChunk) -> Void)?

    /// Called when several consecutive silent chunks are seen
    /// (matches the Python app's "no audio" hint). Argument is the run length.
    var onSilenceRun: (@Sendable (Int) -> Void)?

    /// Reset internal state for a new capture session.
    /// - Parameter noiseGateRMS: minimum chunk RMS to be considered
    ///   speech; pass 0 to disable (system audio / virtual devices).
    func prepare(
        inputSampleRate: Double,
        chunkDuration: Double,
        sourceName: String,
        noiseGateRMS: Float = 0
    ) {
        lock.lock()
        defer { lock.unlock() }
        pending.removeAll(keepingCapacity: true)
        self.inputSampleRate = inputSampleRate
        self.chunkDuration = max(1.0, chunkDuration)
        self.sourceName = sourceName
        self.noiseGateRMS = noiseGateRMS
        silenceRun = 0
        chunkIndex = 0
    }

    /// Feed mono Float32 samples at the capture-native sample rate.
    /// If the rate changes mid-stream (device/route change), buffered
    /// audio is dropped and accumulation restarts at the new rate.
    func ingestMono(_ samples: UnsafeBufferPointer<Float>, sampleRate: Double) {
        guard samples.count > 0 else { return }
        var completed: [[Float]] = []
        var rateForChunks: Double = 0

        lock.lock()
        if sampleRate != inputSampleRate {
            pending.removeAll(keepingCapacity: true)
            inputSampleRate = sampleRate
        }
        pending.append(contentsOf: samples)
        let chunkFrameCount = Int(inputSampleRate * chunkDuration)
        while chunkFrameCount > 0 && pending.count >= chunkFrameCount {
            completed.append(Array(pending.prefix(chunkFrameCount)))
            pending.removeFirst(chunkFrameCount)
        }
        // Early emit: speech followed by a pause doesn't need to wait
        // for the full chunk window.
        if completed.isEmpty, let early = earlyChunkAfterPause() {
            completed.append(early)
        }
        rateForChunks = inputSampleRate
        lock.unlock()

        for nativeChunk in completed {
            emit(nativeChunk, capturedAt: rateForChunks)
        }
    }

    /// Flush whatever is buffered (used on stop so trailing audio isn't lost).
    func flush() {
        var remainder: [Float] = []
        var rate: Double = 0
        lock.lock()
        // Only bother if there's at least one second of audio.
        if pending.count >= Int(inputSampleRate) {
            remainder = pending
        }
        pending.removeAll(keepingCapacity: false)
        rate = inputSampleRate
        lock.unlock()
        if !remainder.isEmpty {
            emit(remainder, capturedAt: rate)
        }
    }

    /// Must be called with `lock` held. Returns (and consumes) the
    /// pending buffer if it contains speech followed by a quiet tail:
    /// tail RMS well below body RMS, and the body loud enough to be
    /// actual signal (steady ambient noise never triggers this, so it
    /// falls back to the fixed chunk window).
    private func earlyChunkAfterPause() -> [Float]? {
        let minFrames = Int(inputSampleRate * Self.earlyEmitMinSpeechSeconds)
        let tailFrames = Int(inputSampleRate * Self.earlyEmitTailSeconds)
        guard tailFrames > 0, pending.count >= minFrames + tailFrames else { return nil }

        let bodyCount = pending.count - tailFrames
        var bodyPeak: Float = 0
        var bodyRMS: Float = 0
        var tailRMS: Float = 0
        pending.withUnsafeBufferPointer { pointer in
            vDSP_maxmgv(pointer.baseAddress!, 1, &bodyPeak, vDSP_Length(bodyCount))
            vDSP_rmsqv(pointer.baseAddress!, 1, &bodyRMS, vDSP_Length(bodyCount))
            vDSP_rmsqv(pointer.baseAddress! + bodyCount, 1, &tailRMS, vDSP_Length(tailFrames))
        }

        guard bodyPeak > Self.earlyEmitBodyPeakFloor,
              tailRMS > 0 ? (bodyRMS / tailRMS) > Self.earlyEmitDropRatio : bodyRMS > 0
        else { return nil }

        let chunk = pending
        pending.removeAll(keepingCapacity: true)
        return chunk
    }

    // MARK: - Chunk finalization

    private func emit(_ nativeSamples: [Float], capturedAt rate: Double) {
        var samples = resample(nativeSamples, from: rate, to: Self.targetSampleRate)
        guard !samples.isEmpty else { return }

        var peak: Float = 0
        var rms: Float = 0
        vDSP_maxmgv(samples, 1, &peak, vDSP_Length(samples.count))
        vDSP_rmsqv(samples, 1, &rms, vDSP_Length(samples.count))

        // Silence gate (same thresholds as the Python app) plus the
        // ambient-noise gate for microphone sources: room noise, car
        // honks, and distant sounds stay below speech RMS and get
        // dropped before ASR instead of being gain-boosted into
        // hallucinated transcriptions.
        lock.lock()
        let gate = noiseGateRMS
        lock.unlock()
        let isDigitalSilence = peak < Self.silencePeakThreshold && rms < Self.silenceRMSThreshold
        let isBelowNoiseGate = gate > 0 && rms < gate
        if isDigitalSilence || isBelowNoiseGate {
            lock.lock()
            silenceRun += 1
            let run = silenceRun
            lock.unlock()
            if run >= Self.silenceRunHintCount && isDigitalSilence {
                onSilenceRun?(run)
            }
            return
        }

        lock.lock()
        silenceRun = 0
        chunkIndex += 1
        let name = sourceName
        lock.unlock()

        // Boost quiet chunks: gain = min(200, 0.9 / peak).
        if peak > 0 && peak < Self.quietPeakThreshold {
            var gain = min(Self.maxGain, 0.9 / peak)
            let count = samples.count
            samples.withUnsafeMutableBufferPointer { pointer in
                vDSP_vsmul(pointer.baseAddress!, 1, &gain, pointer.baseAddress!, 1, vDSP_Length(count))
            }
            // Recompute levels after gain so the UI shows what ASR sees.
            vDSP_maxmgv(samples, 1, &peak, vDSP_Length(count))
            vDSP_rmsqv(samples, 1, &rms, vDSP_Length(count))
        }

        onChunk?(AudioChunk(
            samples: samples,
            timestamp: Date(),
            peak: peak,
            rms: rms,
            sourceName: name
        ))
    }

    /// High-quality resample via AVAudioConverter (per handoff guidance:
    /// capture native, resample to 16 kHz — never capture desktop audio
    /// at 16 kHz directly).
    private func resample(_ input: [Float], from sourceRate: Double, to targetRate: Double) -> [Float] {
        guard sourceRate != targetRate else { return input }
        guard
            let inputFormat = AVAudioFormat(
                commonFormat: .pcmFormatFloat32, sampleRate: sourceRate, channels: 1, interleaved: false),
            let outputFormat = AVAudioFormat(
                commonFormat: .pcmFormatFloat32, sampleRate: targetRate, channels: 1, interleaved: false),
            let converter = AVAudioConverter(from: inputFormat, to: outputFormat),
            let inputBuffer = AVAudioPCMBuffer(
                pcmFormat: inputFormat, frameCapacity: AVAudioFrameCount(input.count))
        else { return [] }

        input.withUnsafeBufferPointer { source in
            inputBuffer.floatChannelData![0].update(from: source.baseAddress!, count: input.count)
        }
        inputBuffer.frameLength = AVAudioFrameCount(input.count)

        let outputCapacity = AVAudioFrameCount(Double(input.count) * targetRate / sourceRate) + 64
        guard let outputBuffer = AVAudioPCMBuffer(
            pcmFormat: outputFormat, frameCapacity: outputCapacity) else { return [] }

        var fedInput = false
        var conversionError: NSError?
        let status = converter.convert(to: outputBuffer, error: &conversionError) { _, outStatus in
            if fedInput {
                outStatus.pointee = .endOfStream
                return nil
            }
            fedInput = true
            outStatus.pointee = .haveData
            return inputBuffer
        }
        guard status != .error, conversionError == nil, outputBuffer.frameLength > 0 else { return [] }

        return Array(UnsafeBufferPointer(
            start: outputBuffer.floatChannelData![0],
            count: Int(outputBuffer.frameLength)
        ))
    }
}
