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

enum ScheduleCalendarScope: String, CaseIterable {
    case weekdays = "Weekdays"
    case weekends = "Weekends"
    case days = "By day"

    func columns(start: Int, count: Int) -> [ScheduleCalendarColumn] {
        switch self {
        case .weekdays: return [ScheduleCalendarColumn(id: "weekdays", title: "Monday – Friday", days: Array(0...4))]
        case .weekends: return [ScheduleCalendarColumn(id: "weekends", title: "Saturday – Sunday", days: [5, 6])]
        case .days:
            return (0..<count).map {
                let day = (start + $0) % 7
                return ScheduleCalendarColumn(id: "day-\(day)", title: SchedulePresentation.weekdays[day], days: [day])
            }
        }
    }
}

struct ScheduleCalendarColumn: Identifiable {
    let id: String
    let title: String
    let days: [Int]

    func blocks(_ values: [TickerScheduleBlock]) -> [TickerScheduleBlock] {
        let selected = Set(days)
        return SchedulePresentation.blocks(values.filter { !selected.isDisjoint(with: $0.days_of_week) }, on: nil)
    }

    static func minute(hour: Int, fraction: Double) -> Int {
        let quarter = max(0, min(3, Int(fraction * 4)))
        return min(1425, hour * 60 + quarter * 15)
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

    static func calendarPlacements(_ blocks: [TickerScheduleBlock], minimumMinutes: Int = 45) -> [ScheduleCalendarPlacement] {
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
            let visualEnd = max(block.end_minute, block.start_minute + minimumMinutes)
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
    let has_enabled_rules: Bool
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
        case has_enabled_rules, active, override, override_expires_at, source, mode, sports_filter
        case sports_presentation, live_games, timezone, local_day, day_of_week, local_time
        case rule_id, condition_id, scheduled_mode, scheduled_sports_filter
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        has_enabled_rules = try container.decodeIfPresent(Bool.self, forKey: .has_enabled_rules) ?? false
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
