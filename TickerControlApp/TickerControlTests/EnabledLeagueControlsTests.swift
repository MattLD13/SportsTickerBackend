import Foundation
import XCTest
@testable import TickerControlState

final class EnabledLeagueControlsTests: XCTestCase {
    private func catalog(_ json: String) throws -> [LeagueOption] {
        try JSONDecoder().decode(V2LeagueCatalog.self, from: Data(json.utf8)).leagues
    }

    private func options() throws -> [LeagueOption] {
        try catalog("""
        {"leagues":[
          {"id":"nfl","label":"NFL","type":"sport"},
          {"id":"ncf_fbs","label":"College FBS","type":"sport"},
          {"id":"future-choice-A","label":"Shared Conference","type":"sport",
           "conference_id":"4","conference_parent":"ncf_fbs"},
          {"id":"ncf_fcs","label":"College FCS","type":"sport"},
          {"id":"ncf_fcs:4","label":"Shared Conference","type":"sport",
           "conference_id":"4","conference_parent":"ncf_fcs"},
          {"id":"ncf_fbs:999","label":"New Conference","type":"sport",
           "conference_id":"999","conference_parent":"ncf_fcs"},
          {"id":"stock-tech","label":"Technology","type":"stock"}
        ]}
        """)
    }

    func testCatalogDecodesConferenceParentAndOrdinaryOptions() throws {
        let options = try options()
        XCTAssertNil(options[0].conference_parent)
        XCTAssertNil(options[1].conference_parent)
        XCTAssertEqual(options[2].conference_parent, "ncf_fbs")
        XCTAssertEqual(options[4].conference_parent, "ncf_fcs")
        XCTAssertNil(options[6].conference_parent)
        XCTAssertEqual(options[6].type, "stock")
        XCTAssertNil(options[6].enabled)
        XCTAssertNil(options[6].my_teams_enabled)
    }

    func testGroupsUseMetadataAndKeepCatalogOrderWithoutDuplicateConferences() throws {
        let groups = EnabledLeagueControls.groups(from: try options())
        XCTAssertEqual(groups.map(\.id), ["nfl", "ncf_fbs", "ncf_fcs"])
        XCTAssertTrue(groups[0].conferences.isEmpty)
        XCTAssertFalse(groups[0].hasConferenceDisclosure)
        XCTAssertEqual(groups[1].conferences.map(\.id), ["future-choice-A"])
        XCTAssertEqual(groups[2].conferences.map(\.id), ["ncf_fcs:4", "ncf_fbs:999"])
        XCTAssertEqual(groups[1].conferences[0].label, groups[2].conferences[0].label)
        XCTAssertTrue(groups[1].hasConferenceDisclosure)
        XCTAssertTrue(groups[2].hasConferenceDisclosure)
    }

    func testMissingAndEmptyConferenceListsKeepBothParentControls() throws {
        let options = try catalog("""
        {"leagues":[
          {"id":"ncf_fbs","label":"FBS","type":"sport","conferences":[]},
          {"id":"ncf_fcs","label":"FCS","type":"sport","conference_parent":null}
        ]}
        """)
        let groups = EnabledLeagueControls.groups(from: options)
        XCTAssertEqual(groups.map(\.id), ["ncf_fbs", "ncf_fcs"])
        XCTAssertTrue(groups.allSatisfy { $0.conferences.isEmpty && $0.hasConferenceDisclosure })
        XCTAssertTrue(EnabledLeagueControls.groups(from: []).isEmpty)
    }

    func testNewParentWithConferenceMetadataGetsItsOwnGroup() throws {
        let options = try catalog("""
        {"leagues":[
          {"id":"future-parent","label":"Future League","type":"sport"},
          {"id":"unrelated-key","label":"Future Conference","type":"sport",
           "conference_parent":"future-parent"}
        ]}
        """)
        let groups = EnabledLeagueControls.groups(from: options)
        XCTAssertEqual(groups.count, 1)
        XCTAssertEqual(groups[0].conferences.map(\.id), ["unrelated-key"])
        XCTAssertTrue(groups[0].hasConferenceDisclosure)
    }

    func testDisclosuresStartCollapsedAndChangeIndependently() {
        var controls = EnabledLeagueControls()
        XCTAssertTrue(controls.expandedParents.isEmpty)
        controls.toggleDisclosure(for: "ncf_fbs")
        XCTAssertEqual(controls.expandedParents, Set(["ncf_fbs"]))
        controls.toggleDisclosure(for: "ncf_fcs")
        XCTAssertEqual(controls.expandedParents, Set(["ncf_fbs", "ncf_fcs"]))
        controls.toggleDisclosure(for: "ncf_fbs")
        XCTAssertEqual(controls.expandedParents, Set(["ncf_fcs"]))
        controls.toggleDisclosure(for: "ncf_fcs")
        XCTAssertTrue(controls.expandedParents.isEmpty)
    }

    func testEachToggleChangesOnlyItsOwnSettingsKeyAndRestoresChoices() throws {
        let options = try options()
        let initial = [
            "nfl": false, "ncf_fbs": true, "ncf_fcs": false,
            "future-choice-A": false, "ncf_fcs:4": true, "ncf_fbs:999": false,
            "stock-tech": true, "unknown-setting": false
        ]
        for option in options where option.type == "sport" {
            var state = TickerState(
                active_sports: initial, mode: "sports", sports_filter: "my_teams",
                my_teams: ["nfl:1"], ticker_id: "test-ticker",
                pinned_game: "game-1", pinned_games: ["game-1", "game-2"],
                sports_presentation: "pinned", pinned_content_id: "game-1"
            )
            let before = try nonLeagueSettings(state)
            EnabledLeagueControls.toggle(option, in: &state.active_sports)
            var expected = initial
            expected[option.id] = !initial[option.id]!
            XCTAssertEqual(state.active_sports, expected, option.id)
            XCTAssertEqual(try nonLeagueSettings(state), before, option.id)
            EnabledLeagueControls.toggle(option, in: &state.active_sports)
            XCTAssertEqual(state.active_sports, initial, option.id)
        }
    }

    func testMissingSelectionUsesExistingEnabledDefaultWithoutChangingOtherKeys() throws {
        let option = try XCTUnwrap(try options().first { $0.id == "future-choice-A" })
        var active = ["ncf_fbs": false, "ncf_fcs:4": true]
        EnabledLeagueControls.toggle(option, in: &active)
        XCTAssertEqual(active, ["ncf_fbs": false, "ncf_fcs:4": true, "future-choice-A": false])
    }

    private func nonLeagueSettings(_ state: TickerState) throws -> NSDictionary {
        let data = try JSONEncoder().encode(state)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        object.removeValue(forKey: "active_sports")
        return object as NSDictionary
    }
}
