import SwiftUI

@main
struct TickerControlApp: App {
    var body: some Scene {
        WindowGroup {
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("-scheduleInteractionTest") {
                ScheduleInteractionTestView()
            } else {
                ContentView()
            }
            #else
            ContentView()
            #endif
        }
    }
}
