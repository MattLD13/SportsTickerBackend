import Foundation

/// The weekly schedule and the live-game rule of one ticker.
extension TickerStore {
    private func authorized(_ tickerID: String) throws -> Scope {
        guard let scope = scope(tickerID) else { throw APIError.notPaired }
        return scope
    }

    func loadSchedule(_ tickerID: String) async throws -> Schedule {
        try await api.send(API.schedule(tickerID), token: authorized(tickerID).token)
    }

    func saveBlock(_ tickerID: String, id: String?, _ draft: ScheduleBlockDraft) async throws {
        let token = try authorized(tickerID).token
        if let id { _ = try await api.send(API.updateBlock(tickerID, block: id, draft), token: token) }
        else { _ = try await api.send(API.createBlock(tickerID, draft), token: token) }
    }

    func deleteBlock(_ tickerID: String, id: String) async throws {
        _ = try await api.send(API.deleteBlock(tickerID, block: id), token: authorized(tickerID).token)
    }

    func saveCondition(_ tickerID: String, id: String?, _ draft: ScheduleConditionDraft) async throws {
        let token = try authorized(tickerID).token
        if let id { _ = try await api.send(API.updateCondition(tickerID, condition: id, draft), token: token) }
        else { _ = try await api.send(API.createCondition(tickerID, draft), token: token) }
    }

    func deleteCondition(_ tickerID: String, id: String) async throws {
        _ = try await api.send(API.deleteCondition(tickerID, condition: id), token: authorized(tickerID).token)
    }

    /// Pause the schedule until its next change, or resume it.
    func setScheduleOverride(_ tickerID: String, enabled: Bool) async throws {
        _ = try await api.send(API.updateTicker(tickerID, TickerChange(scheduleOverride: enabled)), token: authorized(tickerID).token)
    }

    /// Pause or resume the schedule of the active ticker, then read the new state.
    func setScheduleOverride(_ enabled: Bool) async throws {
        let scope = try authorized(activeTickerID ?? "")
        try await setScheduleOverride(scope.tickerID, enabled: enabled)
        guard isCurrent(scope) else { throw CancellationError() }
        beginBurst()
        await refreshData()
        let value = try await loadSchedule(scope.tickerID)
        guard isCurrent(scope) else { throw CancellationError() }
        schedule = value.effective
    }

    /// Read the display data after a schedule change, so the feed shows the new mode.
    func scheduleChanged() { Task { await refreshData() } }
}
