import Foundation

/// Choose when the app reads the display data again. A user edit stops polling, so a read cannot undo the edit.
/// After a mode change, a burst of fast reads shows the result quickly.
nonisolated struct PollingPolicy {
    private var lastPoll: Date = .distantPast
    private var burstUntil: Date = .distantPast

    static func interval(mode: String) -> TimeInterval {
        switch mode {
        case "music", "sports": return 1
        case "flights", "airports": return 60
        case "stock": return 30
        case "weather", "clock": return 600
        default: return 5
        }
    }

    mutating func beginBurst(at now: Date) { burstUntil = now.addingTimeInterval(30) }

    mutating func shouldPoll(at now: Date, mode: String, isEditing: Bool) -> Bool {
        guard !isEditing else { return false }
        let interval = now < burstUntil ? 0.5 : Self.interval(mode: mode)
        guard now.timeIntervalSince(lastPoll) >= interval else { return false }
        lastPoll = now
        return true
    }
}
