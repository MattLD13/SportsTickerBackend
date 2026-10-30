import Foundation
import SwiftUI

struct ModesView: View {
    @Environment(TickerStore.self) private var store

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 15), count: 3)

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { ScreenTitle(text: "Modes"); Spacer() }.padding(.horizontal).padding(.top, 80)

                LazyVGrid(columns: columns, spacing: 15) {
                    tile("Sports", "sports")
                    if !store.isSportsOnly {
                        tile("Stocks", "stock")
                        tile("Music", "music")
                        tile("Flights", "flights")
                        tile("Weather", "weather")
                        tile("Clock", "clock")
                    }
                }
                .padding(.horizontal)

                Group {
                    switch store.modeCategory {
                    case "flights": FlightsSection()
                    case "weather": WeatherSection()
                    case "clock":
                        VStack(alignment: .leading, spacing: 10) {
                            Text("CLOCK MODE").sectionHeader()
                            Text("Displaying large time and date.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                        }
                    case "music": MusicSection()
                    case "stock": StocksSection()
                    default: LeaguesSection()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
    }

    private func tile(_ title: String, _ category: String) -> some View {
        ModeTile(title: title, symbol: store.modeSymbol(category), selected: store.modeCategory == category) {
            store.setCategory(category)
        }
    }
}

private struct ModeTile: View {
    let title: String
    let symbol: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 12, style: .continuous)
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: symbol).font(.system(size: 16))
                Text(title).font(.subheadline).bold()
            }
            .frame(maxWidth: .infinity).frame(height: 55)
            .background(selected ? Color.blue : Color.white.opacity(0.05))
            .clipShape(shape)
            .overlay(shape.stroke(selected ? Color.blue.opacity(0.8) : Color.white.opacity(0.1), lineWidth: 1))
            .foregroundColor(selected ? .white : .gray)
            .shadow(color: selected ? Color.blue.opacity(0.3) : Color.clear, radius: 4, x: 0, y: 2)
        }
    }
}

/// A text field that shows the saved value until the user types, and saves when the user submits or leaves the field.
private struct CommitField: View {
    let label: String
    let prompt: String
    let saved: String
    var capitals = false
    var commitOnBlur = true
    let commit: (String) -> Void

    @State private var text = ""
    @FocusState private var focused: Bool

    var body: some View {
        HStack {
            Text(label)
            Spacer()
            TextField(prompt, text: $text)
                .multilineTextAlignment(.trailing)
                .foregroundColor(.white)
                .textInputAutocapitalization(capitals ? .characters : .sentences)
                .autocorrectionDisabled(capitals)
                .focused($focused)
                .onSubmit { commit(text); focused = false }
        }
        .padding().liquidGlass()
        .onAppear { text = saved }
        .onChange(of: saved) { _, value in if !focused { text = value } }
        .onChange(of: focused) { _, isFocused in if !isFocused && commitOnBlur { commit(text) } }
    }
}

private struct FlightsSection: View {
    @Environment(TickerStore.self) private var store

    var body: some View {
        let tracking = store.settings.mode == "flights"
        VStack(alignment: .leading, spacing: 16) {
            Text("FLIGHTS MODE").sectionHeader()
            HStack(spacing: 10) {
                OptionButton(title: "Airport", cornerRadius: 10, verticalPadding: 10, selected: !tracking) { store.setFlightView(tracking: false) }
                OptionButton(title: "Track", cornerRadius: 10, verticalPadding: 10, selected: tracking) { store.setFlightView(tracking: true) }
            }
            .padding().liquidGlass()
            VStack(alignment: .leading, spacing: 10) {
                if tracking { tracker } else { airport }
            }
        }
    }

    @ViewBuilder private var airport: some View {
        HStack {
            Image(systemName: "building.2.fill").font(.title2).foregroundStyle(.cyan)
            VStack(alignment: .leading) {
                Text("Airport Activity").bold().foregroundStyle(.white)
                if !store.settings.airportName.isEmpty {
                    Text(store.settings.airportName).font(.caption).foregroundStyle(.gray)
                }
            }
            Spacer()
        }.padding().liquidGlass()
        CommitField(label: "Airport Code:", prompt: "IATA or ICAO (e.g. EWR, KJFK)", saved: store.settings.airportCodeIATA,
                    capitals: true, commitOnBlur: false) { store.setAirport($0) }
        if !store.settings.airportCodeIATA.isEmpty {
            HStack {
                Text("Resolved:").foregroundStyle(.gray)
                Spacer()
                Text("\(store.settings.airportCodeIATA)  ·  \(store.settings.airportCodeICAO)")
                    .foregroundStyle(.cyan).font(.caption).monospaced()
            }
            .padding().liquidGlass()
        }
    }

    @ViewBuilder private var tracker: some View {
        HStack {
            Image(systemName: "airplane.circle.fill").font(.title2).foregroundStyle(.orange)
            VStack(alignment: .leading) {
                Text("Track a Flight").bold().foregroundStyle(.white)
                Text("Enter a flight number to track in real time.").font(.caption).foregroundStyle(.gray)
            }
            Spacer()
        }.padding().liquidGlass()
        CommitField(label: "Flight #:", prompt: "e.g. UA123, DAL456", saved: store.settings.trackFlightID, capitals: true) {
            store.setTrackedFlight($0)
        }
        CommitField(label: "Guest Name:", prompt: "Optional (e.g. Mom)", saved: store.settings.trackGuestName) {
            store.setGuestName($0)
        }
        if store.settings.trackFlightID.isEmpty {
            HStack(spacing: 10) {
                Image(systemName: "airplane.slash").font(.title3).foregroundStyle(.gray)
                VStack(alignment: .leading, spacing: 2) {
                    Text("No flight selected").font(.subheadline).bold().foregroundStyle(.white)
                    Text("Enter a flight number above to start tracking.").font(.caption).foregroundStyle(.gray)
                }
                Spacer()
            }
            .padding().liquidGlass()
        } else {
            HStack {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                Text("Tracking: \(store.settings.trackFlightID)").bold().foregroundStyle(.white)
                Spacer()
                Button { store.clearTrackedFlight() } label: { Text("Clear").font(.caption).foregroundStyle(.red) }
            }.padding().liquidGlass()
        }
    }
}

private struct WeatherSection: View {
    @Environment(TickerStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("WEATHER CONFIGURATION").sectionHeader()
            CommitField(label: "Location:", prompt: "City or Zip", saved: store.weatherInput, commitOnBlur: false) { query in
                Task { await store.setWeatherLocation(query) }
            }
        }
    }
}

private struct MusicSection: View {
    @Environment(TickerStore.self) private var store

    var body: some View {
        let spotify = store.spotify
        VStack(alignment: .leading, spacing: 10) {
            Text("NOW PLAYING").sectionHeader()
            HStack {
                Image(systemName: "hifispeaker.fill").font(.title2).foregroundStyle(.green)
                VStack(alignment: .leading) {
                    Text("Spotify Integration").bold().foregroundStyle(.white)
                    Text("Ticker will display currently playing track.").font(.caption).foregroundStyle(.gray)
                }
                Spacer()
            }.padding().liquidGlass()
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(spotify.status).font(.caption).foregroundStyle(.secondary)
                    if let name = spotify.accountName { Text(name).font(.caption).foregroundStyle(.gray) }
                }
                Spacer()
                Button(spotify.connecting ? "Connecting..." : "Add account") { Task { await store.connectSpotify() } }
                    .font(.caption).foregroundStyle(.green)
                    .disabled(spotify.connecting)
            }
            .padding().liquidGlass()
            if !spotify.accounts.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("CONNECTED ACCOUNTS").font(.caption2).bold().foregroundStyle(.secondary)
                    ForEach(spotify.accounts) { account in
                        HStack(spacing: 10) {
                            Image(systemName: account.priority ? "star.fill" : "person.crop.circle")
                                .foregroundStyle(account.priority ? .yellow : .secondary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(account.displayName).font(.subheadline).bold().foregroundStyle(.white)
                                Text(account.priority ? "Priority account" : "Auto-select when playing").font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button(account.priority ? "Priority" : "Prioritize") { Task { await store.setSpotifyPriority(account.id) } }
                                .font(.caption).foregroundStyle(account.priority ? .yellow : .green)
                            Button(role: .destructive) { Task { await store.disconnectSpotify(account.id) } } label: {
                                Image(systemName: "trash")
                            }
                            .font(.caption)
                        }
                        .padding(10).liquidGlass()
                    }
                    if spotify.accounts.contains(where: \.priority) {
                        Button("Use whichever account is playing") { Task { await store.setSpotifyPriority(nil) } }
                            .font(.caption).foregroundStyle(.green)
                    }
                }
            }
            if let error = spotify.error { Text(error).font(.caption).foregroundStyle(.red) }
        }
    }
}

private struct StocksSection: View {
    @Environment(TickerStore.self) private var store
    /// The ticker whose custom list the editor shows. The editor closes when the active ticker changes.
    @State private var editing: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("MARKETS").sectionHeader()
            Text("Smart markets update automatically. Tap Custom to create or edit your list.").font(.caption).foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 12) {
                ForEach(store.stockLists) { list in
                    let custom = list.id == "stock_custom"
                    OptionButton(title: list.label, symbol: custom ? "square.and.pencil" : "chart.line.uptrend.xyaxis",
                                 selected: store.settings.activeSports[list.id] ?? (list.id == "stock_tech_ai")) {
                        if custom { editing = store.activeTickerID } else { store.selectStockList(list.id) }
                    }
                    .disabled(custom && !store.canEditCustomStocks)
                }
            }
        }
        .sheet(item: Binding(get: { editing.map(EditedTicker.init) }, set: { editing = $0?.id })) { ticker in
            CustomStockEditor(symbols: store.settings.customStockSymbols, search: store.searchStocks) { symbols in
                store.saveCustomStocks(symbols, for: ticker.id)
            }
        }
        .onChange(of: store.activeTickerID) { _, _ in editing = nil }
    }

    private struct EditedTicker: Identifiable { let id: String }
}

private struct LeaguesSection: View {
    @Environment(TickerStore.self) private var store
    @State private var expanded: Set<String> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("ENABLED LEAGUES").sectionHeader()
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), alignment: .top)], spacing: 12) {
                ForEach(LeagueGroup.groups(store.leagues)) { group in
                    Group {
                        if group.hasConferences { conferences(group) } else { leagueButton(group.league) }
                    }
                    .frame(maxHeight: .infinity, alignment: .top)
                }
            }
        }
    }

    private func leagueButton(_ league: League, conference: Bool = false, embedded: Bool = false) -> some View {
        let enabled = store.isEnabled(league)
        let shape = RoundedRectangle(cornerRadius: 12, style: .continuous)
        return Button { store.toggleLeague(league) } label: {
            Text(league.label)
                .font(.subheadline).bold()
                .multilineTextAlignment(.center)
                .padding(.horizontal, embedded ? 8 : 12)
                .frame(maxWidth: .infinity, minHeight: 44)
                .padding(.vertical, 4)
                .background(embedded ? Color.clear : (enabled ? Color.green.opacity(0.8) : Color.white.opacity(0.05)))
                .clipShape(shape)
                .overlay(shape.stroke(embedded ? Color.clear : (enabled ? Color.green : Color.white.opacity(0.1)), lineWidth: 1))
                .foregroundColor(.white)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("\(conference ? "conference" : "league")-\(league.id)")
        .accessibilityLabel(league.label)
        .accessibilityValue(enabled ? "Enabled" : "Disabled")
        .accessibilityHint("Double-tap to change whether this league is enabled.")
    }

    private func conferences(_ group: LeagueGroup) -> some View {
        let open = expanded.contains(group.id)
        let enabled = store.isEnabled(group.league)
        let shape = RoundedRectangle(cornerRadius: 12, style: .continuous)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 0) {
                leagueButton(group.league, embedded: true)
                Rectangle().fill(Color.white.opacity(0.25)).frame(width: 1, height: 24)
                Button {
                    if !expanded.insert(group.id).inserted { expanded.remove(group.id) }
                } label: {
                    Image(systemName: open ? "chevron.up" : "chevron.down")
                        .font(.caption.bold()).frame(width: 44, height: 52).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("conferences-\(group.id)")
                .accessibilityLabel("\(group.league.label) conferences")
                .accessibilityValue(open ? "Expanded" : "Collapsed")
            }
            .background(enabled ? Color.green.opacity(0.8) : Color.white.opacity(0.05))
            .clipShape(shape)
            .overlay(shape.stroke(enabled ? Color.green : Color.white.opacity(0.1), lineWidth: 1))
            .foregroundColor(.white)
            if open {
                if group.conferences.isEmpty {
                    Text("No conferences available.").font(.subheadline).foregroundStyle(.secondary).padding(.vertical, 8)
                } else {
                    VStack(spacing: 10) {
                        ForEach(group.conferences) { leagueButton($0, conference: true) }
                    }
                    .padding(.leading, 8)
                }
            }
        }
    }
}
