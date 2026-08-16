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

    func testScrollLevelEightKeepsItsCurrentPhysicalSpeed() {
        XCTAssertEqual(ScrollSpeedScale.pixelInterval(for: 8), 0.03, accuracy: 0.000_001)
        XCTAssertEqual(ScrollSpeedScale.level(forPixelInterval: 0.03), 8)
    }

    func testScrollLevelsRoundTripAcrossTheBoundedSpeedRange() {
        let intervals = (1...10).map { ScrollSpeedScale.pixelInterval(for: Double($0)) }

        XCTAssertEqual(intervals[0], 0.10, accuracy: 0.000_001)
        XCTAssertEqual(intervals[9], 0.025, accuracy: 0.000_001)
        XCTAssertTrue(zip(intervals, intervals.dropFirst()).allSatisfy { pair in pair.0 > pair.1 })
        for level in 1...10 {
            let interval = ScrollSpeedScale.pixelInterval(for: Double(level))
            XCTAssertEqual(ScrollSpeedScale.level(forPixelInterval: interval), Double(level))
        }
    }
}
