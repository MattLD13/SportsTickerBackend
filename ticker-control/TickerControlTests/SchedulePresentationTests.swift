import Foundation
import XCTest
@testable import TickerControlState

final class SchedulePresentationTests: XCTestCase {
    func testGroupedLabelsReserveSpaceWithoutHidingOverlappingBlocks() {
        let first = TickerScheduleBlock(id: "short", ticker_id: "preview", days_of_week: [0], day_names: [],
            start_minute: 480, end_minute: 495, mode: "weather", sports_filter: nil,
            enabled: true, created_at: 0, updated_at: 0)
        let positions = SchedulePresentation.calendarPlacements([first, block("next", days: [0], start: 525)], minimumMinutes: 60)
        XCTAssertEqual(positions.map(\.columns), [2, 2])
        XCTAssertEqual(positions[0].visualEnd, 540)
        XCTAssertEqual(first.end_minute, 495)
    }
    func testWeekdayAndWeekendScopesSelectTheirActualDays() {
        XCTAssertEqual(ScheduleCalendarScope.weekdays.columns(start: 3, count: 3)[0].days, [0, 1, 2, 3, 4])
        XCTAssertEqual(ScheduleCalendarScope.weekends.columns(start: 3, count: 3)[0].days, [5, 6])
        XCTAssertEqual(ScheduleCalendarScope.days.columns(start: 6, count: 3).map(\.days), [[6], [0], [1]])
    }

    func testGroupedCalendarKeepsPartialDaysExplicitAndDoesNotDuplicateBlocks() {
        let values = [block("monday", days: [0], start: 480), block("routine", days: Array(0...4), start: 540),
                      block("weekend", days: [5, 6], start: 600)]
        let weekdays = ScheduleCalendarScope.weekdays.columns(start: 0, count: 3)[0].blocks(values)
        XCTAssertEqual(weekdays.map(\.id), ["monday", "routine"])
        XCTAssertEqual(weekdays[0].dayLabel, "Mon")
        let weekends = ScheduleCalendarScope.weekends.columns(start: 0, count: 3)[0].blocks(values)
        XCTAssertEqual(weekends.map(\.id), ["weekend"])
    }

    func testEmptySpaceUsesQuarterHourPlacement() {
        XCTAssertEqual(ScheduleCalendarColumn.minute(hour: 8, fraction: 0.1), 480)
        XCTAssertEqual(ScheduleCalendarColumn.minute(hour: 8, fraction: 0.3), 495)
        XCTAssertEqual(ScheduleCalendarColumn.minute(hour: 8, fraction: 0.6), 510)
        XCTAssertEqual(ScheduleCalendarColumn.minute(hour: 23, fraction: 1), 1425)
    }
    func testRepeatPresetsUseNumericContractDays() {
        XCTAssertEqual(SchedulePresentation.repeatLabel(Array(0...6)), "Every day")
        XCTAssertEqual(SchedulePresentation.repeatLabel(Array(0...4)), "Weekdays")
        XCTAssertEqual(SchedulePresentation.repeatLabel([5, 6]), "Weekends")
        XCTAssertEqual(SchedulePresentation.repeatLabel([4, 0, 4]), "Mon, Fri")
        XCTAssertEqual(SchedulePresentation.repeatLabel([]), "Choose days")
    }

    func testClockLabelsDistinguishNoonAndDayEnd() {
        XCTAssertEqual(SchedulePresentation.clock(0), "12:00 AM")
        XCTAssertEqual(SchedulePresentation.clock(480), "8:00 AM")
        XCTAssertEqual(SchedulePresentation.clock(720), "12:00 PM")
        XCTAssertEqual(SchedulePresentation.clock(1439), "11:59 PM")
        XCTAssertEqual(SchedulePresentation.clock(1440), "Midnight")
    }

    func testRangeRejectsOvernightAndEmptyIntervals() {
        XCTAssertTrue(SchedulePresentation.validTimeRange(start: 0, end: 1440))
        XCTAssertTrue(SchedulePresentation.validTimeRange(start: 1439, end: 1440))
        for pair in [(-1, 60), (1440, 1440), (480, 480), (900, 480), (0, 1441)] {
            XCTAssertFalse(SchedulePresentation.validTimeRange(start: pair.0, end: pair.1))
        }
    }

    func testTimePickerRoundTripsInTickerTimeZone() throws {
        for name in ["America/New_York", "America/Los_Angeles", "Asia/Kolkata", "Pacific/Auckland"] {
            let zone = try XCTUnwrap(TimeZone(identifier: name))
            for minute in [0, 60, 480, 720, 1439, 1440] {
                let date = SchedulePresentation.timeDate(minute: minute, timeZone: zone)
                XCTAssertEqual(SchedulePresentation.minute(date, timeZone: zone, endOfDay: minute == 1440), minute)
            }
        }
    }

    func testBlocksFilterThenSortWithoutDroppingDisabledSchedules() {
        let blocks = [block("late", days: [0], start: 1080), block("weekend", days: [5], start: 480),
                      block("morning", days: [0], start: 480, enabled: false)]
        XCTAssertEqual(SchedulePresentation.blocks(blocks, on: 0).map(\.id), ["morning", "late"])
        XCTAssertEqual(SchedulePresentation.blocks(blocks, on: 6), [])
        XCTAssertEqual(SchedulePresentation.blocks(blocks, on: nil).count, 3)
    }

    func testModeLabelsCoverEveryV2Mode() {
        let modes = ["sports", "stock", "weather", "music", "flights", "airports", "clock"]
        XCTAssertEqual(modes.map(SchedulePresentation.modeName),
                       ["Sports", "Stocks", "Weather", "Music", "Flight tracking", "Airport board", "Clock"])
    }

    func testCalendarGroupsOverlappingVisualIntervalsIntoColumns() {
        let blocks = [block("a", days: [0], start: 480), block("b", days: [0], start: 510),
                      block("later", days: [0], start: 800)]
        let positions = SchedulePresentation.calendarPlacements(blocks)
        XCTAssertEqual(positions.map(\.column), [0, 1, 0])
        XCTAssertEqual(positions.map(\.columns), [2, 2, 1])
        XCTAssertEqual(positions.map(\.visualEnd), [540, 570, 860])
    }

    func testShortCalendarBlocksRemainVisibleWithoutCoveringAdjacentBlocks() {
        let a = TickerScheduleBlock(id: "short", ticker_id: "preview", days_of_week: [0], day_names: [],
            start_minute: 480, end_minute: 485, mode: "clock", sports_filter: nil,
            enabled: true, created_at: 0, updated_at: 0)
        let positions = SchedulePresentation.calendarPlacements([a, block("next", days: [0], start: 485)])
        XCTAssertEqual(positions.map(\.columns), [2, 2])
        XCTAssertEqual(positions[0].visualEnd, 525)
        XCTAssertEqual(a.end_minute, 485)
        XCTAssertEqual(SchedulePresentation.calendarPlacements([]).count, 0)
    }

    private func block(_ id: String, days: [Int], start: Int, enabled: Bool = true) -> TickerScheduleBlock {
        TickerScheduleBlock(id: id, ticker_id: "preview", days_of_week: days, day_names: ["Untrusted label"],
                            start_minute: start, end_minute: start + 60, mode: "sports", sports_filter: "all",
                            enabled: enabled, created_at: 0, updated_at: 0)
    }
}
