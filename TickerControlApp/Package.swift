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
                "Services/BLEProvisioningCoordinator.swift",
                "ViewModels",
                "Views",
            ],
            sources: ["DeviceListState.swift", "TickerScheduleModels.swift", "Models/TickerHardwareProfile.swift", "Models/TickerContentModels.swift", "Services/TickerHTTPClient.swift"]
        ),
        .testTarget(
            name: "TickerControlStateTests",
            dependencies: ["TickerControlState"],
            path: "TickerControlTests"
        ),
    ]
)
