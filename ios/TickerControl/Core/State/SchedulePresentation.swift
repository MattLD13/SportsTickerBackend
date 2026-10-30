import Foundation

nonisolated enum ScheduleCalendarScope: String, CaseIterable {
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

nonisolated struct ScheduleCalendarColumn: Identifiable {
    let id: String
    let title: String
    let days: [Int]

    func blocks(_ values: [ScheduleBlock]) -> [ScheduleBlock] {
        let selected = Set(days)
        return SchedulePresentation.blocks(values.filter { !selected.isDisjoint(with: $0.daysOfWeek) }, on: nil)
    }

    static func minute(hour: Int, fraction: Double) -> Int {
        let quarter = max(0, min(3, Int(fraction * 4)))
        return min(1425, hour * 60 + quarter * 15)
    }
}

nonisolated enum SchedulePresentation {
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

    static func calendarPlacements(_ blocks: [ScheduleBlock], minimumMinutes: Int = 45) -> [ScheduleCalendarPlacement] {
        let ordered = self.blocks(blocks, on: nil)
        var result: [ScheduleCalendarPlacement] = []
        var groupStart = 0
        var groupEnd = -1
        var laneEnds: [Int] = []
        func finishGroup() {
            for index in groupStart..<result.count { result[index].columns = laneEnds.count }
        }
        for block in ordered {
            if block.startMinute >= groupEnd {
                finishGroup()
                groupStart = result.count
                laneEnds = []
            }
            let visualEnd = max(block.endMinute, block.startMinute + minimumMinutes)
            let column = laneEnds.firstIndex { $0 <= block.startMinute } ?? laneEnds.count
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

    static func blocks(_ blocks: [ScheduleBlock], on day: Int?) -> [ScheduleBlock] {
        blocks.filter { block in day.map { block.daysOfWeek.contains($0) } ?? true }.sorted {
            if $0.startMinute != $1.startMinute { return $0.startMinute < $1.startMinute }
            if $0.endMinute != $1.endMinute { return $0.endMinute < $1.endMinute }
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

nonisolated struct ScheduleCalendarPlacement: Identifiable {
    let block: ScheduleBlock
    let column: Int
    var columns: Int
    let visualEnd: Int
    var id: String { block.id }
}

nonisolated extension SchedulePresentation {
    /// The SF Symbol of a mode, when the server catalog has none.
    static func modeSymbol(_ mode: String) -> String {
        switch mode {
        case "sports": return "sportscourt.fill"
        case "stock": return "chart.line.uptrend.xyaxis"
        case "music": return "music.note"
        case "weather": return "cloud.sun.fill"
        case "flights": return "airplane"
        case "airports": return "airplane.arrival"
        case "clock": return "clock.fill"
        default: return "circle"
        }
    }
}
