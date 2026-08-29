import AppKit
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

// Initialize CGS connection required by SCContentFilter
_ = NSApplication.shared

// MARK: - Argument parsing

guard CommandLine.arguments.count > 1 else {
    fputs("Usage: audio-capture <window-title-filter>\n", stderr)
    fputs("Example: audio-capture 'Premier League'\n", stderr)
    exit(1)
}
let titleFilter = CommandLine.arguments[1]

// MARK: - Permission check

guard CGPreflightScreenCaptureAccess() else {
    CGRequestScreenCaptureAccess()
    fputs(
        "[audio-capture] Screen Recording permission required.\n"
        + "Grant it in System Settings → Privacy & Security → Screen Recording, then re-run.\n",
        stderr
    )
    exit(1)
}

// MARK: - Stream handler

/// Receives SCStream audio callbacks and writes raw Int16 PCM to stdout.
final class StreamHandler: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let stdout = FileHandle.standardOutput

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of outputType: SCStreamOutputType
    ) {
        guard outputType == .audio else { return }
        guard let dataBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }

        var length = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        guard CMBlockBufferGetDataPointer(
            dataBuffer, atOffset: 0,
            lengthAtOffsetOut: nil,
            totalLengthOut: &length,
            dataPointerOut: &dataPointer
        ) == kCMBlockBufferNoErr,
            let ptr = dataPointer, length > 0
        else { return }

        // SCStream outputs Float32 PCM — convert to Int16 for Whisper/PyAudio compatibility
        let sampleCount = length / MemoryLayout<Float32>.size
        let floats = UnsafeBufferPointer(
            start: UnsafeRawPointer(ptr).assumingMemoryBound(to: Float32.self),
            count: sampleCount
        )
        var int16s = [Int16](repeating: 0, count: sampleCount)
        for i in 0..<sampleCount {
            int16s[i] = Int16(clamping: Int32(floats[i] * 32_767))
        }

        int16s.withUnsafeBytes { stdout.write(Data($0)) }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("[audio-capture] Stream stopped: \(error)\n", stderr)
        exit(1)
    }
}

// MARK: - Capture setup

let handler = StreamHandler()

// Held at module scope to prevent ARC from deallocating the stream after Task completes
var captureStream: SCStream?

signal(SIGINT) { _ in
    fputs("[audio-capture] Stopped.\n", stderr)
    exit(0)
}

Task {
    do {
        // Always fetch fresh content — never cache SCContentFilter (permissions can be revoked)
        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: true)

        // Find the first window whose title contains the filter string,
        // excluding terminal emulators (whose titles often echo the running command)
        let terminalBundleIDs: Set<String> = [
            "com.apple.Terminal",
            "com.googlecode.iterm2",
            "net.kovidgoyal.kitty",
            "com.mitchellh.ghostty",
        ]
        let targetWindow = content.windows.first { window in
            guard let title = window.title, !title.isEmpty else { return false }
            if let bundleID = window.owningApplication?.bundleIdentifier,
               terminalBundleIDs.contains(bundleID) { return false }
            return title.localizedCaseInsensitiveContains(titleFilter)
        }

        guard let window = targetWindow else {
            let available = content.windows.compactMap { $0.title }.filter { !$0.isEmpty }
            fputs("[audio-capture] No window found matching '\(titleFilter)'.\n", stderr)
            fputs("Available windows:\n", stderr)
            available.forEach { fputs("  - \($0)\n", stderr) }
            exit(1)
        }

        guard let targetApp = window.owningApplication else {
            fputs("[audio-capture] Could not get owning application.\n", stderr)
            exit(1)
        }
        guard let display = content.displays.first else {
            fputs("[audio-capture] No display found.\n", stderr)
            exit(1)
        }

        fputs("[audio-capture] Capturing audio from: \(window.title ?? "unknown") (\(targetApp.applicationName))\n", stderr)

        // desktopIndependentWindow does not deliver audio callbacks — use a display filter
        // scoped to the target app instead
        let filter = SCContentFilter(display: display, including: [targetApp], exceptingWindows: [])

        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.sampleRate = 16_000
        config.channelCount = 1
        config.excludesCurrentProcessAudio = true

        let stream = SCStream(filter: filter, configuration: config, delegate: handler)
        captureStream = stream  // retain at module scope
        try stream.addStreamOutput(handler, type: .audio, sampleHandlerQueue: .global())
        try await stream.startCapture()

        fputs("[audio-capture] Streaming 16kHz mono Int16 PCM to stdout... (Ctrl+C to stop)\n", stderr)
    } catch {
        fputs("[audio-capture] Setup error: \(error)\n", stderr)
        exit(1)
    }
}

RunLoop.main.run()
