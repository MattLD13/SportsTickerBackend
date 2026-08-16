import Foundation

/// Identifies the ticker and token that a device-list request used.
struct DeviceListRequestIdentity: Equatable, Sendable {
    let generation: UInt64
    let tickerID: String
    let authorizationToken: String
}

/// Rejects device-list completions that started before a newer selection or refresh.
struct DeviceListRequestGate: Sendable {
    private(set) var generation: UInt64 = 0

    mutating func begin(tickerID: String, authorizationToken: String) -> DeviceListRequestIdentity {
        generation &+= 1
        return DeviceListRequestIdentity(
            generation: generation,
            tickerID: tickerID,
            authorizationToken: authorizationToken
        )
    }

    mutating func invalidate() {
        generation &+= 1
    }

    func accepts(
        _ request: DeviceListRequestIdentity,
        activeTickerID: String?,
        activeAuthorizationToken: String?
    ) -> Bool {
        request.generation == generation &&
        request.tickerID == activeTickerID &&
        request.authorizationToken == activeAuthorizationToken
    }
}

/// Owns explicit selection changes that device-list fetching cannot perform.
struct DeviceSelectionReducer: Equatable, Sendable {
    private(set) var activeTickerID: String?

    init(activeTickerID: String?) {
        self.activeTickerID = activeTickerID
    }

    mutating func select(_ tickerID: String?) {
        activeTickerID = tickerID
    }

    mutating func selectPairedTicker(_ tickerID: String, tokenWasSaved: Bool) -> Bool {
        guard tokenWasSaved else { return false }
        activeTickerID = tickerID
        return true
    }

    mutating func selectAfterRemoving(_ tickerID: String, remainingTickerIDs: [String]) {
        guard activeTickerID == tickerID else { return }
        activeTickerID = remainingTickerIDs.first
    }
}
