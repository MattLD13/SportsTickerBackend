import SwiftUI
import Foundation
import Combine
import UIKit
import CoreLocation
import Security
import AuthenticationServices
import NetworkExtension
import CoreBluetooth
import CryptoKit

struct TeamsView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var selectedLeague = ""

    var sportsOptions: [LeagueOption] {
        vm.leagueOptions.filter { opt in
            guard opt.type == "sport" else { return false }
            return opt.my_teams_enabled != false && vm.state.active_sports[opt.id] != false
        }
    }

    let teamColumns = [GridItem(.adaptive(minimum: 60))]

    var body: some View {
        VStack(spacing: 0) {

            // Header
            HStack {
                Text("My Teams").font(.system(size: 34, weight: .bold)).foregroundColor(.white)
                Spacer()

                // Status Indicator
                if vm.isEditing {
                    Text("Saving...").font(.caption).bold().foregroundColor(.orange)
                } else {
                    Text("\(vm.state.my_teams.count) Selected").font(.caption).bold().foregroundColor(.gray)
                }
            }
            .padding(.horizontal)
            .padding(.top, 80)
            .padding(.bottom, 10)

            ScrollView {
                VStack(alignment: .leading, spacing: 20) {

                    // League Tabs
                    if !sportsOptions.isEmpty {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))], spacing: 10) {
                            ForEach(sportsOptions) { opt in
                                Button { selectedLeague = opt.id; vm.fetchTeams(for: opt.id) } label: {
                                    Text(opt.label).bold().font(.caption)
                                        .frame(maxWidth: .infinity).padding(.vertical, 8)
                                        .background(selectedLeague == opt.id ? Color.blue : Color(white: 0.2))
                                        .foregroundColor(.white).clipShape(RoundedRectangle(cornerRadius: 8))
                                }
                            }
                        }
                    }

                    Divider().background(Color.white.opacity(0.2))

                    // Teams Grid
                    if let teams = vm.allTeams[selectedLeague], !teams.isEmpty {
                        let filteredTeams = teams
                            .filter { $0.abbr.trimmingCharacters(in: .whitespaces).count > 0 && $0.abbr != "TBD" && $0.abbr != "null" }
                            .sorted { $0.abbr < $1.abbr }

                        LazyVGrid(columns: teamColumns, spacing: 15) {
                            ForEach(filteredTeams, id: \.self) { team in

                                // === SMART MATCHING LOGIC ===
                                // 1. Clean inputs
                                let cleanAbbr = team.abbr.trimmingCharacters(in: .whitespacesAndNewlines)
                                let cleanLeague = selectedLeague.trimmingCharacters(in: .whitespacesAndNewlines)

                                // 2. Construct the "Smart ID" (e.g. nfl:NYG)
                                let smartID = "\(cleanLeague):\(cleanAbbr)"

                                // 3. Check against saved list using scoped ID (e.g. "mlb:ATL")
                                let isSelected = vm.state.my_teams.contains(team.id) ||
                                                 vm.state.my_teams.contains(smartID)

                                Button {
                                    print("🔵 Toggling Team: \(smartID)") // DEBUG PRINT
                                    vm.toggleTeam(smartID)
                                } label: {
                                    VStack {
                                        TeamLogoView(url: team.logo, abbr: team.abbr, size: 40)
                                        Text(team.abbr).font(.caption2).bold()
                                            .foregroundColor(isSelected ? .white : .gray)
                                    }
                                    .padding(8)
                                    .background(isSelected ? Color.blue.opacity(0.3) : Color.clear)
                                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                    .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .stroke(isSelected ? Color.blue : Color.clear, lineWidth: 2))
                                }
                            }
                        }
                    } else if !selectedLeague.isEmpty {
                        Text("No teams found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
        .onAppear {
            if !sportsOptions.isEmpty && (selectedLeague.isEmpty || !sportsOptions.contains(where: { $0.id == selectedLeague })) {
                selectedLeague = sportsOptions.first?.id ?? ""
                vm.fetchTeams(for: selectedLeague)
            }
        }
        .onChange(of: vm.leagueOptions) { _ in
            if !sportsOptions.isEmpty && (selectedLeague.isEmpty || !sportsOptions.contains(where: { $0.id == selectedLeague })) {
                selectedLeague = sportsOptions.first?.id ?? ""
                vm.fetchTeams(for: selectedLeague)
            }
        }
    }
}
