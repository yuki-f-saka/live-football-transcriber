// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "AudioCapture",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "audio-capture",
            path: "Sources/AudioCapture"
        )
    ]
)
