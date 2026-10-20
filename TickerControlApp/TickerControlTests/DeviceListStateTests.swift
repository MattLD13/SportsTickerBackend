import XCTest
@testable import TickerControlState

final class DeviceListStateTests: XCTestCase {
    func testRepairKeepsSameTickerIDSelected() {
        var selection = DeviceSelectionReducer(activeTickerID: "ticker-a")

        XCTAssertTrue(selection.selectPairedTicker("ticker-a", tokenWasSaved: true))
        XCTAssertEqual(selection.activeTickerID, "ticker-a")
    }

    func testStaleListCompletionIsRejectedAfterFreshCompletionStarts() {
        var gate = TickerRequestGate()
        let stale = gate.begin(tickerID: "ticker-a", authorizationToken: "old-token", serverURL: "https://ticker.example")
        let fresh = gate.begin(tickerID: "ticker-a", authorizationToken: "new-token", serverURL: "https://ticker.example")

        XCTAssertFalse(gate.accepts(stale, activeTickerID: "ticker-a", activeAuthorizationToken: "new-token", activeServerURL: "https://ticker.example"))
        XCTAssertTrue(gate.accepts(fresh, activeTickerID: "ticker-a", activeAuthorizationToken: "new-token", activeServerURL: "https://ticker.example"))
    }

    func testEmptyListDoesNotSelectAnotherTicker() {
        let selection = DeviceSelectionReducer(activeTickerID: "ticker-a")

        XCTAssertEqual(selection.activeTickerID, "ticker-a")
    }

    func testServerChangeRejectsSameTickerAndToken() {
        var gate = TickerRequestGate()
        let request = gate.begin(tickerID: "ticker-a", authorizationToken: "token", serverURL: "https://first.example")
        XCTAssertFalse(gate.accepts(request, activeTickerID: "ticker-a", activeAuthorizationToken: "token",
                                    activeServerURL: "https://second.example"))
    }

    func testInvalidationRejectsCompletionAfterSwitchingAwayAndBack() {
        var gate = TickerRequestGate()
        let request = gate.begin(tickerID: "ticker-a", authorizationToken: "token", serverURL: "https://ticker.example")
        gate.invalidate()
        XCTAssertFalse(gate.accepts(request, activeTickerID: "ticker-a", activeAuthorizationToken: "token",
                                    activeServerURL: "https://ticker.example"))
    }

    func testOnlyLatestSaveCanComplete() {
        var gate = TickerRequestGate()
        let first = gate.begin(tickerID: "ticker-a", authorizationToken: "token", serverURL: "https://ticker.example")
        let second = gate.begin(tickerID: "ticker-a", authorizationToken: "token", serverURL: "https://ticker.example")
        XCTAssertFalse(gate.accepts(first, activeTickerID: "ticker-a", activeAuthorizationToken: "token",
                                    activeServerURL: "https://ticker.example"))
        XCTAssertTrue(gate.accepts(second, activeTickerID: "ticker-a", activeAuthorizationToken: "token",
                                   activeServerURL: "https://ticker.example"))
        XCTAssertFalse(gate.accepts(second, activeTickerID: "ticker-b", activeAuthorizationToken: "token",
                                    activeServerURL: "https://ticker.example"))
    }

    func testFailedTokenWriteDoesNotSelectTicker() {
        var selection = DeviceSelectionReducer(activeTickerID: nil)

        XCTAssertFalse(selection.selectPairedTicker("ticker-a", tokenWasSaved: false))
        XCTAssertNil(selection.activeTickerID)
    }

    func testUnpairSelectsRemainingTickerOrClearsSelection() {
        var selection = DeviceSelectionReducer(activeTickerID: "ticker-a")
        selection.selectAfterRemoving("ticker-a", remainingTickerIDs: ["ticker-b"])
        XCTAssertEqual(selection.activeTickerID, "ticker-b")

        selection.selectAfterRemoving("ticker-b", remainingTickerIDs: [])
        XCTAssertNil(selection.activeTickerID)
    }
}
