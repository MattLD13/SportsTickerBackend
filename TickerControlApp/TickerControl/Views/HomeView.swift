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

struct HomeView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var showTickerSwitcher = false

    private var displayMode: String { vm.state.mode }
    private var sportsFilter: String { vm.state.sports_filter }
    private var leagueLabels: [String: String] { vm.leagueLabels }
    private var splitGames: (
        other: [Game], music: [Game], stocks: [Game], weather: [Game],
        trackedFlights: [Game], airports: [Game]
    ) { partitionedGames }

    private var partitionedGames: (
        other: [Game], music: [Game], stocks: [Game], weather: [Game],
        trackedFlights: [Game], airports: [Game]
    ) {
        var music: [Game] = []
        var stocks: [Game] = []
        var weather: [Game] = []
        var trackedFlights: [Game] = []
        var airports: [Game] = []
        var other: [Game] = []
        for g in vm.games {
            if g.type == "spotify" {
                music.append(g)
            } else if g.type == "stock_ticker" || g.sport == "stock" {
                stocks.append(g)
            } else if g.type == "weather" || g.sport == "weather" {
                weather.append(g)
            } else if g.type == "flight_visitor" {
                trackedFlights.append(g)
            } else if g.type == "flight_airport_hud" || g.sport == "airport" {
                airports.append(g)
            } else {
                other.append(g)
            }
        }
        return (other, music, stocks, weather, trackedFlights, airports)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Ticker Dashboard").font(.system(size: 34, weight: .bold, design: .rounded)).foregroundColor(.white)
                    Button { showTickerSwitcher = true } label: {
                        HStack(spacing: 8) {
                            Circle().fill(vm.statusColor).frame(width: 8, height: 8)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(vm.connectionStatus).font(.caption).foregroundColor(.gray)
                                if vm.pairedTickerCount > 0 {
                                    Text(vm.activeTickerIndicator).font(.caption2).foregroundColor(.blue.opacity(0.9))
                                }
                            }
                            Image(systemName: "arrow.left.arrow.right.circle").foregroundColor(.blue.opacity(0.8))
                        }
                    }
                    .buttonStyle(.plain)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal).padding(.top, 60)

                if vm.scheduleStatus != nil {
                    HomeScheduleControl(vm: vm).id(vm.activeTicker?.id).padding(.horizontal)
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("DISPLAY FILTER").font(.caption).bold().foregroundStyle(.secondary)
                    HStack(spacing: 12) {
                        FilterBtn(title: "Show All", val: "all", cur: sportsFilter) { vm.state.sports_filter = "all"; vm.startBurstPolling(); vm.saveSettings() }
                        FilterBtn(title: "Live Only", val: "live", cur: sportsFilter) { vm.state.sports_filter = "live"; vm.startBurstPolling(); vm.saveSettings() }
                        FilterBtn(title: "My Teams", val: "my_teams", cur: sportsFilter) { vm.state.sports_filter = "my_teams"; vm.startBurstPolling(); vm.saveSettings() }
                    }
                    .disabled(!vm.isSportsMode)
                    .opacity(vm.isSportsMode ? 1.0 : 0.4)
                }.padding(.horizontal)

                VStack(alignment: .leading, spacing: 12) {
                    Text("ACTIVE FEED").font(.caption).bold().foregroundStyle(.secondary)
                    if vm.games.isEmpty {
                        Text("No active items found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        ForEach(splitGames.other) { game in
                            GameRow(game: game, leagueLabel: leagueLabels[game.sport], isPinned: vm.isPinned(game))
                                .onTapGesture { vm.togglePin(game) }
                        }
                        ForEach(splitGames.music) { game in
                            MusicNowPlayingCard(game: game)
                        }
                        if displayMode == "stock" {
                            ForEach(splitGames.stocks) { game in
                                StockFeedCard(game: game)
                            }
                        }
                        ForEach(splitGames.weather) { game in
                            WeatherLocationCard(game: game)
                            WeatherCurrentCard(game: game)
                            WeatherTodayCard(game: game)
                        }
                        ForEach(splitGames.trackedFlights) { game in
                            TrackedFlightFeedCard(game: game)
                        }
                        ForEach(splitGames.airports) { game in
                            AirportLocationCard(game: game)
                            AirportScheduleFeedCard(
                                title: "ARRIVALS",
                                icon: "airplane.arrival",
                                flights: game.arrivals ?? [],
                                color: .green
                            )
                            AirportScheduleFeedCard(
                                title: "DEPARTURES",
                                icon: "airplane.departure",
                                flights: game.departures ?? [],
                                color: .orange
                            )
                        }
                    }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
        .sheet(isPresented: $showTickerSwitcher) {
            TickerSwitcherView(vm: vm, isPresented: $showTickerSwitcher)
        }
    }
}

struct HomeScheduleControl: View {
    @ObservedObject var vm: TickerViewModel
    @State private var updating = false
    @State private var errorMessage: String?

    private var paused: Bool { vm.scheduleStatus?.override == true }
    private var detail: String {
        if paused, let expiry = vm.scheduleStatus?.override_expires_at {
            let zone = TimeZone(identifier: vm.scheduleStatus?.timezone ?? "") ?? .current
            let format = Date.FormatStyle(date: .omitted, time: .shortened, timeZone: zone)
            return "Resumes at \(Date(timeIntervalSince1970: expiry).formatted(format))"
        }
        return paused ? "Using your current mode" : "Override until the next scheduled change"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Image(systemName: paused ? "calendar.badge.minus" : "calendar.badge.clock")
                    .font(.title3).foregroundStyle(paused ? Color.orange : Color.blue)
                VStack(alignment: .leading, spacing: 3) {
                    Text(paused ? "Schedule paused" : "Schedule on").font(.subheadline.weight(.semibold))
                        .accessibilityIdentifier("home-schedule-status")
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                Button(action: toggle) {
                    if updating { ProgressView().controlSize(.small) }
                    else { Text(paused ? "Resume" : "Override").font(.subheadline.weight(.semibold)) }
                }
                .buttonStyle(.bordered).buttonBorderShape(.capsule).tint(.blue)
                .frame(minHeight: 44).disabled(updating)
                .accessibilityIdentifier("home-schedule-override")
            }
            if let errorMessage {
                Text(errorMessage).font(.caption).foregroundStyle(.red)
                    .accessibilityIdentifier("home-schedule-error")
            }
        }
        .padding(14).liquidGlass()
    }

    private func toggle() {
        updating = true
        errorMessage = nil
        vm.setCurrentScheduleOverride(!paused) { result in
            updating = false
            if case .failure(let error) = result, !(error is CancellationError) { errorMessage = error.localizedDescription }
        }
    }
}
struct ModeTile: View {
    let title: String
    let icon: String
    let val: String
    let cur: String
    let act: () -> Void

    var isSelected: Bool { cur == val }

    var body: some View {
        Button(action: act) {
            HStack(spacing: 8) { // Changed to HStack for inline layout
                Image(systemName: icon)
                    .font(.system(size: 16)) // Smaller icon
                Text(title)
                    .font(.subheadline)
                    .bold()
            }
            .frame(maxWidth: .infinity)
            .frame(height: 55) // Reduced height from 85 to 55
            .background(isSelected ? Color.blue : Color.white.opacity(0.05))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(isSelected ? Color.blue.opacity(0.8) : Color.white.opacity(0.1), lineWidth: 1)
            )
            .foregroundColor(isSelected ? .white : .gray)
            .shadow(color: isSelected ? Color.blue.opacity(0.3) : Color.clear, radius: 4, x: 0, y: 2)
        }
    }
}
