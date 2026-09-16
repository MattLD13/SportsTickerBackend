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
        if day_names.count == 7 { return "Every day" }
        return day_names.map { String($0.capitalized.prefix(3)) }.joined(separator: ", ")
    }

    var timeLabel: String {
        "\(Self.clock(start_minute))–\(Self.clock(end_minute))"
    }

    private static func clock(_ minute: Int) -> String {
        let hour = (minute / 60) % 24
        let value = minute % 60
        let suffix = hour >= 12 ? "PM" : "AM"
        let displayHour = hour % 12 == 0 ? 12 : hour % 12
        return String(format: "%d:%02d %@", displayHour, value, suffix)
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
        let comparison = `operator` == "gte" ? "≥" : ">"
        return "When \(kind.replacingOccurrences(of: "_", with: " ")) \(comparison) \(threshold)"
    }
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
