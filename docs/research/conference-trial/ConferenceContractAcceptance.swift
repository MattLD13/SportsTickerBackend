import Foundation
import XCTest
@testable import TickerControlState

final class ConferenceContractAcceptance: XCTestCase {
    func testExistingCatalogMetadataDecodesWithoutChangingIdentity() throws {
        let data = Data("""
        {"leagues":[
          {"id":"ncf_fbs","label":"NCAA (FBS)","type":"sport","enabled":true},
          {"id":"ncf_fbs:4","label":"Shared label","type":"sport","enabled":true,"conference_parent":"ncf_fbs","conference_id":"4","my_teams_enabled":false},
          {"id":"ncf_fcs:4","label":"Shared label","type":"sport","enabled":true,"conference_parent":"ncf_fcs","conference_id":"4","my_teams_enabled":false},
          {"id":"nfl","label":"NFL","type":"sport"},
          {"id":"custom_sport","label":"College football FBS","type":"sport"},
          {"id":"tech","label":"Technology","type":"stock"}
        ]}
        """.utf8)
        let catalog = try JSONDecoder().decode(V2LeagueCatalog.self, from: data)
        XCTAssertEqual(catalog.leagues.count, 6)
        XCTAssertEqual(catalog.leagues[1].id, "ncf_fbs:4")
        XCTAssertEqual(catalog.leagues[1].conference_parent, "ncf_fbs")
        XCTAssertEqual(catalog.leagues[2].conference_parent, "ncf_fcs")
        XCTAssertNil(catalog.leagues[3].conference_parent)
        XCTAssertNil(catalog.leagues[4].conference_parent)
        XCTAssertEqual(catalog.leagues[5].type, "stock")
    }

    func testSavedIdentifiersSurviveSettingsSerialization() throws {
        let choices = ["ncf_fbs": false, "ncf_fbs:4": false, "ncf_fbs:99": true,
                       "ncf_fcs": true, "ncf_fcs:4": true, "nfl": false]
        let original = TickerState(active_sports: choices)
        let restored = try JSONDecoder().decode(TickerState.self, from: JSONEncoder().encode(original))
        XCTAssertEqual(restored.active_sports, choices)
    }
}
