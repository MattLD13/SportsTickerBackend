# iOS controller

The app uses the routes in `docs/api.md`.

## Layout

- `TickerControl/Core/` holds the models, the API client, and `TickerStore`. It has no UIKit or SwiftUI code.
  The Swift package `TickerControlCore` builds it, so `swift test` checks it on macOS and Linux.
- `TickerControl/App/` holds the app entry point and the iOS services: Keychain, location, Bluetooth, and web sign-in.
- `TickerControl/Views/` holds the screens. A view reads `TickerStore` from the environment and calls its methods.
- `TickerControl/Preview/` holds the DEBUG schedule preview for `ScheduleUITests`.

## Rules

- `TickerStore` owns the app state and every user action. Views keep only local edit state.
- A network result applies only to the server, ticker, and token that sent the request. Use `TickerStore.Scope`.
- If a server payload changes, change its model in `Core/Models/` and `TickerControlTests/ContractTests.swift` together.
- Keep the UserDefaults keys and the Keychain services in `Core/State/Session.swift`. Installed apps keep their pairings with them.
- Keep business facts in the server contract. Do not parse display strings to recover state.
- Keep the selected mode, the pinned game, the pairing flow, and the overlay behavior.

## Checks

Run `swift test --package-path TickerControlApp` for the core.
Use the iOS workflow or a supported Xcode environment for the app build.
