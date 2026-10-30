import Foundation

/// A weekly block: the ticker shows `mode` on the selected days from `startMinute` to `endMinute`.
/// Days count from 0 (Monday) to 6 (Sunday). Minute 1440 ends a block at midnight.
struct ScheduleBlock: Decodable, Identifiable, Hashable {
    let id: String
    let daysOfWeek: [Int]
    let startMinute: Int
    let endMinute: Int
    let mode: String
    let sportsFilter: String?
    let enabled: Bool

    enum CodingKeys: String, CodingKey {
        case id, daysOfWeek = "days_of_week", startMinute = "start_minute", endMinute = "end_minute", mode
        case sportsFilter = "sports_filter", enabled
    }

    init(id: String, daysOfWeek: [Int], startMinute: Int, endMinute: Int, mode: String, sportsFilter: String? = nil, enabled: Bool = true) {
        self.id = id; self.daysOfWeek = daysOfWeek; self.startMinute = startMinute; self.endMinute = endMinute
        self.mode = mode; self.sportsFilter = sportsFilter; self.enabled = enabled
    }

    var dayLabel: String { SchedulePresentation.repeatLabel(daysOfWeek) }
    var timeLabel: String { "\(SchedulePresentation.clock(startMinute)) – \(SchedulePresentation.clock(endMinute))" }
}

/// A live-game rule: while Sports mode shows, the feed switches to live games when enough games are live.
struct ScheduleCondition: Decodable, Identifiable, Hashable {
    let id: String
    let threshold: Int
    let comparison: String
    let enabled: Bool

    enum CodingKeys: String, CodingKey { case id, threshold, comparison = "operator", enabled }

    var label: String { "\(comparison == "gte" ? "At least" : "More than") \(threshold) games live" }
}

/// The effective state of the schedule now.
struct ScheduleStatus: Decodable, Hashable {
    var hasEnabledRules = false
    var active = false
    var override = false
    var overrideExpiresAt: Double?
    var source = "base"
    var mode = "sports"
    var liveGames = 0
    var timezone = ""
    var dayOfWeek = 0

    enum CodingKeys: String, CodingKey {
        case hasEnabledRules = "has_enabled_rules", active, override, overrideExpiresAt = "override_expires_at", source, mode
        case liveGames = "live_games", timezone, dayOfWeek = "day_of_week"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        hasEnabledRules = try c.decodeIfPresent(Bool.self, forKey: .hasEnabledRules) ?? false
        active = try c.decodeIfPresent(Bool.self, forKey: .active) ?? false
        override = try c.decodeIfPresent(Bool.self, forKey: .override) ?? false
        overrideExpiresAt = try c.decodeIfPresent(Double.self, forKey: .overrideExpiresAt)
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? "base"
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "sports"
        liveGames = try c.decodeIfPresent(Int.self, forKey: .liveGames) ?? 0
        timezone = try c.decodeIfPresent(String.self, forKey: .timezone) ?? ""
        dayOfWeek = try c.decodeIfPresent(Int.self, forKey: .dayOfWeek) ?? 0
    }
}

/// The schedule of one ticker, as `GET /tickers/<id>/schedule` returns it.
struct Schedule: Decodable {
    let timezone: String
    let blocks: [ScheduleBlock]
    let conditions: [ScheduleCondition]
    let liveGames: Int
    let effective: ScheduleStatus

    enum CodingKeys: String, CodingKey { case timezone, blocks, conditions, liveGames = "live_games", effective }

    var timeZone: TimeZone { TimeZone(identifier: timezone) ?? .current }
}

/// The body that adds or changes a block. A block for another mode clears its sports filter.
struct ScheduleBlockDraft: Encodable, Equatable {
    var daysOfWeek: [Int]
    var startMinute: Int
    var endMinute: Int
    var mode: String
    var sportsFilter: String?
    var enabled: Bool

    enum CodingKeys: String, CodingKey {
        case daysOfWeek = "days_of_week", startMinute = "start_minute", endMinute = "end_minute", mode
        case sportsFilter = "sports_filter", enabled
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(daysOfWeek, forKey: .daysOfWeek)
        try c.encode(startMinute, forKey: .startMinute)
        try c.encode(endMinute, forKey: .endMinute)
        try c.encode(mode, forKey: .mode)
        try c.encode(sportsFilter, forKey: .sportsFilter)
        try c.encode(enabled, forKey: .enabled)
    }
}

/// The body that adds or changes the live-game rule. The rule always runs in Sports mode, shows live games,
/// and keeps a pinned game first. Only a new rule sends its kind.
struct ScheduleConditionDraft: Encodable, Equatable {
    var isNew: Bool
    var threshold: Int
    var comparison: String
    var enabled: Bool

    enum CodingKeys: String, CodingKey {
        case kind, threshold, comparison = "operator", whenMode = "when_mode", actionSportsFilter = "action_sports_filter"
        case ignorePinned = "ignore_pinned", enabled
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        if isNew { try c.encode("live_games", forKey: .kind) }
        try c.encode(threshold, forKey: .threshold)
        try c.encode(comparison, forKey: .comparison)
        try c.encode("sports", forKey: .whenMode)
        try c.encode("live", forKey: .actionSportsFilter)
        try c.encode(true, forKey: .ignorePinned)
        try c.encode(enabled, forKey: .enabled)
    }
}
