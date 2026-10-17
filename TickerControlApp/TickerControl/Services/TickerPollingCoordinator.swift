import Foundation

struct TickerPollingPolicy {
    private var lastFetch: Date = .distantPast
    private var burstUntil: Date = .distantPast

    mutating func beginBurst(at now: Date) {
        burstUntil = now.addingTimeInterval(30)
    }

    mutating func takePoll(at now: Date, mode: String, isEditing: Bool) -> Bool {
        guard !isEditing else { return false }
        let interval: TimeInterval
        if now < burstUntil {
            interval = 0.5
        } else {
            switch mode {
            case "music", "sports": interval = 1
            case "flights", "airports": interval = 60
            case "stock": interval = 30
            case "weather", "clock": interval = 600
            default: interval = 5
            }
        }
        guard now.timeIntervalSince(lastFetch) >= interval else { return false }
        lastFetch = now
        return true
    }
}

@MainActor
final class TickerPollingCoordinator {
    private var policy = TickerPollingPolicy()
    private var dataTimer: Timer?
    private var deviceTimer: Timer?
    private var saveTimer: Timer?

    func start(state: @escaping @MainActor () -> (mode: String, isEditing: Bool),
               poll: @escaping @MainActor () -> Void,
               refreshDevices: @escaping @MainActor () -> Void) {
        stop()
        dataTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                let current = state()
                if self.policy.takePoll(at: Date(), mode: current.mode, isEditing: current.isEditing) { poll() }
            }
        }
        deviceTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in
            Task { @MainActor in
                if !state().isEditing { refreshDevices() }
            }
        }
    }

    func beginBurst() { policy.beginBurst(at: Date()) }

    func debounceSave(_ action: @escaping @MainActor () -> Void) {
        saveTimer?.invalidate()
        saveTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: false) { _ in
            Task { @MainActor in action() }
        }
    }

    func stop() {
        dataTimer?.invalidate()
        deviceTimer?.invalidate()
        saveTimer?.invalidate()
        dataTimer = nil
        deviceTimer = nil
        saveTimer = nil
    }

    deinit {
        dataTimer?.invalidate()
        deviceTimer?.invalidate()
        saveTimer?.invalidate()
    }
}
