// swift-tools-version: 6.2
import PackageDescription

// The upcoming concurrency features of the app target.
let concurrencySettings: [SwiftSetting] = [
    .enableUpcomingFeature("NonisolatedNonsendingByDefault"),
    .enableUpcomingFeature("InferIsolatedConformances"),
    .enableUpcomingFeature("InferSendableFromCaptures"),
    .enableUpcomingFeature("GlobalActorIsolatedTypesUsability"),
    .enableUpcomingFeature("DisableOutwardActorInference"),
    .enableUpcomingFeature("MemberImportVisibility"),
]

// The app target isolates its code to the main actor by default, so the core does the same.
// XCTest cases are nonisolated, so the tests mark their main-actor types explicitly.
let appSettings: [SwiftSetting] = [.defaultIsolation(MainActor.self)] + concurrencySettings

let package = Package(
    name: "TickerControlCore",
    platforms: [.macOS(.v14), .iOS(.v18)],
    products: [
        .library(name: "TickerControlCore", targets: ["TickerControlCore"]),
    ],
    targets: [
        .target(name: "TickerControlCore", path: "TickerControl/Core", swiftSettings: appSettings),
        .testTarget(name: "TickerControlCoreTests", dependencies: ["TickerControlCore"], path: "TickerControlTests",
                    swiftSettings: concurrencySettings),
    ],
    swiftLanguageModes: [.v5]
)
