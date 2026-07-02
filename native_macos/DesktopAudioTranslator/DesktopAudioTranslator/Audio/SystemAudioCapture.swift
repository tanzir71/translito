//
//  SystemAudioCapture.swift
//  DesktopAudioTranslator
//
//  Native system/desktop audio capture using ScreenCaptureKit.
//  This is the macOS replacement for the Windows `soundcard` loopback
//  path — no BlackHole required.
//
//  Requires Screen Recording permission. Video frames are configured
//  to the minimum and never consumed; only the .audio output is used.
//

import Foundation
import ScreenCaptureKit
import CoreMedia
import Accelerate

@MainActor
final class SystemAudioCapture: NSObject {

    let processor: AudioChunkProcessor
    private var stream: SCStream?
    private let sampleQueue = DispatchQueue(label: "SystemAudioCapture.samples", qos: .userInitiated)

    /// Reported when the stream stops unexpectedly (e.g. permission revoked).
    var onStreamError: (@Sendable (Error) -> Void)?

    init(processor: AudioChunkProcessor) {
        self.processor = processor
    }

    /// Start capturing system audio.
    /// - Parameter excludeCurrentProcess: don't capture this app's own audio.
    func start(excludeCurrentProcess: Bool) async throws {
        guard stream == nil else { return }

        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: false)
        guard let display = content.displays.first else {
            throw CaptureError.noDisplayFound
        }

        let filter = SCContentFilter(
            display: display,
            excludingApplications: [],
            exceptingWindows: [])

        let configuration = SCStreamConfiguration()
        configuration.capturesAudio = true
        configuration.excludesCurrentProcessAudio = excludeCurrentProcess
        configuration.sampleRate = 48_000
        configuration.channelCount = 2
        // Minimize the (unused) video leg of the stream.
        configuration.width = 2
        configuration.height = 2
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        configuration.showsCursor = false

        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: sampleQueue)
        try await stream.startCapture()
        self.stream = stream
    }

    func stop() async {
        guard let stream else { return }
        self.stream = nil
        try? await stream.stopCapture()
        processor.flush()
    }
}

// MARK: - SCStreamOutput / SCStreamDelegate

extension SystemAudioCapture: SCStreamOutput, SCStreamDelegate {

    nonisolated func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .audio,
              sampleBuffer.isValid,
              CMSampleBufferGetNumSamples(sampleBuffer) > 0,
              let formatDescription = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(formatDescription)?.pointee
        else { return }

        let frameCount = CMSampleBufferGetNumSamples(sampleBuffer)
        let channelCount = max(1, Int(asbd.mChannelsPerFrame))
        let sampleRate = asbd.mSampleRate
        let isFloat = (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0
        let isInterleaved = (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) == 0
        guard isFloat, asbd.mBitsPerChannel == 32 else { return }

        // Extract the audio buffer list, keeping the backing block buffer alive.
        var blockBuffer: CMBlockBuffer?
        let audioBufferList = AudioBufferList.allocate(maximumBuffers: channelCount)
        defer { free(audioBufferList.unsafeMutablePointer) }

        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: audioBufferList.unsafeMutablePointer,
            bufferListSize: AudioBufferList.sizeInBytes(maximumBuffers: channelCount),
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: &blockBuffer)
        guard status == noErr else { return }

        // Downmix to mono.
        var mono = [Float](repeating: 0, count: frameCount)

        if isInterleaved {
            guard let data = audioBufferList[0].mData else { return }
            let interleavedSamples = data.assumingMemoryBound(to: Float.self)
            let available = Int(audioBufferList[0].mDataByteSize) / MemoryLayout<Float>.size
            let frames = min(frameCount, available / channelCount)
            if channelCount == 1 {
                mono = Array(UnsafeBufferPointer(start: interleavedSamples, count: frames))
            } else {
                for frame in 0..<frames {
                    var sum: Float = 0
                    for channel in 0..<channelCount {
                        sum += interleavedSamples[frame * channelCount + channel]
                    }
                    mono[frame] = sum / Float(channelCount)
                }
            }
        } else {
            var mixedChannels = 0
            mono.withUnsafeMutableBufferPointer { monoPointer in
                for buffer in audioBufferList {
                    guard let data = buffer.mData else { continue }
                    let channelSamples = data.assumingMemoryBound(to: Float.self)
                    let frames = min(frameCount, Int(buffer.mDataByteSize) / MemoryLayout<Float>.size)
                    vDSP_vadd(monoPointer.baseAddress!, 1, channelSamples, 1,
                              monoPointer.baseAddress!, 1, vDSP_Length(frames))
                    mixedChannels += 1
                }
                if mixedChannels > 1 {
                    var scale = 1.0 / Float(mixedChannels)
                    vDSP_vsmul(monoPointer.baseAddress!, 1, &scale,
                               monoPointer.baseAddress!, 1, vDSP_Length(frameCount))
                }
            }
        }

        mono.withUnsafeBufferPointer {
            processor.ingestMono($0, sampleRate: sampleRate)
        }
        // Keep the block buffer alive through sample extraction.
        _ = blockBuffer
    }

    nonisolated func stream(_ stream: SCStream, didStopWithError error: Error) {
        onStreamErrorHandler(error)
    }

    private nonisolated func onStreamErrorHandler(_ error: Error) {
        // `onStreamError` is set once before capture starts.
        Task { @MainActor [weak self] in
            self?.stream = nil
            self?.onStreamError?(error)
        }
    }
}
