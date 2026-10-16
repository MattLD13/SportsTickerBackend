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

struct TickerSwitcherView: View {
    @ObservedObject var vm: TickerViewModel
    @Binding var isPresented: Bool

    var body: some View {
        NavigationView {
            List {
                if vm.devices.isEmpty {
                    Text("No paired tickers found.")
                        .foregroundColor(.secondary)
                } else {
                    ForEach(vm.devices) { device in
                        Button {
                            vm.switchToTicker(device.id)
                            isPresented = false
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: device.id == vm.activeTicker?.id ? "checkmark.circle.fill" : "circle")
                                    .foregroundColor(device.id == vm.activeTicker?.id ? .blue : .secondary)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(device.name).foregroundColor(.primary)
                                    let family = device.profile?.product_family.uppercased() ?? "TICKER"
                                    let dimensions = device.profile.map { "\($0.display.width)×\($0.display.height)" } ?? ""
                                    Text([family, dimensions].filter { !$0.isEmpty }.joined(separator: " • "))
                                        .font(.caption)
                                        .foregroundColor(.secondary)
                                }
                                Spacer()
                                if let lastSeen = device.last_seen {
                                    Text(Date(timeIntervalSince1970: lastSeen), style: .relative)
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Switch Ticker")
            .navigationBarItems(trailing: Button("Close") { isPresented = false })
        }
    }
}
struct WiFiSetupView: View {
    @ObservedObject var vm: TickerViewModel
    @Binding var isPresented: Bool

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Ticker Bluetooth")) {
                    Text("Turn on Bluetooth and enter the temporary setup PIN shown after the ticker opens setup mode. The app sends Wi-Fi details through an encrypted local Bluetooth session, then pairs automatically when the ticker has a backend code.")
                    TextField("Six-digit setup PIN", text: $vm.wifiSetupCode)
                        .keyboardType(.numberPad)
                        .textContentType(.oneTimeCode)
                        .disabled(vm.isWifiSetupInProgress)
                }
                Section(header: Text("Home Wi-Fi")) {
                    Picker("Network", selection: $vm.wifiNetworkChoice) {
                        Text("This iPhone's current Wi-Fi").tag(0)
                        Text("Different Wi-Fi network").tag(1)
                    }
                    if vm.wifiNetworkChoice == 0 {
                        HStack {
                            Text(vm.wifiDetectedSSID.isEmpty ? "Detecting network..." : vm.wifiDetectedSSID)
                                .foregroundColor(vm.wifiDetectedSSID.isEmpty ? .secondary : .primary)
                            Spacer()
                            Button("Refresh") { vm.fetchCurrentWiFiSSID() }
                                .disabled(vm.isWifiSetupInProgress)
                        }
                    } else {
                        TextField("Network name", text: $vm.wifiHomeSSID)
                            .textContentType(.username)
                            .disabled(vm.isWifiSetupInProgress)
                    }
                    SecureField("Wi-Fi password", text: $vm.wifiHomePassword)
                        .disabled(vm.isWifiSetupInProgress)
                    Button(vm.isWifiSetupInProgress ? "Connecting..." : "Connect ticker over Bluetooth") {
                        vm.startWiFiSetup(
                            code: vm.wifiSetupCode,
                            homeSSID: vm.wifiHomeSSID,
                            homePassword: vm.wifiHomePassword
                        )
                    }
                    .disabled(vm.isWifiSetupInProgress)
                }
                if !vm.wifiSetupStatus.isEmpty {
                    Section { Text(vm.wifiSetupStatus).foregroundColor(.secondary) }
                }
                if let error = vm.wifiSetupError {
                    Section { Text(error).foregroundColor(.red) }
                }
            }
            .navigationTitle("Ticker Wi-Fi")
            .navigationBarItems(trailing: Button("Close") { isPresented = false })
            .onAppear { vm.fetchCurrentWiFiSSID() }
        }
    }
}
struct DeviceRow: View {
    let device: TickerDevice
    @ObservedObject var vm: TickerViewModel
    @State private var showSchedule = false

    @State private var brightness: Double
    @State private var speedInt: Double
    @State private var delaySecondsInt: Double

    let haptic = UIImpactFeedbackGenerator(style: .medium)

    var lastSeenString: String {
        guard let ls = device.last_seen else { return "Never" }
        let diff = Int(Date().timeIntervalSince1970 - ls)
        if diff < 60 { return "Online" }
        if diff < 3600 { return "Last seen: \(diff/60)m ago" }
        return "Last seen: \(diff/3600)h ago"
    }

    var isOnline: Bool { return lastSeenString == "Online" }

    init(device: TickerDevice, vm: TickerViewModel) {
        self.device = device
        self.vm = vm

        // Initialize State from Device Settings
        _brightness = State(initialValue: Double(device.settings.brightness) / 100.0)

        let raw = device.settings.scroll_speed
        let uiVal = round((0.11 - raw) * 100)
        _speedInt = State(initialValue: max(1, min(10, uiVal)))

        let ds = device.settings.live_delay_seconds ?? 45
        _delaySecondsInt = State(initialValue: Double(ds))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button {
                    vm.switchToTicker(device.id)
                } label: {
                    Image(systemName: device.id == vm.activeTicker?.id ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundColor(device.id == vm.activeTicker?.id ? .blue : .secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(device.id == vm.activeTicker?.id ? "Active ticker" : "Use this ticker")
                VStack(alignment: .leading) {
                    Text(device.name).font(.headline).foregroundColor(.white)
                    Text("ID: \(device.id.prefix(8))...").font(.caption).foregroundColor(.gray)
                    if let profile = device.profile {
                        Text("\(profile.product_family.uppercased()) • \(profile.display.width)×\(profile.display.height)")
                            .font(.caption2)
                            .foregroundColor(.blue.opacity(0.8))
                    }
                }
                Spacer()
                VStack(alignment: .trailing) {
                    Image(systemName: "light.beacon.max.fill").foregroundColor(isOnline ? .green : .red)
                    Text(lastSeenString).font(.system(size: 9)).foregroundColor(.gray)
                }
            }
            Divider().background(Color.white.opacity(0.1))

            // Brightness
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Image(systemName: "sun.max").font(.caption)
                    Spacer()
                    Text("\(Int(brightness * 100))%").font(.caption).monospacedDigit().bold()
                }
                Slider(value: $brightness, in: 0...1, step: 0.05, onEditingChanged: { editing in
                    if !editing { vm.updateDeviceSettings(id: device.id, brightness: brightness) }
                }).tint(.white).onChange(of: brightness) { _ in haptic.impactOccurred() }
            }

            // Speed
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Image(systemName: "tortoise").font(.caption)
                    Spacer()
                    Text("Speed: \(Int(speedInt))").font(.caption).monospacedDigit().bold()
                    Spacer()
                    Image(systemName: "hare").font(.caption)
                }
                Slider(value: $speedInt, in: 1...10, step: 1, onEditingChanged: { editing in
                    if !editing {
                        let newFloat = 0.11 - (speedInt * 0.01)
                        vm.updateDeviceSettings(id: device.id, speed: newFloat)
                    }
                }).tint(.blue).onChange(of: speedInt) { _ in haptic.impactOccurred() }
            }

            Divider().background(Color.white.opacity(0.1))

            HStack {
                Toggle("Inverted", isOn: Binding(
                    get: { device.settings.inverted ?? false },
                    set: { vm.updateDeviceSettings(id: device.id, inverted: $0) }
                )).fixedSize()
                .labelsHidden()
                .toggleStyle(SwitchToggleStyle(tint: .blue))
                Text("Inverted").font(.caption)
                Spacer()
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Toggle("Stream Delay", isOn: Binding(
                        get: { device.settings.live_delay_mode ?? false },
                        set: { vm.updateDeviceSettings(id: device.id, liveDelayMode: $0) }
                    ))
                    .labelsHidden()
                    .toggleStyle(SwitchToggleStyle(tint: .orange))

                    Text("Live Stream Delay").font(.caption)
                    Spacer()
                    Button {
                        showSchedule = true
                    } label: {
                        VStack(spacing: 2) {
                            Image(systemName: "calendar.badge.clock")
                                .font(.headline)
                            Text("Schedule")
                                .font(.caption2)
                        }
                        .foregroundColor(.yellow)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Edit schedule")
                }

                if device.settings.live_delay_mode == true {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text("Buffer: \(Int(delaySecondsInt))s")
                                .font(.caption).monospacedDigit().bold().foregroundColor(.orange)
                            Spacer()
                        }
                        Slider(value: $delaySecondsInt, in: 15...120, step: 15, onEditingChanged: { editing in
                            if !editing {
                                vm.updateDeviceSettings(id: device.id, delaySeconds: Int(delaySecondsInt))
                            }
                        })
                        .tint(.orange)
                    }.transition(.opacity)
                }
            }

            Divider().background(Color.white.opacity(0.1))

            HStack {
                Button(action: { UIPasteboard.general.string = device.id }) { Label("Copy ID", systemImage: "doc.on.doc").font(.caption).bold() }
                Spacer()
                Button(action: { vm.showPairCode(for: device.id) }) { Label("Show Pair Code", systemImage: "number").font(.caption).bold() }
                Spacer()
                Button(action: { vm.unpairTicker(id: device.id) }) { Label("Unpair", systemImage: "trash").font(.caption).bold().foregroundColor(.red) }
            }
        }
        .padding().liquidGlass()
        .alert("Pair Code", isPresented: $vm.showingPairCodeAlert) {
            Button("OK", role: .cancel) { }
        } message: {
            Text(vm.pairCodeAlertMessage)
        }
        .sheet(isPresented: $showSchedule) {
            TickerScheduleView(vm: vm, device: device, isPresented: $showSchedule)
        }
    }
}
struct PairingView: View {
    @ObservedObject var vm: TickerViewModel
    @Binding var isPresented: Bool
    @State private var shareWithApp = false
    @State private var showWiFiSetup = false
    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Instructions")) { Text("1. Ensure your Ticker is powered on."); Text("2. Wait for the app pairing code. On Mini, look for APP PAIR."); Text("3. Enter that code below. Use WIFI PIN only in Wi-Fi setup.") }
                Section(header: Text("Device Info")) {
                    TextField("Friendly Name", text: $vm.pairName)
                    TextField("6-Digit App Code", text: $vm.pairCode).keyboardType(.numberPad)
                    Toggle("Share teams and Spotify with my other tickers", isOn: $shareWithApp)
                }
                Section(header: Text("Ticker Wi-Fi")) {
                    Text("Optional. Set up the ticker network before pairing this ticker.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Button {
                        vm.wifiSetupCode = ""
                        showWiFiSetup = true
                    } label: {
                        Label("Set Up Ticker Wi-Fi", systemImage: "wifi")
                    }
                }
                Button("Pair with Code") {
                    vm.pairError = nil
                    vm.pairTicker(
                        code: vm.pairCode,
                        name: vm.pairName.isEmpty ? "My Ticker" : vm.pairName,
                        shareGroup: shareWithApp
                    )
                }.disabled(vm.pairCode.count < 6)
                if let err = vm.pairError { Section { Text(err).foregroundColor(.red) } }
            }
            .navigationTitle("Pair Ticker")
            .navigationBarItems(trailing: Button("Close") { isPresented = false })
            .onAppear { shareWithApp = vm.canShareTickerGroup }
            .sheet(isPresented: $showWiFiSetup) {
                WiFiSetupView(vm: vm, isPresented: $showWiFiSetup)
            }
            .alert(isPresented: $vm.showPairSuccess) {
                Alert(title: Text("Success"), message: Text("Ticker paired successfully!"), dismissButton: .default(Text("OK")) { isPresented = false })
            }
        }
    }
}
