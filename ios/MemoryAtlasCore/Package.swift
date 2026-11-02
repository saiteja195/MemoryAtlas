// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "MemoryAtlasCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "MemoryAtlasCore", targets: ["MemoryAtlasCore"])],
    targets: [
        .target(name: "MemoryAtlasCore"),
        .testTarget(name: "MemoryAtlasCoreTests", dependencies: ["MemoryAtlasCore"]),
    ]
)
