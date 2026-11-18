import Foundation
import AVFoundation
import CoreAudio

guard CommandLine.arguments.count >= 3 else {
    fputs("Usage: record_mic.swift output.wav seconds\n", stderr)
    exit(2)
}
guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
    fputs("Microphone permission is not authorized.\n", stderr)
    exit(3)
}
var device = AudioDeviceID(0)
var size = UInt32(MemoryLayout<AudioDeviceID>.size)
var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultInputDevice, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
if AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device) == noErr {
    var deviceName: CFString = "Unknown" as CFString
    size = UInt32(MemoryLayout<CFString>.size)
    address.mSelector = kAudioObjectPropertyName
    if AudioObjectGetPropertyData(device, &address, 0, nil, &size, &deviceName) == noErr {
        print("Input device: \(deviceName)")
    }
}
let seconds = Double(CommandLine.arguments[2]) ?? 15
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let settings: [String: Any] = [
    AVFormatIDKey: Int(kAudioFormatLinearPCM),
    AVSampleRateKey: 16000.0,
    AVNumberOfChannelsKey: 1,
    AVLinearPCMBitDepthKey: 16,
    AVLinearPCMIsFloatKey: false,
    AVLinearPCMIsBigEndianKey: false
]
do {
    let recorder = try AVAudioRecorder(url: url, settings: settings)
    guard recorder.prepareToRecord(), (seconds > 0 ? recorder.record(forDuration: seconds) : recorder.record()) else {
        fputs("Microphone recording could not start.\n", stderr)
        exit(4)
    }
    print(seconds > 0 ? "Recording microphone for \(seconds) seconds." : "Recording microphone until stop flag.")
    fflush(stdout)
    if seconds > 0 {
        RunLoop.current.run(until: Date(timeIntervalSinceNow: seconds + 0.5))
    } else {
        let stopPath = CommandLine.arguments.count >= 4 ? CommandLine.arguments[3] : "work/microphone-stop.flag"
        while !FileManager.default.fileExists(atPath: stopPath) {
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.25))
        }
    }
    recorder.stop()
    print("Saved: \(url.path)")
    if seconds <= 0 {
        try "done".write(toFile: url.path + ".done", atomically: true, encoding: .utf8)
    }
} catch {
    fputs("Recording error: \(error)\n", stderr)
    exit(5)
}
