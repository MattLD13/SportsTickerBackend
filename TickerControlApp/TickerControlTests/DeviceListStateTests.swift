import XCTest
@testable import TickerControlState

final class DeviceListStateTests: XCTestCase {
    func testRepairKeepsSameTickerIDSelected() {
        var selection = DeviceSelectionReducer(activeTickerID: "ticker-a")

        XCTAssertTrue(selection.selectPairedTicker("ticker-a", tokenWasSaved: true))
        XCTAssertEqual(selection.activeTickerID, "ticker-a")
    }

    func testStaleListCompletionIsRejectedAfterFreshCompletionStarts() {
        var gate = DeviceListRequestGate()
        let stale = gate.begin(tickerID: "ticker-a", authorizationToken: "old-token")
        let fresh = gate.begin(tickerID: "ticker-a", authorizationToken: "new-token")

        XCTAssertFalse(gate.accepts(stale, activeTickerID: "ticker-a", activeAuthorizationToken: "new-token"))
        XCTAssertTrue(gate.accepts(fresh, activeTickerID: "ticker-a", activeAuthorizationToken: "new-token"))
    }

    func testEmptyListDoesNotSelectAnotherTicker() {
        let selection = DeviceSelectionReducer(activeTickerID: "ticker-a")

        XCTAssertEqual(selection.activeTickerID, "ticker-a")
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
