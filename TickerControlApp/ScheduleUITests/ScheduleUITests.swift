import XCTest

final class ScheduleUITests: XCTestCase {
    private var app: XCUIApplication!

    private func launch(_ arguments: [String] = []) {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-schedulePreview"] + arguments
        app.launch()
    }

    private func button(_ id: String) -> XCUIElement { app.buttons[id] }

    private func wait(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.waitForExistence(timeout: 8), file: file, line: line)
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testOverviewAndDayFilter() {
        launch()
        wait(button("schedule-edit-weather"))
        XCTAssertTrue(button("schedule-edit-sports").exists)
        capture("schedule-overview")
        button("schedule-filter-5").tap()
        wait(button("schedule-edit-music"))
        XCTAssertFalse(button("schedule-edit-weather").exists)
        button("schedule-filter-0").tap()
        wait(button("schedule-edit-weather"))
    }

    func testAddPresetsSaveAndCancel() {
        launch(["-emptySchedulePreview"])
        wait(button("schedule-empty-add"))
        button("schedule-empty-add").tap()
        wait(button("schedule-editor-save"))
        button("schedule-preset-weekends").tap()
        XCTAssertEqual(button("schedule-day-5").value as? String, "Selected")
        XCTAssertEqual(button("schedule-day-0").value as? String, "Not selected")
        capture("schedule-editor")
        button("schedule-editor-save").tap()
        button("schedule-filter-5").tap()
        wait(button("schedule-edit-new-1"))
        button("schedule-add").tap()
        wait(button("schedule-editor-cancel"))
        button("schedule-editor-cancel").tap()
        wait(button("schedule-add"))
        XCTAssertFalse(button("schedule-edit-new-2").exists)
    }

    func testNoDaysDisablesSaveAndDayFilterPrefillsEditor() {
        launch(["-emptySchedulePreview"])
        wait(button("schedule-filter-0"))
        button("schedule-filter-0").tap()
        button("schedule-add").tap()
        wait(button("schedule-day-0"))
        XCTAssertEqual(button("schedule-day-0").value as? String, "Selected")
        XCTAssertEqual(button("schedule-day-1").value as? String, "Not selected")
        button("schedule-day-0").tap()
        XCTAssertFalse(button("schedule-editor-save").isEnabled)
        button("schedule-preset-every-day").tap()
        XCTAssertTrue(button("schedule-editor-save").isEnabled)
    }

    func testEditPreservesMidnightAndEnabledState() {
        launch()
        wait(button("schedule-edit-sports"))
        button("schedule-edit-sports").tap()
        wait(button("schedule-editor-save"))
        XCTAssertTrue(app.staticTexts["schedule-time-summary"].label.contains("6:00 PM – Midnight"))
        XCTAssertEqual(button("schedule-day-5").value as? String, "Not selected")
        capture("schedule-midnight-editor")
        app.switches["schedule-editor-enabled"].coordinate(withNormalizedOffset: CGVector(dx: 0.94, dy: 0.5)).tap()
        XCTAssertEqual(app.switches["schedule-editor-enabled"].value as? String, "0")
        button("schedule-editor-save").tap()
        let block = button("schedule-edit-sports")
        wait(block)
        expectation(for: NSPredicate(format: "value == %@", "Disabled"), evaluatedWith: block)
        waitForExpectations(timeout: 8)
        XCTAssertEqual(block.value as? String, "Disabled")
        button("schedule-edit-sports").tap()
        wait(button("schedule-editor-save"))
        XCTAssertEqual(app.switches["schedule-editor-enabled"].value as? String, "0")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Midnight")).firstMatch.exists)
    }

    func testDeleteRequiresConfirmation() {
        launch()
        let row = button("schedule-edit-weather")
        wait(row)
        row.press(forDuration: 0.8)
        app.buttons["Delete schedule"].firstMatch.tap()
        wait(app.alerts.buttons["Delete schedule"])
        app.buttons["Cancel"].firstMatch.tap()
        XCTAssertTrue(row.exists)
        row.press(forDuration: 0.8)
        app.buttons["Delete schedule"].firstMatch.tap()
        app.alerts.buttons["Delete schedule"].tap()
        let gone = NSPredicate(format: "exists == false")
        expectation(for: gone, evaluatedWith: row)
        waitForExpectations(timeout: 8)
    }

    func testServerValidationKeepsEditorOpen() {
        launch(["-scheduleWriteFailure"])
        wait(button("schedule-add"))
        button("schedule-add").tap()
        wait(button("schedule-editor-save"))
        button("schedule-editor-save").tap()
        wait(app.staticTexts["schedule-editor-error"])
        XCTAssertTrue(button("schedule-editor-save").exists)
        XCTAssertTrue(app.staticTexts["enabled schedule blocks cannot overlap"].exists)
        capture("schedule-validation-error")
    }

    func testConnectionErrorRetry() {
        launch(["-scheduleReadFailure"])
        wait(app.buttons["Try again"])
        app.buttons["Try again"].tap()
        wait(button("schedule-edit-weather"))
        XCTAssertFalse(app.staticTexts["schedule-error"].exists)
    }

    func testCalendarCreateFromEmptyHour() {
        launch()
        wait(button("schedule-edit-weather"))
        capture("calendar-weekday")
        button("schedule-filter-5").tap()
        wait(button("schedule-edit-music"))
        capture("calendar-weekend")
        button("schedule-add-hour-15").tap()
        wait(button("schedule-editor-save"))
        XCTAssertTrue(app.staticTexts["schedule-time-summary"].label.contains("3:00 PM – 4:00 PM"))
        app.descendants(matching: .any)["schedule-editor-mode"].firstMatch.tap()
        let weather = app.buttons["Weather"].firstMatch
        wait(weather)
        capture("calendar-mode-picker")
        weather.tap()
        wait(button("schedule-editor-save"))
        capture("calendar-editor")
        button("schedule-editor-save").tap()
        wait(button("schedule-edit-new-1"))
        XCTAssertTrue(button("schedule-edit-new-1").label.contains("Weather"))
        XCTAssertTrue(button("schedule-edit-new-1").label.contains("3:00 PM – 4:00 PM"))
        capture("calendar-new-block")
    }

    func testLiveRuleAndManualOverride() {
        launch(["-emptySchedulePreview"])
        wait(button("schedule-rules"))
        button("schedule-rules").tap()
        wait(button("schedule-condition-add"))
        button("schedule-condition-add").tap()
        wait(button("schedule-condition-save"))
        capture("schedule-live-rule")
        button("schedule-condition-save").tap()
        wait(button("schedule-rules"))
        button("schedule-rules").tap()
        wait(button("schedule-condition-new-1"))
        button("schedule-condition-new-1").tap()
        wait(button("schedule-condition-save"))
        app.buttons["Cancel"].firstMatch.tap()
        let manual = button("schedule-override")
        if !manual.isHittable { app.swipeUp() }
        manual.tap()
        let resumed = NSPredicate(format: "label == %@", "Resume schedule")
        expectation(for: resumed, evaluatedWith: manual)
        waitForExpectations(timeout: 8)
        manual.tap()
        expectation(for: NSPredicate(format: "label == %@", "Pause schedule"), evaluatedWith: manual)
        waitForExpectations(timeout: 8)
    }
}
