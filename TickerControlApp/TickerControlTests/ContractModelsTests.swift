import Foundation
import XCTest
@testable import TickerControlState

final class ContractModelsTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let repository = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return try Data(contentsOf: repository.appendingPathComponent("docs/contracts/fixtures/\(name).json"))
    }

    func testDisplayContractDecodesInExtractedModels() throws {
        let response = try JSONDecoder().decode(V2DataResponse.self, from: fixture("display-response"))
        XCTAssertFalse(response.settings.mode.isEmpty)
        XCTAssertEqual(response.games.count, 0)
    }

    func testHardwareProfileContractDecodes() throws {
        let profile = try JSONDecoder().decode(TickerProfile.self, from: fixture("hardware-profile-response"))
        XCTAssertGreaterThan(profile.display.width, 0)
        XCTAssertGreaterThan(profile.display.height, 0)
        XCTAssertTrue(profile.capabilities.modes.contains("sports"))
    }

    func testSportsContractKeepsGameIdentity() throws {
        let response = try JSONDecoder().decode(V2DataResponse.self, from: fixture("display/sports"))
        XCTAssertFalse(response.games.isEmpty)
        let identifiers = Set(response.content.values.flatMap { $0 }.map(\.id))
        for game in response.games {
            XCTAssertTrue(identifiers.contains(game.id))
        }
    }

    func testScheduleContractRoundTrip() throws {
        let decoder = JSONDecoder()
        let response = try decoder.decode(TickerScheduleResponse.self, from: fixture("schedule-response"))
        XCTAssertTrue(response.effective.has_enabled_rules)
        let encoded = try JSONEncoder().encode(response)
        XCTAssertEqual(try decoder.decode(TickerScheduleResponse.self, from: encoded), response)
    }

    func testScheduleStatusContractRoundTrip() throws {
        let decoder = JSONDecoder()
        let status = try decoder.decode(TickerScheduleStatus.self, from: fixture("schedule-status-response"))
        XCTAssertFalse(status.has_enabled_rules)
        XCTAssertEqual(try decoder.decode(TickerScheduleStatus.self, from: JSONEncoder().encode(status)), status)
    }
}
