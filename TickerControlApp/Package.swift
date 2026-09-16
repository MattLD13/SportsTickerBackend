// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TickerControlState",
    products: [
        .library(name: "TickerControlState", targets: ["TickerControlState"]),
    ],
    targets: [
        .target(
            name: "TickerControlState",
            path: "TickerControl",
            exclude: [
                "ContentView.swift",
                "TickerControlApp.swift",
                "Assets.xcassets",
                "TickerScheduleView.swift",
                "TickerControl.entitlements",
                "Models/TickerHardwareProfile.swift",
            ],
            sources: ["DeviceListState.swift", "TickerScheduleModels.swift"]
        ),
        .testTarget(
            name: "TickerControlStateTests",
            dependencies: ["TickerControlState"],
            path: "TickerControlTests"
        ),
    ]
)
