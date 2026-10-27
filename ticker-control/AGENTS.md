# iOS controller

Use explicit V2 models and routes.
If a shared payload changes, update its model and contract checks together.
Read `TickerControl/Models/TickerContentModels.swift` and `TickerControlTests/ContractModelsTests.swift` for contract work.
Preserve the selected mode, pinned game state, pairing flow, and overlay behavior.
Keep business facts in the server contract. Do not parse display strings to recover state.
Use the iOS workflow or a supported Xcode environment for app builds.
