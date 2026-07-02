//
//  AudioTypes.swift
//  DesktopAudioTranslator
//
//  Shared audio types used across capture backends and the pipeline.
//

import Foundation
import CoreAudio

/// A fixed-length chunk of audio, normalized to the ASR contract:
/// Float32 PCM, mono, 16 kHz.
nonisolated struct AudioChunk: Sendable {
    let samples: [Float]
    let timestamp: Date
    let peak: Float
    let rms: Float
    let sourceName: String
}

/// What the user chose to capture.
nonisolated enum CaptureSource: Hashable, Identifiable {
    /// Native system/desktop audio via ScreenCaptureKit.
    case systemAudio
    /// A Core Audio input device (microphone or virtual device like BlackHole).
    case inputDevice(AudioInputDevice)

    var id: String {
        switch self {
        case .systemAudio: return "system-audio"
        case .inputDevice(let device): return "device-\(device.id)"
        }
    }

    var displayName: String {
        switch self {
        case .systemAudio: return "System Audio"
        case .inputDevice(let device):
            return device.isVirtual ? "\(device.name) (virtual)" : device.name
        }
    }
}

/// A Core Audio input device.
nonisolated struct AudioInputDevice: Identifiable, Hashable {
    let id: AudioDeviceID
    let name: String
    let isVirtual: Bool
}

/// A Core Audio output device (used by Speak Mode to route synthesized
/// speech into a virtual device that conferencing apps use as a mic).
nonisolated struct AudioOutputDevice: Identifiable, Hashable {
    let id: AudioDeviceID
    let name: String
    let isVirtual: Bool
}

nonisolated enum CaptureError: LocalizedError {
    case noDisplayFound
    case screenRecordingPermissionDenied
    case microphonePermissionDenied
    case deviceNotFound(String)
    case engineStartFailed(String)

    var errorDescription: String? {
        switch self {
        case .noDisplayFound:
            return "No display found for system audio capture."
        case .screenRecordingPermissionDenied:
            return "Screen Recording permission is required to capture system audio. Enable it in System Settings → Privacy & Security → Screen & System Audio Recording."
        case .microphonePermissionDenied:
            return "Microphone permission is required to capture from input devices. Enable it in System Settings → Privacy & Security → Microphone."
        case .deviceNotFound(let name):
            return "Audio input device \"\(name)\" was not found."
        case .engineStartFailed(let reason):
            return "Audio engine failed to start: \(reason)"
        }
    }
}
