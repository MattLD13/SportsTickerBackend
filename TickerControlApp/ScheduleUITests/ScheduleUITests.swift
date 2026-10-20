import XCTest

final class ScheduleUITests: XCTestCase {
    private var app: XCUIApplication!

    private func launch(_ arguments: [String] = []) {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-schedulePreview"] + arguments
        app.launch()
        wait(app.segmentedControls["schedule-view-picker"])
        app.segmentedControls["schedule-view-picker"].buttons["Day"].tap()
    }

    private func button(_ id: String) -> XCUIElement {
        if id.hasPrefix("schedule-edit-") || id.hasPrefix("schedule-add-hour-") {
            return app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", id + "-day-")).firstMatch
        }
        return app.buttons[id]
    }

    private func wait(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.waitForExistence(timeout: 8), file: file, line: line)
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func drag(_ element: XCUIElement, dx: CGFloat = 0, dy: CGFloat) {
        let start = element.coordinate(withNormalizedOffset: CGVector(dx: 0.4, dy: 0.35))
        start.press(forDuration: 0.6, thenDragTo: start.withOffset(CGVector(dx: dx, dy: dy)),
                    withVelocity: .slow, thenHoldForDuration: 0.2)
    }

    private func expectTime(_ element: XCUIElement, _ value: String) {
        expectation(for: NSPredicate(format: "label CONTAINS %@", value), evaluatedWith: element)
        waitForExpectations(timeout: 8)
    }

    private func openBlock(_ element: XCUIElement) {
        element.tap()
        wait(button("schedule-selected-edit"))
        button("schedule-selected-edit").tap()
    }

    func testDirectMoveSnapsAndPersists() {
        launch(["-singleDaySchedulePreview"])
        let weather = button("schedule-edit-weather")
        wait(weather)
        drag(weather, dy: -18)
        expectTime(weather, "7:45 AM – 8:45 AM")
        capture("direct-move")
        openBlock(weather)
        wait(button("schedule-editor-save"))
        capture("direct-move-reopened")
        XCTAssertTrue(app.staticTexts["schedule-time-summary"].label.contains("7:45 AM – 8:45 AM"),
                      app.staticTexts["schedule-time-summary"].label)
    }

    func testDirectResizeBothEdges() {
        launch(["-singleDaySchedulePreview"])
        let weather = button("schedule-edit-weather")
        wait(weather)
        weather.tap()
        let start = app.descendants(matching: .any)["schedule-resize-start-weather-day-0"].firstMatch
        wait(start)
        drag(start, dy: -36)
        expectTime(weather, "7:30 AM – 9:00 AM")
        let end = app.descendants(matching: .any)["schedule-resize-end-weather-day-0"].firstMatch
        wait(end)
        drag(end, dy: -36)
        expectTime(weather, "7:30 AM – 8:30 AM")
        capture("direct-resize")
    }

    func testDirectMoveAcrossDayColumns() {
        launch(["-singleDaySchedulePreview"])
        app.segmentedControls["schedule-view-picker"].buttons["3 days"].tap()
        let monday = app.buttons["schedule-edit-weather-day-0"]
        wait(monday)
        capture("three-day-calendar")
        drag(monday, dx: monday.frame.width + 4, dy: -18)
        let tuesday = app.buttons["schedule-edit-weather-day-1"]
        wait(tuesday)
        expectTime(tuesday, "7:45 AM – 8:45 AM")
        XCTAssertFalse(monday.exists)
        capture("direct-day-move")
    }

    func testDirectRepeatChangeCanBeCancelled() {
        launch()
        let weather = button("schedule-edit-weather")
        wait(weather)
        drag(weather, dy: -18)
        wait(app.alerts.buttons["Apply to all repeat days"])
        app.alerts.buttons["Cancel"].tap()
        expectTime(weather, "8:00 AM – 9:00 AM")
        XCTAssertFalse(app.staticTexts["schedule-error"].exists)
    }

    func testDirectRepeatChangeUpdatesAllRepeatDays() {
        launch()
        let weather = button("schedule-edit-weather")
        wait(weather)
        drag(weather, dy: -18)
        wait(app.alerts.buttons["Apply to all repeat days"])
        app.alerts.buttons["Apply to all repeat days"].tap()
        expectTime(weather, "7:45 AM – 8:45 AM")
        button("schedule-filter-1").tap()
        expectTime(button("schedule-edit-weather"), "7:45 AM – 8:45 AM")
    }

    func testDirectOverlapPreservesSavedTimes() {
        launch(["-singleDaySchedulePreview"])
        let weather = button("schedule-edit-weather")
        wait(weather)
        drag(weather, dy: 18)
        wait(app.staticTexts["schedule-error"])
        expectTime(weather, "8:00 AM – 9:00 AM")
        XCTAssertTrue(app.staticTexts["schedule-error"].label.contains("cannot overlap"))
    }

    func testDirectFailedSaveRestoresOriginalBlock() {
        launch(["-singleDaySchedulePreview", "-scheduleWriteFailure"])
        let weather = button("schedule-edit-weather")
        wait(weather)
        drag(weather, dy: -18)
        wait(app.staticTexts["schedule-error"])
        expectTime(weather, "8:00 AM – 9:00 AM")
        capture("direct-rejected-save")
    }

    func testDirectDrawPrefillsQuarterHourRange() {
        launch(["-emptySchedulePreview"])
        let hour = button("schedule-add-hour-10")
        wait(hour)
        let origin = hour.coordinate(withNormalizedOffset: CGVector(dx: 0.4, dy: 0.05))
        origin.press(forDuration: 0.6, thenDragTo: origin.withOffset(CGVector(dx: 0, dy: 108)),
                     withVelocity: .slow, thenHoldForDuration: 0.2)
        wait(button("schedule-editor-save"))
        XCTAssertTrue(app.staticTexts["schedule-time-summary"].label.contains("10:00 AM – 11:30 AM"))
        capture("direct-draw-editor")
        button("schedule-editor-cancel").tap()
        XCTAssertFalse(button("schedule-edit-new-1").exists)
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
        wait(button("schedule-add"))
        button("schedule-add").tap()
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
        openBlock(button("schedule-edit-sports"))
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
        openBlock(button("schedule-edit-sports"))
        wait(button("schedule-editor-save"))
        XCTAssertEqual(app.switches["schedule-editor-enabled"].value as? String, "0")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Midnight")).firstMatch.exists)
    }

    func testDeleteRequiresConfirmation() {
        launch()
        let row = button("schedule-edit-weather")
        wait(row)
        row.tap()
        button("schedule-selected-more").tap()
        app.buttons["Delete schedule"].firstMatch.tap()
        wait(app.alerts.buttons["Delete schedule"])
        app.buttons["Cancel"].firstMatch.tap()
        XCTAssertTrue(row.exists)
        button("schedule-selected-more").tap()
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
        XCTAssertTrue(app.staticTexts["schedule-time-summary"].label.contains("3:30 PM – 4:30 PM"))
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
        XCTAssertTrue(button("schedule-edit-new-1").label.contains("3:30 PM – 4:30 PM"))
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
