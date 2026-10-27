import Foundation

/// Identifies the server, ticker, and token used by one request.
struct TickerRequestIdentity: Equatable, Sendable {
    let generation: UInt64
    let tickerID: String
    let authorizationToken: String
    let serverURL: String
}

/// Rejects completions from a replaced request or session.
struct TickerRequestGate: Sendable {
    private(set) var generation: UInt64 = 0

    mutating func begin(tickerID: String, authorizationToken: String, serverURL: String) -> TickerRequestIdentity {
        generation &+= 1
        return TickerRequestIdentity(
            generation: generation,
            tickerID: tickerID,
            authorizationToken: authorizationToken,
            serverURL: serverURL
        )
    }

    mutating func invalidate() {
        generation &+= 1
    }

    func accepts(
        _ request: TickerRequestIdentity,
        activeTickerID: String?,
        activeAuthorizationToken: String?,
        activeServerURL: String
    ) -> Bool {
        request.generation == generation &&
        request.tickerID == activeTickerID &&
        request.authorizationToken == activeAuthorizationToken &&
        request.serverURL == activeServerURL
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
