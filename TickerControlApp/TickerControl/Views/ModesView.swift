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

struct ModesView: View {
    @ObservedObject var vm: TickerViewModel

    // 1. LOCAL BUFFER: This is the secret.
    // The background timer cannot touch this variable.
    @State private var localWeatherInput: String = ""
    @FocusState private var isWeatherFieldFocused: Bool

    // Flight tracking local buffers
    @State private var localAirportCode: String = ""
    @State private var localFlightNumber: String = ""
    @State private var localGuestName: String = ""
    @FocusState private var isAirportFieldFocused: Bool
    @FocusState private var isFlightFieldFocused: Bool
    @FocusState private var isGuestFieldFocused: Bool

    let modeColumns = [
        GridItem(.flexible(), spacing: 15),
        GridItem(.flexible(), spacing: 15),
        GridItem(.flexible(), spacing: 15)
    ]

    var sportsOptions: [LeagueOption] {
        vm.leagueOptions.filter { $0.type == "sport" }
    }

    var stockOptions: [LeagueOption] {
        vm.leagueOptions.filter { $0.type == "stock" }
    }

    func setCategory(_ target: String) {
        if vm.isSportsOnly && target != "sports" { return }
        if target != "sports" {
            vm.pinnedGameIDs.removeAll()
            vm.state.pinned_games = []
            vm.state.pinned_game = nil
            vm.state.pinned_content_id = ""
            vm.state.sports_presentation = "rotation"
        }
        switch target {
        case "flights":
            // Default Flights to the airport board. Track selects the visitor card.
            if vm.state.mode != "flights" && vm.state.mode != "airports" {
                vm.state.mode = "airports"
                vm.state.flight_submode = "airport"
            }
        case "stock", "weather", "clock", "music":
            vm.state.mode = target
            vm.state.flight_submode = ""
        default:
            vm.state.mode = "sports"
            vm.state.flight_submode = ""
        }
        if target == "stock" {
            let stockKeys = stockOptions.map { $0.id }
            let hasStock = stockKeys.contains { vm.state.active_sports[$0] == true }
            if !hasStock, let first = stockKeys.first {
                vm.state.active_sports[first] = true
            }
        }
        if target == "music" { vm.fetchSpotifyStatus() }
        vm.startBurstPolling()
        vm.saveSettings(scheduleOverride: true)
    }
    private func setFlightSubmode(_ submode: String) {
        vm.state.mode = submode == "track" ? "flights" : "airports"
        vm.state.flight_submode = submode
        vm.startBurstPolling()
        vm.saveSettings(scheduleOverride: true)
    }
    private func commitFlightNumber() {
        let flight = localFlightNumber.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if flight != vm.state.track_flight_id {
            vm.isEditing = true
            vm.state.track_flight_id = flight
            if flight.isEmpty {
                vm.state.track_guest_name = ""
            }
            vm.saveSettings()
        }
    }
    private func commitGuestName() {
        let guest = localGuestName.trimmingCharacters(in: .whitespacesAndNewlines)
        if guest != vm.state.track_guest_name {
            vm.isEditing = true
            vm.state.track_guest_name = guest
            vm.saveSettings()
        }
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack {
                    Text("Modes").font(.system(size: 34, weight: .bold)).foregroundColor(.white)
                    Spacer()
                }
                .padding(.horizontal).padding(.top, 80)

                LazyVGrid(columns: modeColumns, spacing: 15) {
                    let utilities = ["stock", "weather", "clock", "music", "flights", "airports"]
                    let displayMode = ["flights", "airports"].contains(vm.state.mode) ? "flights" : vm.state.mode
                    let activeCategory = utilities.contains(displayMode) ? displayMode : "sports"

                    ModeTile(title: "Sports", icon: vm.modeSymbol(for: "sports"), val: "sports", cur: activeCategory) { setCategory("sports") }
                    if !vm.isSportsOnly {
                        ModeTile(title: "Stocks", icon: vm.modeSymbol(for: "stock"), val: "stock", cur: activeCategory) { setCategory("stock") }
                        ModeTile(title: "Music", icon: vm.modeSymbol(for: "music"), val: "music", cur: activeCategory) { setCategory("music") }
                        ModeTile(title: "Flights", icon: vm.modeSymbol(for: "flights"), val: "flights", cur: activeCategory) { setCategory("flights") }
                        ModeTile(title: "Weather", icon: vm.modeSymbol(for: "weather"), val: "weather", cur: activeCategory) { setCategory("weather") }
                        ModeTile(title: "Clock", icon: vm.modeSymbol(for: "clock"), val: "clock", cur: activeCategory) { setCategory("clock") }
                    }
                }
                .padding(.horizontal)

                VStack(alignment: .leading, spacing: 20) {
                    if vm.state.mode == "flights" || vm.state.mode == "airports" {
                        VStack(alignment: .leading, spacing: 16) {
                            Text("FLIGHTS MODE").font(.caption).bold().foregroundStyle(.secondary)
                            HStack(spacing: 10) {
                                Button {
                                    setFlightSubmode("airport")
                                } label: {
                                    Text("Airport")
                                        .font(.subheadline).bold()
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 10)
                                        .background(vm.state.mode == "airports" ? Color.blue.opacity(0.8) : Color.white.opacity(0.05))
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(vm.state.mode == "airports" ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                                        .foregroundColor(.white)
                                }
                                Button {
                                    setFlightSubmode("track")
                                } label: {
                                    Text("Track")
                                        .font(.subheadline).bold()
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 10)
                                        .background(vm.state.mode == "flights" ? Color.blue.opacity(0.8) : Color.white.opacity(0.05))
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(vm.state.mode == "flights" ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                                        .foregroundColor(.white)
                                }
                            }
                            .padding().liquidGlass()
                            if vm.state.mode == "airports" {
                                VStack(alignment: .leading, spacing: 10) {
                                    HStack {
                                        Image(systemName: "building.2.fill").font(.title2).foregroundStyle(.cyan)
                                        VStack(alignment: .leading) {
                                            Text("Airport Activity").bold().foregroundStyle(.white)
                                            if !vm.state.airport_name.isEmpty {
                                                Text(vm.state.airport_name).font(.caption).foregroundStyle(.gray)
                                            }
                                        }
                                        Spacer()
                                    }.padding().liquidGlass()

                                    HStack {
                                        Text("Airport Code:")
                                        Spacer()
                                        TextField("IATA or ICAO (e.g. EWR, KJFK)", text: $localAirportCode)
                                            .multilineTextAlignment(.trailing)
                                            .foregroundColor(.white)
                                            .autocapitalization(.allCharacters)
                                            .disableAutocorrection(true)
                                            .focused($isAirportFieldFocused)
                                            .onSubmit {
                                                let code = localAirportCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
                                                if code.count >= 3 && code.count <= 4 {
                                                    vm.isEditing = true
                                                    vm.state.airport_code_iata = code
                                                    vm.saveSettings()
                                                }
                                                isAirportFieldFocused = false
                                            }
                                    }
                                    .padding().liquidGlass()
                                    if !vm.state.airport_code_iata.isEmpty {
                                        HStack {
                                            Text("Resolved:")
                                                .foregroundStyle(.gray)
                                            Spacer()
                                            Text("\(vm.state.airport_code_iata)  ·  \(vm.state.airport_code_icao)")
                                                .foregroundStyle(.cyan)
                                                .font(.caption)
                                                .monospaced()
                                        }
                                        .padding().liquidGlass()
                                    }
                                }
                            } else {
                                VStack(alignment: .leading, spacing: 10) {
                                    HStack {
                                        Image(systemName: "airplane.circle.fill").font(.title2).foregroundStyle(.orange)
                                        VStack(alignment: .leading) {
                                            Text("Track a Flight").bold().foregroundStyle(.white)
                                            Text("Enter a flight number to track in real time.").font(.caption).foregroundStyle(.gray)
                                        }
                                        Spacer()
                                    }.padding().liquidGlass()

                                    HStack {
                                        Text("Flight #:")
                                        Spacer()
                                        TextField("e.g. UA123, DAL456", text: $localFlightNumber)
                                            .multilineTextAlignment(.trailing)
                                            .foregroundColor(.white)
                                            .autocapitalization(.allCharacters)
                                            .disableAutocorrection(true)
                                            .focused($isFlightFieldFocused)
                                            .onSubmit {
                                                commitFlightNumber()
                                                isFlightFieldFocused = false
                                            }
                                            .onChange(of: isFlightFieldFocused) { focused in
                                                if !focused { commitFlightNumber() }
                                            }
                                    }
                                    .padding().liquidGlass()

                                    HStack {
                                        Text("Guest Name:")
                                        Spacer()
                                        TextField("Optional (e.g. Mom)", text: $localGuestName)
                                            .multilineTextAlignment(.trailing)
                                            .foregroundColor(.white)
                                            .focused($isGuestFieldFocused)
                                            .onSubmit {
                                                commitGuestName()
                                                isGuestFieldFocused = false
                                            }
                                            .onChange(of: isGuestFieldFocused) { focused in
                                                if !focused { commitGuestName() }
                                            }
                                    }
                                    .padding().liquidGlass()

                                    if vm.state.track_flight_id.isEmpty {
                                        HStack(spacing: 10) {
                                            Image(systemName: "airplane.slash")
                                                .font(.title3)
                                                .foregroundStyle(.gray)
                                            VStack(alignment: .leading, spacing: 2) {
                                                Text("No flight selected")
                                                    .font(.subheadline).bold().foregroundStyle(.white)
                                                Text("Enter a flight number above to start tracking.")
                                                    .font(.caption).foregroundStyle(.gray)
                                            }
                                            Spacer()
                                        }
                                        .padding().liquidGlass()
                                    }
                                    if !vm.state.track_flight_id.isEmpty {
                                        HStack {
                                            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                                            Text("Tracking: \(vm.state.track_flight_id)").bold().foregroundStyle(.white)
                                            Spacer()
                                            Button {
                                                vm.isEditing = true
                                                vm.state.track_flight_id = ""
                                                vm.state.track_guest_name = ""
                                                localFlightNumber = ""
                                                localGuestName = ""
                                                vm.saveSettings()
                                            } label: {
                                                Text("Clear").font(.caption).foregroundStyle(.red)
                                            }
                                        }.padding().liquidGlass()
                                    }
                                }
                            }
                        }
                    } else if vm.state.mode == "weather" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("WEATHER CONFIGURATION").font(.caption).bold().foregroundStyle(.secondary)
                            HStack {
                                Text("Location:")
                                Spacer()
                                // 2. BIND TO LOCAL INPUT: Not the ViewModel
                                TextField("City or Zip", text: $localWeatherInput)
                                    .multilineTextAlignment(.trailing)
                                    .foregroundColor(.white)
                                    .focused($isWeatherFieldFocused)
                                    .onSubmit {
                                        // 3. PUSH LOCAL TO GLOBAL: Only happens on Enter
                                        vm.weatherLocInput = localWeatherInput
                                        vm.updateWeatherAndSave()
                                        isWeatherFieldFocused = false
                                    }
                            }
                            .padding().liquidGlass()
                        }
                    } else if vm.state.mode == "clock" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("CLOCK MODE").font(.caption).bold().foregroundStyle(.secondary)
                            Text("Displaying large time and date.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                        }
                    } else if vm.state.mode == "music" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("NOW PLAYING").font(.caption).bold().foregroundStyle(.secondary)
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
                                    Text(vm.spotifyStatus).font(.caption).foregroundStyle(.secondary)
                                    if let accountName = vm.spotifyAccountName {
                                        Text(accountName).font(.caption).foregroundStyle(.gray)
                                    }
                                }
                                Spacer()
                                Button(vm.isConnectingSpotify ? "Connecting..." : "Add account") { vm.connectSpotify() }
                                    .font(.caption).foregroundStyle(.green)
                                    .disabled(vm.isConnectingSpotify)
                            }
                            .padding().liquidGlass()
                            if !vm.spotifyAccounts.isEmpty {
                                VStack(alignment: .leading, spacing: 8) {
                                    Text("CONNECTED ACCOUNTS").font(.caption2).bold().foregroundStyle(.secondary)
                                    ForEach(vm.spotifyAccounts) { account in
                                        HStack(spacing: 10) {
                                            Image(systemName: account.priority ? "star.fill" : "person.crop.circle")
                                                .foregroundStyle(account.priority ? .yellow : .secondary)
                                            VStack(alignment: .leading, spacing: 2) {
                                                Text(account.display_name).font(.subheadline).bold().foregroundStyle(.white)
                                                Text(account.priority ? "Priority account" : "Auto-select when playing")
                                                    .font(.caption2).foregroundStyle(.secondary)
                                            }
                                            Spacer()
                                            Button(account.priority ? "Priority" : "Prioritize") {
                                                vm.setSpotifyPriority(accountID: account.spotify_account_id)
                                            }
                                            .font(.caption).foregroundStyle(account.priority ? .yellow : .green)
                                            Button(role: .destructive) {
                                                vm.disconnectSpotify(accountID: account.spotify_account_id)
                                            } label: {
                                                Image(systemName: "trash")
                                            }
                                            .font(.caption)
                                        }
                                        .padding(10).liquidGlass()
                                    }
                                    if vm.spotifyAccounts.contains(where: { $0.priority }) {
                                        Button("Use whichever account is playing") {
                                            vm.setSpotifyPriority(accountID: nil)
                                        }
                                        .font(.caption).foregroundStyle(.green)
                                    }
                                }
                            }
                            if let error = vm.spotifyError {
                                Text(error).font(.caption).foregroundStyle(.red)
                            }
                        }
                    } else if vm.state.mode == "stock" {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("MARKET SECTORS").font(.caption).bold().foregroundStyle(.secondary)
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 12) {
                                ForEach(stockOptions) { opt in
                                    let isActive = vm.state.active_sports[opt.id] ?? true
                                    Button {
                                        // 1. CLEAR ALL OTHER STOCKS FIRST
                                        // This forces a "Single Select" behavior
                                        for stockKey in stockOptions.map({ $0.id }) {
                                            vm.state.active_sports[stockKey] = false
                                        }

                                        // 2. SET THE NEW ONE
                                        vm.state.active_sports[opt.id] = true

                                        // 3. SAVE
                                        vm.saveSettings()
                                    } label: {
                                        Text(opt.label).font(.subheadline).bold().frame(maxWidth: .infinity).padding(.vertical, 12)
                                            .background(isActive ? Color.blue.opacity(0.8) : Color.white.opacity(0.05))
                                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(isActive ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                                            .foregroundColor(.white)
                                    }
                                }
                            }
                        }
                    } else {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("ENABLED LEAGUES").font(.caption).bold().foregroundStyle(.secondary)
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 12) {
                                ForEach(sportsOptions) { opt in
                                    let isActive = vm.state.active_sports[opt.id] ?? true
                                    Button {
                                        vm.state.active_sports[opt.id] = !isActive
                                        vm.saveSettings()
                                    } label: {
                                        Text(opt.label).font(.subheadline).bold().frame(maxWidth: .infinity).padding(.vertical, 12)
                                            .background(isActive ? Color.green.opacity(0.8) : Color.white.opacity(0.05))
                                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(isActive ? Color.green : Color.white.opacity(0.1), lineWidth: 1))
                                            .foregroundColor(.white)
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal)
                Spacer(minLength: 120)
            }
        }
        // 4. SYNC LOGIC: Updates the text field only when NOT typing
        .onAppear {
            localWeatherInput = vm.state.weather_city
            localAirportCode = vm.state.airport_code_iata
            localFlightNumber = vm.state.track_flight_id
            localGuestName = vm.state.track_guest_name
        }
        .onChange(of: vm.state.weather_city) { newValue in
            if !isWeatherFieldFocused {
                localWeatherInput = newValue
            }
        }
        .onChange(of: vm.state.airport_code_iata) { newValue in
            if !isAirportFieldFocused { localAirportCode = newValue }
        }
        .onChange(of: vm.state.track_flight_id) { newValue in
            if !isFlightFieldFocused { localFlightNumber = newValue }
        }
        .onChange(of: vm.state.track_guest_name) { newValue in
            if !isGuestFieldFocused { localGuestName = newValue }
        }
    }
}
