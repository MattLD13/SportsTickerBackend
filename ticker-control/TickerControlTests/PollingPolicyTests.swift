import Foundation
import XCTest
@testable import TickerControlState

final class PollingPolicyTests: XCTestCase {
    func testIntervalsEditingAndBurstExpiry() {
        let start = Date(timeIntervalSince1970: 1_000)
        for (mode, interval) in [("sports", 1.0), ("music", 1), ("flights", 60), ("airports", 60),
                                 ("stock", 30), ("weather", 600), ("clock", 600)] {
            var policy = TickerPollingPolicy()
            XCTAssertTrue(policy.takePoll(at: start, mode: mode, isEditing: false))
            XCTAssertFalse(policy.takePoll(at: start.addingTimeInterval(interval - 0.1), mode: mode, isEditing: false))
            XCTAssertFalse(policy.takePoll(at: start.addingTimeInterval(interval), mode: mode, isEditing: true))
            XCTAssertTrue(policy.takePoll(at: start.addingTimeInterval(interval), mode: mode, isEditing: false))
            policy.beginBurst(at: start.addingTimeInterval(interval))
            XCTAssertTrue(policy.takePoll(at: start.addingTimeInterval(interval + 0.5), mode: mode, isEditing: false))
            if interval > 30 {
                XCTAssertFalse(policy.takePoll(at: start.addingTimeInterval(interval + 30), mode: mode, isEditing: false))
            }
        }
    }

    func testExtractedResponseKeepsPinnedGameFirst() throws {
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: repository.appendingPathComponent("docs/contracts/fixtures/display/sports.json"))
        let response = try TickerDisplayResponse(data: data)
        let selected = try XCTUnwrap(response.response.games.last)
        XCTAssertEqual(response.orderedGames(pinnedIDs: [selected.id]).first?.id, selected.id)
    }
}
