import Foundation

/// Maps the ten UI levels to a bounded physical scroll velocity.
struct ScrollSpeedScale: Sendable {
    static let minimumLevel = 1.0
    static let maximumLevel = 10.0
    static let minimumPixelsPerSecond = 10.0
    static let maximumPixelsPerSecond = 40.0

    static func pixelInterval(for level: Double) -> Double {
        let selected = min(max(level, minimumLevel), maximumLevel)
        let progress = (selected - minimumLevel) / (maximumLevel - minimumLevel)
        let pixelsPerSecond = minimumPixelsPerSecond
            + progress * (maximumPixelsPerSecond - minimumPixelsPerSecond)
        return 1.0 / pixelsPerSecond
    }

    static func level(forPixelInterval interval: Double) -> Double {
        guard interval > 0 else { return 8.0 }
        let pixelsPerSecond = 1.0 / interval
        let progress = (pixelsPerSecond - minimumPixelsPerSecond)
            / (maximumPixelsPerSecond - minimumPixelsPerSecond)
        let level = minimumLevel + progress * (maximumLevel - minimumLevel)
        return min(max(level.rounded(), minimumLevel), maximumLevel)
    }
}
