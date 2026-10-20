import Foundation

struct TickerScheduleBlock: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let ticker_id: String
    let days_of_week: [Int]
    let day_names: [String]
    let start_minute: Int
    let end_minute: Int
    let mode: String
    let sports_filter: String?
    let enabled: Bool
    let created_at: Double
    let updated_at: Double

    var dayLabel: String {
        SchedulePresentation.repeatLabel(days_of_week)
    }

    var timeLabel: String {
        "\(SchedulePresentation.clock(start_minute)) – \(SchedulePresentation.clock(end_minute))"
    }

    func rescheduled(days: [Int], start: Int, end: Int) -> Self {
        Self(id: id, ticker_id: ticker_id, days_of_week: days, day_names: [],
             start_minute: start, end_minute: end, mode: mode, sports_filter: sports_filter,
             enabled: enabled, created_at: created_at, updated_at: updated_at)
    }
}

enum ScheduleCalendarEdit: String { case move, start, end }

enum ScheduleCalendarInteraction {
    static func snap(_ minutes: Double) -> Int { Int((minutes / 15).rounded()) * 15 }

    static func days(start: Int, count: Int) -> [Int] { (0..<count).map { (start + $0) % 7 } }

    static func columnOffset(translation: Double, width: Double, column: Int, count: Int) -> Int {
        let offset = Int((translation / max(1, width)).rounded())
        return max(-column, min(count - 1 - column, offset))
    }

    static func hasChanges(_ original: TickerScheduleBlock, _ proposed: TickerScheduleBlock) -> Bool {
        original.start_minute != proposed.start_minute || original.end_minute != proposed.end_minute ||
            Set(original.days_of_week) != Set(proposed.days_of_week)
    }

    static func drawnRange(first: Double, last: Double) -> (start: Int, end: Int) {
        let first = max(0, min(1425, snap(first)))
        let last = max(0, min(1440, snap(last)))
        let start = min(first, last)
        return (start, max(start + 15, max(first, last)))
    }

    static func applying(_ edit: ScheduleCalendarEdit, to block: TickerScheduleBlock,
                         minutes: Double, dayOffset: Int = 0) -> TickerScheduleBlock {
        let delta = snap(minutes)
        var start = block.start_minute
        var end = block.end_minute
        var days = block.days_of_week
        let minimum = min(15, end - start)
        switch edit {
        case .move:
            start = max(0, min(1440 - (end - start), start + delta))
            end = start + block.end_minute - block.start_minute
            days = days.map { (($0 + dayOffset) % 7 + 7) % 7 }.sorted()
        case .start: start = max(0, min(end - minimum, start + delta))
        case .end: end = min(1440, max(start + minimum, end + delta))
        }
        return block.rescheduled(days: days, start: start, end: end)
    }
}

struct TickerScheduleCondition: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let ticker_id: String
    let kind: String
    let threshold: Int
    let `operator`: String
    let when_mode: String
    let action_sports_filter: String
    let ignore_pinned: Bool
    let enabled: Bool
    let created_at: Double
    let updated_at: Double

    var label: String {
        let comparison = `operator` == "gte" ? "At least" : "More than"
        return "\(comparison) \(threshold) games live"
    }
}

enum SchedulePresentation {
    static let weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    static func repeatLabel(_ days: [Int]) -> String {
        let selected = Set(days)
        if selected == Set(0...6) { return "Every day" }
        if selected == Set(0...4) { return "Weekdays" }
        if selected == Set(5...6) { return "Weekends" }
        if selected.isEmpty { return "Choose days" }
        return selected.sorted().filter { weekdays.indices.contains($0) }
            .map { String(weekdays[$0].prefix(3)) }.joined(separator: ", ")
    }

    static func clock(_ minute: Int) -> String {
        if minute == 1440 { return "Midnight" }
        let hour = minute / 60
        let suffix = hour >= 12 ? "PM" : "AM"
        let displayHour = hour % 12 == 0 ? 12 : hour % 12
        return String(format: "%d:%02d %@", displayHour, minute % 60, suffix)
    }

    static func hourLabel(_ hour: Int) -> String {
        "\(hour % 12 == 0 ? 12 : hour % 12) \(hour >= 12 ? "PM" : "AM")"
    }

    static func calendarPlacements(_ blocks: [TickerScheduleBlock]) -> [ScheduleCalendarPlacement] {
        let ordered = self.blocks(blocks, on: nil)
        var result: [ScheduleCalendarPlacement] = []
        var groupStart = 0
        var groupEnd = -1
        var laneEnds: [Int] = []
        func finishGroup() {
            for index in groupStart..<result.count { result[index].columns = laneEnds.count }
        }
        for block in ordered {
            if block.start_minute >= groupEnd {
                finishGroup()
                groupStart = result.count
                laneEnds = []
            }
            let visualEnd = max(block.end_minute, block.start_minute + 45)
            let column = laneEnds.firstIndex { $0 <= block.start_minute } ?? laneEnds.count
            if column == laneEnds.count { laneEnds.append(visualEnd) } else { laneEnds[column] = visualEnd }
            result.append(ScheduleCalendarPlacement(block: block, column: column, columns: 1, visualEnd: visualEnd))
            groupEnd = max(groupEnd, visualEnd)
        }
        finishGroup()
        return result
    }

    static func modeName(_ mode: String) -> String {
        switch mode {
        case "sports": return "Sports"
        case "stock": return "Stocks"
        case "music": return "Music"
        case "weather": return "Weather"
        case "flights": return "Flight tracking"
        case "airports": return "Airport board"
        case "clock": return "Clock"
        default: return mode.capitalized
        }
    }

    static func blocks(_ blocks: [TickerScheduleBlock], on day: Int?) -> [TickerScheduleBlock] {
        blocks.filter { block in day.map { block.days_of_week.contains($0) } ?? true }.sorted {
            if $0.start_minute != $1.start_minute { return $0.start_minute < $1.start_minute }
            if $0.end_minute != $1.end_minute { return $0.end_minute < $1.end_minute }
            return $0.id < $1.id
        }
    }

    static func validTimeRange(start: Int, end: Int) -> Bool {
        start >= 0 && start < 1440 && end > start && end <= 1440
    }

    static func timeDate(minute: Int, timeZone: TimeZone) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        // A fixed winter date avoids offset arithmetic across a daylight-saving transition.
        let components = DateComponents(year: 2001, month: 1, day: minute == 1440 ? 16 : 15,
                                        hour: (minute % 1440) / 60, minute: minute % 60)
        return calendar.date(from: components)!
    }

    static func minute(_ date: Date, timeZone: TimeZone, endOfDay: Bool = false) -> Int {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let value = calendar.component(.hour, from: date) * 60 + calendar.component(.minute, from: date)
        return endOfDay && value == 0 ? 1440 : value
    }
}

struct ScheduleCalendarPlacement: Identifiable {
    let block: TickerScheduleBlock
    let column: Int
    var columns: Int
    let visualEnd: Int
    var id: String { block.id }
}

struct TickerScheduleDay: Codable, Hashable, Sendable {
    let day_of_week: Int
    let name: String
    let blocks: [TickerScheduleBlock]
}

struct TickerScheduleStatus: Codable, Hashable, Sendable {
    let active: Bool
    let override: Bool
    let override_expires_at: Double?
    let source: String
    let mode: String
    let sports_filter: String
    let sports_presentation: String
    let live_games: Int
    let timezone: String
    let local_day: String
    let day_of_week: Int
    let local_time: String
    let rule_id: String?
    let condition_id: String?
    let scheduled_mode: String?
    let scheduled_sports_filter: String?

    enum CodingKeys: String, CodingKey {
        case active, override, override_expires_at, source, mode, sports_filter
        case sports_presentation, live_games, timezone, local_day, day_of_week, local_time
        case rule_id, condition_id, scheduled_mode, scheduled_sports_filter
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        active = try container.decodeIfPresent(Bool.self, forKey: .active) ?? false
        override = try container.decodeIfPresent(Bool.self, forKey: .override) ?? false
        override_expires_at = try container.decodeIfPresent(Double.self, forKey: .override_expires_at)
        source = try container.decodeIfPresent(String.self, forKey: .source) ?? "base"
        mode = try container.decodeIfPresent(String.self, forKey: .mode) ?? "sports"
        sports_filter = try container.decodeIfPresent(String.self, forKey: .sports_filter) ?? "all"
        sports_presentation = try container.decodeIfPresent(String.self, forKey: .sports_presentation) ?? "rotation"
        live_games = try container.decodeIfPresent(Int.self, forKey: .live_games) ?? 0
        timezone = try container.decodeIfPresent(String.self, forKey: .timezone) ?? ""
        local_day = try container.decodeIfPresent(String.self, forKey: .local_day) ?? ""
        day_of_week = try container.decodeIfPresent(Int.self, forKey: .day_of_week) ?? 0
        local_time = try container.decodeIfPresent(String.self, forKey: .local_time) ?? ""
        rule_id = try container.decodeIfPresent(String.self, forKey: .rule_id)
        condition_id = try container.decodeIfPresent(String.self, forKey: .condition_id)
        scheduled_mode = try container.decodeIfPresent(String.self, forKey: .scheduled_mode)
        scheduled_sports_filter = try container.decodeIfPresent(String.self, forKey: .scheduled_sports_filter)
    }
}

struct TickerScheduleResponse: Codable, Hashable, Sendable {
    let api_version: String
    let ticker_id: String
    let timezone: String
    let days: [TickerScheduleDay]
    let blocks: [TickerScheduleBlock]
    let conditions: [TickerScheduleCondition]
    let live_games: Int
    let effective: TickerScheduleStatus
}

struct TickerScheduleMutationResponse: Decodable, Sendable {}

enum TickerScheduleRequestError: LocalizedError, Sendable {
    case authorization
    case invalidResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .authorization:
            return "Pair this ticker before editing its schedule."
        case .invalidResponse:
            return "The ticker returned an invalid schedule response."
        case .server(let message):
            return message
        }
    }
}
