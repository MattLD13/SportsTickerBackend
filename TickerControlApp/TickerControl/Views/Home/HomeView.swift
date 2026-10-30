import Foundation
import SwiftUI

struct HomeView: View {
    @Environment(TickerStore.self) private var store
    @State private var showSwitcher = false

    private var labels: [String: String] { Dictionary(store.leagues.map { ($0.id, $0.label) }) { first, _ in first } }

    var body: some View {
        let sections = FeedSections(store.feed)
        ScrollView {
            VStack(spacing: 24) {
                header.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal).padding(.top, 60)

                VStack(alignment: .leading, spacing: 8) {
                    Text("DISPLAY FILTER").sectionHeader()
                    HStack(spacing: 12) {
                        filter("Show All", "all")
                        filter("Live Only", "live")
                        filter("My Teams", "my_teams")
                    }
                    .disabled(!store.isSportsMode)
                    .opacity(store.isSportsMode ? 1 : 0.4)
                }.padding(.horizontal)

                VStack(alignment: .leading, spacing: 12) {
                    Text("ACTIVE FEED").sectionHeader()
                    if store.feed.isEmpty {
                        Text("No active items found.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        feed(sections)
                    }
                }.padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
        .sheet(isPresented: $showSwitcher) { TickerSwitcherView() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Ticker Dashboard").font(.system(size: 34, weight: .bold, design: .rounded)).foregroundColor(.white)
            HStack(spacing: 12) {
                Button { showSwitcher = true } label: {
                    HStack(spacing: 8) {
                        Circle().fill(store.connection.tone.color).frame(width: 8, height: 8)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(store.connection.text).font(.caption).foregroundColor(.gray)
                            if !store.devices.isEmpty {
                                Text(store.activeTickerLabel).font(.caption2).foregroundColor(.blue.opacity(0.9))
                            }
                        }
                        Image(systemName: "arrow.left.arrow.right.circle").foregroundColor(.blue.opacity(0.8))
                    }
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("home-ticker-switcher")
                .frame(maxWidth: .infinity, alignment: .leading)
                if store.schedule?.hasEnabledRules == true {
                    ScheduleOverrideButton().id(store.activeTickerID).fixedSize(horizontal: true, vertical: false)
                }
            }
        }
    }

    private func filter(_ title: String, _ value: String) -> some View {
        ChoiceButton(title: title, selected: store.settings.sportsFilter == value) { store.setFilter(value) }
    }

    @ViewBuilder private func feed(_ sections: FeedSections) -> some View {
        ForEach(sections.games) { item in
            GameCard(item: item, leagueLabel: item.game.flatMap { labels[$0.sport] }, isPinned: store.isPinned(item))
                .onTapGesture { store.togglePin(item) }
        }
        ForEach(sections.music) { item in
            if case .music(let track) = item.payload { NowPlayingCard(track: track) }
        }
        if store.settings.mode == "stock" {
            ForEach(sections.stocks) { item in
                if case .stock(let quote) = item.payload { StockCard(quote: quote) }
            }
        }
        ForEach(sections.weather) { item in
            if case .weather(let report) = item.payload {
                WeatherLocationCard(report: report)
                WeatherCurrentCard(report: report)
                WeatherTodayCard(report: report)
            }
        }
        ForEach(sections.flights) { item in
            if case .flight(let flight) = item.payload { TrackedFlightCard(flight: flight) }
        }
        ForEach(sections.airports) { item in
            if case .airport(let board) = item.payload {
                AirportCard(board: board)
                AirportScheduleCard(title: "ARRIVALS", symbol: "airplane.arrival", flights: board.arrivals, color: .green)
                AirportScheduleCard(title: "DEPARTURES", symbol: "airplane.departure", flights: board.departures, color: .orange)
            }
        }
    }
}

extension ConnectionStatus.Tone {
    var color: Color {
        switch self {
        case .neutral: return .gray
        case .good: return .green
        case .warning: return .orange
        case .failure: return .red
        case .schedule: return .blue
        }
    }
}

/// Pause the schedule until its next change, or resume it.
struct ScheduleOverrideButton: View {
    @Environment(TickerStore.self) private var store
    @State private var updating = false
    @State private var errorMessage: String?

    private var paused: Bool { store.schedule?.override == true }

    private var detail: String {
        if paused, let expiry = store.schedule?.overrideExpiresAt {
            let zone = TimeZone(identifier: store.schedule?.timezone ?? "") ?? .current
            let format = Date.FormatStyle(date: .omitted, time: .shortened, timeZone: zone)
            return "Resumes at \(Date(timeIntervalSince1970: expiry).formatted(format))"
        }
        return paused ? "Using your current mode" : "Override until the next scheduled change"
    }

    var body: some View {
        Button(action: toggle) {
            if updating {
                ProgressView().controlSize(.mini)
            } else {
                Label(paused ? "Resume" : "Override", systemImage: paused ? "play.fill" : "pause.fill")
                    .font(.caption.weight(.semibold))
            }
        }
        .buttonStyle(.bordered).buttonBorderShape(.capsule).controlSize(.small).tint(.blue)
        .frame(minHeight: 44).disabled(updating)
        .accessibilityLabel(paused ? "Resume" : "Override")
        .accessibilityValue(paused ? "Schedule paused" : "Schedule on")
        .accessibilityHint(detail).accessibilityIdentifier("home-schedule-override")
        .alert("Schedule update failed", isPresented: Binding(
            get: { errorMessage != nil }, set: { if !$0 { errorMessage = nil } }
        )) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
    }

    private func toggle() {
        updating = true
        errorMessage = nil
        let enable = !paused
        Task {
            do { try await store.setScheduleOverride(enable) } catch is CancellationError {} catch {
                errorMessage = error.localizedDescription
            }
            updating = false
        }
    }
}
