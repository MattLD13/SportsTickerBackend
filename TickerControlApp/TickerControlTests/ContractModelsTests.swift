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

    func testStockAutocompleteDecodesSymbolAndCompanyName() throws {
        let data = Data(#"{"stocks":[{"symbol":"NVDA","name":"NVIDIA Corp"},{"symbol":"BRK.B","name":"Berkshire Hathaway"}]}"#.utf8)
        let response = try JSONDecoder().decode(StockSymbolSearchResponse.self, from: data)
        XCTAssertEqual(response.stocks.map(\.id), ["NVDA", "BRK.B"])
        XCTAssertEqual(response.stocks[0].name, "NVIDIA Corp")
        let encoded = try JSONEncoder().encode(response.stocks[0])
        XCTAssertEqual(try JSONDecoder().decode(StockSymbolOption.self, from: encoded), response.stocks[0])
    }

    func testCustomStockListRoundTripKeepsOrder() throws {
        let data = Data(#"{"mode":"stock","active_sports":{"stock_custom":true},"custom_stock_symbols":["NVDA","BRK.B","AAPL"]}"#.utf8)
        let state = try JSONDecoder().decode(TickerState.self, from: data)
        XCTAssertEqual(state.custom_stock_symbols, ["NVDA", "BRK.B", "AAPL"])
        let encoded = try JSONEncoder().encode(state)
        let restored = try JSONDecoder().decode(TickerState.self, from: encoded)
        XCTAssertEqual(restored.custom_stock_symbols, state.custom_stock_symbols)
        XCTAssertEqual(restored.active_sports["stock_custom"], true)
        let empty = try JSONDecoder().decode(TickerState.self, from: Data("{}".utf8))
        XCTAssertEqual(empty.custom_stock_symbols, [])
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

    func testCompetitionStageUsesTheIntegerWireContract() throws {
        let decoder = JSONDecoder()
        for stage in [0, 1, 2] {
            let data = Data("""
            {"id":"nhl-ot","family":"sports","kind":"scoreboard","is_shown":true,
             "data":{"sport":"nhl","status":"OT","competition_stage":\(stage)}}
            """.utf8)
            let item = try decoder.decode(V2ContentItem.self, from: data)
            let game = try XCTUnwrap(Game(content: item))
            XCTAssertEqual(game.competition_stage?.rawValue, stage)
        }
        XCTAssertThrowsError(try decoder.decode(CompetitionStage.self, from: Data("\"playoff\"".utf8)))
        XCTAssertThrowsError(try decoder.decode(CompetitionStage.self, from: Data("3".utf8)))
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
