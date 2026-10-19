import Foundation

struct EnabledLeagueGroup: Identifiable {
    let league: LeagueOption
    let conferences: [LeagueOption]

    var id: String { league.id }

    var hasConferenceDisclosure: Bool {
        league.id == "ncf_fbs" || league.id == "ncf_fcs" || !conferences.isEmpty
    }
}

struct EnabledLeagueControls {
    private(set) var expandedParents: Set<String> = []

    static func groups(from options: [LeagueOption]) -> [EnabledLeagueGroup] {
        let sports = options.filter { $0.type == "sport" }
        return sports.filter { $0.conference_parent == nil }.map { league in
            EnabledLeagueGroup(
                league: league,
                conferences: sports.filter { $0.conference_parent == league.id }
            )
        }
    }

    mutating func toggleDisclosure(for parentID: String) {
        if expandedParents.contains(parentID) {
            expandedParents.remove(parentID)
        } else {
            expandedParents.insert(parentID)
        }
    }

    static func toggle(_ league: LeagueOption, in activeSports: inout [String: Bool]) {
        activeSports[league.id] = !(activeSports[league.id] ?? true)
    }
}
