import Foundation

/// A league with its college conferences, for the Enabled Leagues grid.
nonisolated struct LeagueGroup: Identifiable {
    let league: League
    let conferences: [League]

    var id: String { league.id }

    /// The college football leagues always offer their conference list, also while it is empty.
    var hasConferences: Bool { league.id == "ncf_fbs" || league.id == "ncf_fcs" || !conferences.isEmpty }

    static func groups(_ leagues: [League]) -> [LeagueGroup] {
        let sports = leagues.filter(\.isSport)
        return sports.filter { $0.conferenceParent == nil }.map { league in
            LeagueGroup(league: league, conferences: sports.filter { $0.conferenceParent == league.id })
        }
    }
}
