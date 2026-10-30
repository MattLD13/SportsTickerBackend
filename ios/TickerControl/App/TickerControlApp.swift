import Foundation
import SwiftUI

@main
struct ios: App {
    @State private var store: TickerStore

    init() {
        URLCache.shared = URLCache(memoryCapacity: 512_000, diskCapacity: 1_000_000, diskPath: nil)
        #if DEBUG
        if SchedulePreview.isRequested {
            _store = State(initialValue: SchedulePreview.store())
            return
        }
        #endif
        let session = Session(values: UserDefaults.standard, credentials: KeychainCredentials())
        _store = State(initialValue: TickerStore(session: session, platform: PhonePlatform()))
    }

    var body: some Scene {
        WindowGroup {
            Group {
                #if DEBUG
                if SchedulePreview.isRequested {
                    SchedulePreview()
                } else {
                    RootView()
                }
                #else
                RootView()
                #endif
            }
            .environment(store)
        }
    }
}
