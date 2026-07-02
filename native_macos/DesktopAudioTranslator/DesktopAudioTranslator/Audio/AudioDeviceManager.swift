//
//  AudioDeviceManager.swift
//  DesktopAudioTranslator
//
//  Core Audio input-device enumeration and virtual-device detection.
//  Mirrors the Python app's virtual-device name matching (BlackHole,
//  Soundflower, Loopback, etc.).
//

import Foundation
import CoreAudio

nonisolated enum AudioDeviceManager {

    /// Name fragments that indicate a virtual loopback-style device.
    static let virtualDeviceKeywords: [String] = [
        "blackhole", "soundflower", "loopback", "background music",
        "vb-cable", "audio hijack", "rogue amoeba", "virtual",
    ]

    /// All Core Audio devices that expose at least one input channel.
    static func inputDevices() -> [AudioInputDevice] {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var dataSize: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize
        ) == noErr, dataSize > 0 else { return [] }

        let deviceCount = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = [AudioDeviceID](repeating: 0, count: deviceCount)
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize, &deviceIDs
        ) == noErr else { return [] }

        return deviceIDs.compactMap { deviceID in
            guard channelCount(of: deviceID, scope: kAudioDevicePropertyScopeInput) > 0,
                  let name = deviceName(of: deviceID) else { return nil }
            let lowered = name.lowercased()
            let isVirtual = virtualDeviceKeywords.contains { lowered.contains($0) }
            return AudioInputDevice(id: deviceID, name: name, isVirtual: isVirtual)
        }
    }

    /// All Core Audio devices that expose at least one output channel.
    /// Speak Mode routes synthesized speech to one of these — typically
    /// BlackHole, which conferencing apps then select as their microphone.
    static func outputDevices() -> [AudioOutputDevice] {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var dataSize: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize
        ) == noErr, dataSize > 0 else { return [] }

        let deviceCount = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = [AudioDeviceID](repeating: 0, count: deviceCount)
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize, &deviceIDs
        ) == noErr else { return [] }

        return deviceIDs.compactMap { deviceID in
            guard channelCount(of: deviceID, scope: kAudioDevicePropertyScopeOutput) > 0,
                  let name = deviceName(of: deviceID) else { return nil }
            let lowered = name.lowercased()
            let isVirtual = virtualDeviceKeywords.contains { lowered.contains($0) }
            return AudioOutputDevice(id: deviceID, name: name, isVirtual: isVirtual)
        }
    }

    static func outputDevice(named name: String) -> AudioOutputDevice? {
        outputDevices().first { $0.name == name }
    }

    static func device(named name: String) -> AudioInputDevice? {
        inputDevices().first { $0.name == name }
    }

    static func defaultInputDevice() -> AudioInputDevice? {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var deviceID = AudioDeviceID(0)
        var dataSize = UInt32(MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize, &deviceID
        ) == noErr, deviceID != 0 else { return nil }
        return inputDevices().first { $0.id == deviceID }
    }

    // MARK: - Private helpers

    private static func channelCount(of deviceID: AudioDeviceID, scope: AudioObjectPropertyScope) -> Int {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreamConfiguration,
            mScope: scope,
            mElement: kAudioObjectPropertyElementMain
        )
        var dataSize: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(deviceID, &address, 0, nil, &dataSize) == noErr,
              dataSize > 0 else { return 0 }

        let rawPointer = UnsafeMutableRawPointer.allocate(
            byteCount: Int(dataSize),
            alignment: MemoryLayout<AudioBufferList>.alignment
        )
        defer { rawPointer.deallocate() }

        guard AudioObjectGetPropertyData(deviceID, &address, 0, nil, &dataSize, rawPointer) == noErr else {
            return 0
        }
        let bufferList = UnsafeMutableAudioBufferListPointer(
            rawPointer.assumingMemoryBound(to: AudioBufferList.self)
        )
        return bufferList.reduce(0) { $0 + Int($1.mNumberChannels) }
    }

    private static func deviceName(of deviceID: AudioDeviceID) -> String? {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceNameCFString,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var name: Unmanaged<CFString>?
        var dataSize = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        let status = withUnsafeMutablePointer(to: &name) { pointer in
            AudioObjectGetPropertyData(deviceID, &address, 0, nil, &dataSize, pointer)
        }
        guard status == noErr, let cfName = name?.takeRetainedValue() else { return nil }
        let result = cfName as String
        return result.isEmpty ? nil : result
    }
}
