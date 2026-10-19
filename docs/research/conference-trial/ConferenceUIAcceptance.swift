import XCTest

final class ConferenceUIAcceptance: XCTestCase {
    var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-conferenceTrialFixture"]
        app.launch()
        XCTAssertTrue(app.staticTexts["fixture-state"].waitForExistence(timeout: 15))
    }

    func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    func tap(_ identifier: String) {
        let control = element(identifier)
        for _ in 0..<12 {
            if control.exists && control.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(control.exists, identifier)
        XCTAssertTrue(control.isHittable, identifier)
        control.tap()
    }

    func state() -> [String: Bool] {
        let label = app.staticTexts["fixture-state"].label
        guard let data = label.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Bool] else {
            XCTFail("Fixture state is not a settings map: \(label)")
            return [:]
        }
        return value
    }

    func expect(_ key: String, _ value: Bool) {
        let expected = NSPredicate { _, _ in self.state()[key] == value }
        expectation(for: expected, evaluatedWith: nil)
        waitForExpectations(timeout: 5)
    }

    func testSectionsStartCollapsedAndOpeningDoesNotSaveOrToggle() {
        XCTAssertFalse(element("conference-ncf_fbs:4").exists)
        XCTAssertFalse(element("conference-ncf_fcs:4").exists)
        tap("conferences-ncf_fbs")
        XCTAssertTrue(element("conference-ncf_fbs:4").exists)
        XCTAssertFalse(element("conference-ncf_fcs:4").exists)
        expect("ncf_fbs", true)
        expect("ncf_fbs:4", true)
        XCTAssertEqual(app.staticTexts["fixture-save-count"].label, "0")
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "fbs-expanded"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        tap("conferences-ncf_fbs")
        XCTAssertFalse(element("conference-ncf_fbs:4").exists)
        XCTAssertEqual(app.staticTexts["fixture-save-count"].label, "0")
    }

    func testParentTogglePreservesConferenceSelectionAndOtherDivision() {
        tap("conferences-ncf_fbs")
        tap("conference-ncf_fbs:4")
        expect("ncf_fbs:4", false)
        expect("ncf_fcs:4", true)
        expect("ncf_fbs", true)
        tap("league-ncf_fbs")
        expect("ncf_fbs", false)
        expect("ncf_fbs:4", false)
        expect("ncf_fbs:99", true)
        expect("ncf_fcs", true)
        tap("league-ncf_fbs")
        expect("ncf_fbs", true)
        expect("ncf_fbs:4", false)
        XCTAssertEqual(app.staticTexts["fixture-save-count"].label, "3")
    }

    func testFCSAndFBSDisclosureStatesAndChoicesAreIndependent() {
        tap("conferences-ncf_fbs")
        tap("conferences-ncf_fcs")
        XCTAssertTrue(element("conference-ncf_fbs:4").exists)
        XCTAssertTrue(element("conference-ncf_fcs:4").exists)
        tap("conference-ncf_fcs:4")
        expect("ncf_fcs:4", false)
        expect("ncf_fbs:4", true)
        tap("conferences-ncf_fbs")
        XCTAssertFalse(element("conference-ncf_fbs:4").exists)
        XCTAssertTrue(element("conference-ncf_fcs:4").exists)
    }

    func testUnknownConferenceUsesMetadataAndUnrelatedSportStaysIndependent() {
        tap("conferences-ncf_fbs")
        tap("conference-ncf_fbs:99")
        expect("ncf_fbs:99", false)
        expect("ncf_fbs:4", true)
        tap("league-custom_sport")
        expect("custom_sport", false)
        expect("ncf_fbs", true)
        XCTAssertFalse(element("conferences-custom_sport").exists)
    }

    func testEmptyConferenceCatalogKeepsBothParentControlsUsable() {
        app.terminate()
        app.launchArguments = ["-conferenceTrialFixture", "-emptyConferenceFixture"]
        app.launch()
        XCTAssertTrue(app.staticTexts["fixture-state"].waitForExistence(timeout: 15))
        tap("league-ncf_fbs")
        expect("ncf_fbs", false)
        expect("ncf_fbs:4", true)
        tap("league-ncf_fcs")
        expect("ncf_fcs", false)
        XCTAssertFalse(element("conference-ncf_fbs:4").exists)
        XCTAssertFalse(element("conference-ncf_fcs:4").exists)
    }
}
