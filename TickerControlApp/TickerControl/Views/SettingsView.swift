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

struct SettingsView: View {
    @ObservedObject var vm: TickerViewModel
    @State private var showPairing = false
    @State private var rebootConfirm = false
    @State private var showRawJSON = false

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                HStack { Text("Settings").font(.system(size: 34, weight: .bold)).foregroundColor(.white); Spacer() }.padding(.horizontal).padding(.top, 80)

                VStack(alignment: .leading, spacing: 10) {
                    Text("CONNECTION").font(.caption).bold().foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Server URL").font(.caption).foregroundColor(.gray)
                        TextField("https://...", text: $vm.serverURL).textFieldStyle(.plain).padding(10).background(Color.black.opacity(0.2)).cornerRadius(8).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1))).foregroundColor(.white)
                            .onSubmit { vm.fetchData(); vm.fetchLeagueOptions(); vm.fetchDevices() }
                    }.padding().liquidGlass()
                }.padding(.horizontal)

                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("MY DEVICES").font(.caption).bold().foregroundStyle(.secondary)
                        Spacer()
                        Button(action: { showPairing = true }) {
                            Text("Pair New").font(.caption).bold().foregroundColor(.blue)
                        }
                    }
                    if vm.devices.isEmpty {
                        Text("No devices paired.").frame(maxWidth: .infinity).padding().liquidGlass().foregroundStyle(.secondary)
                    } else {
                        ForEach(vm.devices) { device in
                            DeviceRow(device: device, vm: vm)
                        }
                    }
                }.padding(.horizontal)

                if vm.state.show_debug_options == true {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("DEBUG").font(.caption).bold().foregroundStyle(.secondary)
                        VStack(spacing: 0) {
                            Toggle("Debug Mode", isOn: Binding(
                                get: { vm.state.debug_mode },
                                set: { val in
                                    vm.isEditing = true
                                    vm.state.debug_mode = val
                                    vm.sendDebug()
                                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { vm.isEditing = false }
                                }
                            ))
                            .padding()
                            .toggleStyle(SwitchToggleStyle(tint: .orange))

                            Divider().background(Color.white.opacity(0.1))

                            Button("View Raw Server JSON") { showRawJSON = true }
                                .padding()
                                .foregroundColor(.blue)

                        }.liquidGlass().clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }.padding(.horizontal)
                }

                VStack(spacing: 12) {
                    Button {
                        if rebootConfirm {
                            vm.reboot()
                            rebootConfirm = false
                        } else {
                            rebootConfirm = true
                            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { rebootConfirm = false }
                        }
                    } label: {
                        Label(rebootConfirm ? "Tap Again to Confirm" : "Reboot Ticker", systemImage: rebootConfirm ? "exclamationmark.triangle.fill" : "power")
                            .frame(maxWidth: .infinity).padding()
                            .background(rebootConfirm ? Color.orange.opacity(0.2) : Color.red.opacity(0.2))
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .foregroundColor(rebootConfirm ? .orange : .red)
                            .animation(.easeInOut, value: rebootConfirm)
                    }
                }.padding(.horizontal)

                Spacer(minLength: 120)
            }
        }
        .sheet(isPresented: $showPairing) {
            PairingView(vm: vm, isPresented: $showPairing)
        }
        .sheet(isPresented: $showRawJSON) {
            ScrollView { Text(String(describing: vm.games)).font(.caption.monospaced()).padding() }.presentationDetents([.medium])
        }
    }
}
