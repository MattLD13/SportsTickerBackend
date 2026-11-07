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

    func testRacingAndGamesUseStartTimeAcrossFamilies() throws {
        let data = Data(#"""
        {"settings":{"mode":"sports"},"meta":{},"content":{
          "sports":[
            {"id":"early","family":"sports","kind":"scoreboard","is_shown":true,"data":{"sport":"nhl","state":"pre","status":"Scheduled","startTimeUTC":"2026-11-07T18:00Z"}},
            {"id":"late","family":"sports","kind":"scoreboard","is_shown":true,"data":{"sport":"nfl","state":"in","status":"Live","startTimeUTC":"2026-11-07T20:00:00Z"}},
            {"id":"final","family":"sports","kind":"scoreboard","is_shown":true,"data":{"sport":"nhl","state":"post","status":"Final","startTimeUTC":"2026-11-07T16:00:00Z"}}
          ],
          "racing":[{"id":"race","family":"racing","kind":"f1","is_shown":true,"data":{"sport":"f1","state":"in","status":"Q2","startTimeUTC":"2026-11-07T19:00:00+00:00"}}]
        }}
        """#.utf8)
        let response = try TickerDisplayResponse(data: data)
        XCTAssertEqual(response.orderedGames(pinnedIDs: []).map(\.id), ["early", "race", "late", "final"])
        XCTAssertEqual(response.orderedGames(pinnedIDs: ["race"]).first?.id, "race")
    }
}
