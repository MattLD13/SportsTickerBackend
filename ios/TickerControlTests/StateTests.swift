import Foundation
import Testing
@testable import TickerControlCore

@MainActor
struct StateTests {
    @Test func pollingIntervalsEditingAndBurst() {
        let start = Date(timeIntervalSince1970: 1_000)
        for (mode, interval) in [("sports", 1.0), ("music", 1), ("flights", 60), ("airports", 60), ("stock", 30), ("weather", 600), ("clock", 600)] {
            var policy = PollingPolicy()
            func polls(after seconds: TimeInterval, isEditing: Bool = false) -> Bool {
                policy.shouldPoll(at: start.addingTimeInterval(seconds), mode: mode, isEditing: isEditing)
            }
            #expect(polls(after: 0))
            #expect(!polls(after: interval - 0.1))
            #expect(!polls(after: interval, isEditing: true))
            #expect(polls(after: interval))
            policy.beginBurst(at: start.addingTimeInterval(interval))
            #expect(polls(after: interval + 0.5))
            if interval > 30 {
                #expect(!polls(after: interval + 30))
            }
        }
    }

    private func data(_ items: [[String: Any]], mode: String = "sports") throws -> DisplayData {
        try JSONDecoder().decode(DisplayData.self, from: JSONSerialization.data(withJSONObject: Harness.data(mode: mode, items: items)))
    }

    @Test func feedOrderPutsThePinnedGameFirstThenShownThenLive() throws {
        let display = try data([Harness.game("a", shown: false), Harness.game("b"), Harness.game("c", state: "in"), Harness.game("d")])
        #expect(FeedOrder.items(display, pinnedID: nil).map(\.id) == ["c", "b", "d", "a"])
        #expect(FeedOrder.items(display, pinnedID: "a").map(\.id) == ["a", "c", "b", "d"])
        let weather = try data([Harness.game("a", shown: false), Harness.game("b")], mode: "weather")
        #expect(FeedOrder.items(weather, pinnedID: nil).map(\.id) == ["b"], "outside Sports mode the feed lists shown items only")
    }

    @Test func sportsFixturePinnedGameComesFirst() throws {
        let display = try JSONDecoder().decode(DisplayData.self, from: fixture("display/sports"))
        let last = try #require(display.items.last)
        #expect(FeedOrder.items(display, pinnedID: last.pinID).first?.id == last.id)
    }

    @Test func feedSectionsSeparateTheCardTypes() throws {
        let json = """
        {"settings":{},"meta":{},"content":{"sports":[{"id":"g","family":"sports","kind":"scoreboard","is_shown":true,"data":{}}],
         "music":[{"id":"m","family":"music","kind":"spotify","is_shown":true,"data":{"type":"music"}}],
         "clock":[{"id":"c","family":"clock","kind":"clock","is_shown":true,"data":{"sport":"clock"}}]}}
        """
        let sections = FeedSections(try JSONDecoder().decode(DisplayData.self, from: Data(json.utf8)).items)
        #expect(sections.games.map(\.id) == ["g", "c"])
        #expect(sections.music.map(\.id) == ["m"])
    }

    private func leagues(_ json: String) throws -> [League] {
        try JSONDecoder().decode(LeagueCatalog.self, from: Data(json.utf8)).leagues
    }

    @Test func leagueGroupsUseConferenceMetadataInCatalogOrder() throws {
        let groups = LeagueGroup.groups(try leagues("""
        {"leagues":[{"id":"nfl","label":"NFL","type":"sport"},{"id":"ncf_fbs","label":"FBS","type":"sport"},
         {"id":"future-choice-A","label":"Shared","type":"sport","conference_parent":"ncf_fbs"},
         {"id":"ncf_fcs","label":"FCS","type":"sport"},{"id":"ncf_fcs:4","label":"Shared","type":"sport","conference_parent":"ncf_fcs"},
         {"id":"ncf_fbs:999","label":"New","type":"sport","conference_parent":"ncf_fcs"},{"id":"stock-tech","label":"Tech","type":"stock"}]}
        """))
        #expect(groups.map(\.id) == ["nfl", "ncf_fbs", "ncf_fcs"])
        #expect(!groups[0].hasConferences)
        #expect(groups[1].conferences.map(\.id) == ["future-choice-A"])
        #expect(groups[2].conferences.map(\.id) == ["ncf_fcs:4", "ncf_fbs:999"])
        #expect(groups[1].hasConferences && groups[2].hasConferences)
        let empty = LeagueGroup.groups(try leagues(#"{"leagues":[{"id":"ncf_fbs","label":"FBS","type":"sport"}]}"#))
        #expect(empty[0].hasConferences && empty[0].conferences.isEmpty)
        let future = LeagueGroup.groups(try leagues("""
        {"leagues":[{"id":"future-parent","label":"Future","type":"sport"},{"id":"x","label":"Conf","type":"sport","conference_parent":"future-parent"}]}
        """))
        #expect(future.count == 1)
        #expect(future[0].hasConferences)
    }

    private func block(_ id: String, days: [Int], start: Int, end: Int? = nil, enabled: Bool = true) -> ScheduleBlock {
        ScheduleBlock(id: id, daysOfWeek: days, startMinute: start, endMinute: end ?? start + 60, mode: "sports", sportsFilter: "all", enabled: enabled)
    }

    @Test func calendarPlacementsReserveSpaceForShortAndOverlappingBlocks() {
        let short = SchedulePresentation.calendarPlacements([block("short", days: [0], start: 480, end: 495), block("next", days: [0], start: 525)],
                                                            minimumMinutes: 60)
        #expect(short.map(\.columns) == [2, 2])
        #expect(short[0].visualEnd == 540)
        let overlap = SchedulePresentation.calendarPlacements([block("a", days: [0], start: 480), block("b", days: [0], start: 510),
                                                               block("later", days: [0], start: 800)])
        #expect(overlap.map(\.column) == [0, 1, 0])
        #expect(overlap.map(\.columns) == [2, 2, 1])
        #expect(overlap.map(\.visualEnd) == [540, 570, 860])
        #expect(SchedulePresentation.calendarPlacements([]).isEmpty)
    }

    @Test func calendarScopesAndColumns() {
        #expect(ScheduleCalendarScope.weekdays.columns(start: 3, count: 3)[0].days == [0, 1, 2, 3, 4])
        #expect(ScheduleCalendarScope.weekends.columns(start: 3, count: 3)[0].days == [5, 6])
        #expect(ScheduleCalendarScope.days.columns(start: 6, count: 3).map(\.days) == [[6], [0], [1]])
        let values = [block("monday", days: [0], start: 480), block("routine", days: Array(0...4), start: 540), block("weekend", days: [5, 6], start: 600)]
        let weekdays = ScheduleCalendarScope.weekdays.columns(start: 0, count: 3)[0].blocks(values)
        #expect(weekdays.map(\.id) == ["monday", "routine"])
        #expect(weekdays[0].dayLabel == "Mon")
        #expect(ScheduleCalendarColumn.minute(hour: 8, fraction: 0.3) == 495)
        #expect(ScheduleCalendarColumn.minute(hour: 23, fraction: 1) == 1425)
    }

    @Test func scheduleLabelsAndRanges() throws {
        #expect(SchedulePresentation.repeatLabel(Array(0...6)) == "Every day")
        #expect(SchedulePresentation.repeatLabel([4, 0, 4]) == "Mon, Fri")
        #expect(SchedulePresentation.repeatLabel([]) == "Choose days")
        #expect(SchedulePresentation.clock(0) == "12:00 AM")
        #expect(SchedulePresentation.clock(720) == "12:00 PM")
        #expect(SchedulePresentation.clock(1440) == "Midnight")
        #expect(SchedulePresentation.validTimeRange(start: 0, end: 1440))
        for pair in [(-1, 60), (1440, 1440), (480, 480), (900, 480), (0, 1441)] {
            #expect(!(SchedulePresentation.validTimeRange(start: pair.0, end: pair.1)))
        }
        #expect(DisplayMode.all.map(SchedulePresentation.modeName) == ["Sports", "Stocks", "Weather", "Music", "Flight tracking", "Airport board", "Clock"])
        for name in ["America/New_York", "Asia/Kolkata", "Pacific/Auckland"] {
            let zone = try #require(TimeZone(identifier: name))
            for minute in [0, 480, 1439, 1440] {
                #expect((SchedulePresentation.minute(SchedulePresentation.timeDate(minute: minute, timeZone: zone), timeZone: zone,
                                                           endOfDay: minute == 1440)) == minute)
            }
        }
        let blocks = [block("late", days: [0], start: 1080), block("weekend", days: [5], start: 480), block("morning", days: [0], start: 480, enabled: false)]
        #expect(SchedulePresentation.blocks(blocks, on: 0).map(\.id) == ["morning", "late"])
    }
}
