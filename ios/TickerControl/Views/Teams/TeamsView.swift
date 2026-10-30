import Foundation
import SwiftUI

struct TeamsView: View {
    @Environment(TickerStore.self) private var store
    @State private var league = ""

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                ScreenTitle(text: "My Teams")
                Spacer()
                if store.isEditing {
                    Text("Saving...").font(.caption).bold().foregroundColor(.orange)
                } else {
                    Text("\(store.myTeams.count) Selected").font(.caption).bold().foregroundColor(.gray)
                }
            }
            .padding(.horizontal).padding(.top, 80).padding(.bottom, 10)

            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if !store.teamLeagues.isEmpty {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))], spacing: 10) {
                            ForEach(store.teamLeagues) { option in
                                Button { choose(option.id) } label: {
                                    Text(option.label).bold().font(.caption)
                                        .frame(maxWidth: .infinity).padding(.vertical, 8)
                                        .background(league == option.id ? Color.blue : Color(white: 0.2))
                                        .foregroundColor(.white).clipShape(RoundedRectangle(cornerRadius: 8))
                                }
                            }
                        }
                    }
                    Divider().background(Color.white.opacity(0.2))
                    teams
                }
                .padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
        .onAppear(perform: keepLeagueValid)
        .onChange(of: store.teamLeagues) { _, _ in keepLeagueValid() }
    }

    @ViewBuilder private var teams: some View {
        let shown = (store.teams[league] ?? []).filter { !$0.isPlaceholder }.sorted { $0.abbr < $1.abbr }
        if !shown.isEmpty {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 60))], spacing: 15) {
                ForEach(shown) { team in
                    let selected = store.myTeams.contains(team.id)
                    let shape = RoundedRectangle(cornerRadius: 10, style: .continuous)
                    Button { store.toggleTeam(team.id) } label: {
                        VStack {
                            TeamLogo(url: team.logo, abbr: team.abbr, size: 40)
                            Text(team.abbr).font(.caption2).bold().foregroundColor(selected ? .white : .gray)
                        }
                        .padding(8)
                        .background(selected ? Color.blue.opacity(0.3) : Color.clear)
                        .clipShape(shape)
                        .overlay(shape.stroke(selected ? Color.blue : Color.clear, lineWidth: 2))
                    }
                }
            }
        } else if !league.isEmpty {
            Text("No teams found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
        }
    }

    private func choose(_ id: String) {
        league = id
        Task { await store.loadTeams(id) }
    }

    /// Select the first league when the selected league is gone, such as after the user disables it.
    private func keepLeagueValid() {
        let leagues = store.teamLeagues
        guard let first = leagues.first, !leagues.contains(where: { $0.id == league }) else { return }
        choose(first.id)
    }
}
