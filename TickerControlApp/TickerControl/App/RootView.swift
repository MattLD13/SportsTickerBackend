import Foundation
import SwiftUI

/// The four screens, the floating tab bar, and the first-run setup.
struct RootView: View {
    @Environment(TickerStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab = Tab.home

    enum Tab: CaseIterable { case home, modes, teams, settings }

    var body: some View {
        ZStack(alignment: .bottom) {
            AppBackground()

            TabView(selection: $tab) {
                HomeView().tag(Tab.home)
                ModesView().tag(Tab.modes)
                TeamsView().tag(Tab.teams)
                SettingsView().tag(Tab.settings)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .ignoresSafeArea(.container, edges: .bottom)

            if store.needsSetup {
                FirstRunSetupView().ignoresSafeArea().zIndex(10)
            }

            HStack {
                TabButton(icon: "house.fill", label: "Home", tab: .home, selection: $tab)
                TabButton(icon: "slider.horizontal.3", label: "Modes", tab: .modes, selection: $tab)
                TabButton(icon: "tshirt.fill", label: "Teams", tab: .teams, selection: $tab)
                TabButton(icon: "cpu", label: "Settings", tab: .settings, selection: $tab)
            }
            .padding(12).background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .padding(.horizontal, 20).padding(.bottom, 20)
            .shadow(color: .black.opacity(0.3), radius: 10, x: 0, y: 5)
        }
        .preferredColorScheme(.dark)
        .onOpenURL { url in Task { await store.handleSpotifyCallback(url) } }
        .onChange(of: scenePhase, initial: true) { _, phase in
            if phase == .active { store.start() } else { store.stop() }
        }
        .alert("Ticker request failed", isPresented: Binding(
            get: { store.operationError != nil },
            set: { if !$0 { store.operationError = nil } }
        )) {
            Button("OK") { store.operationError = nil }
        } message: {
            Text(store.operationError ?? "")
        }
    }
}

private struct TabButton: View {
    let icon: String
    let label: String
    let tab: RootView.Tab
    @Binding var selection: RootView.Tab

    var body: some View {
        let selected = selection == tab
        Button { selection = tab } label: {
            VStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 20))
                Text(label).font(.caption2)
            }
            .frame(maxWidth: .infinity)
            .foregroundColor(selected ? .white : .gray)
            .padding(.vertical, 8)
            .background(selected ? Color.white.opacity(0.15) : Color.clear)
            .cornerRadius(12)
        }
    }
}
