import Foundation
import SwiftUI

/// Edit the custom stock list of one ticker: search by company or symbol, then add, move, or delete stocks.
struct CustomStockEditor: View {
    static let limit = 30

    @Environment(\.dismiss) private var dismiss
    @State private var symbols: [String]
    @State private var input = ""
    @State private var inputError: String?
    @State private var results: [StockSymbol] = []
    @State private var searching = false
    let search: (String) async throws -> [StockSymbol]
    let save: ([String]) -> Void

    init(symbols: [String], search: @escaping (String) async throws -> [StockSymbol], save: @escaping ([String]) -> Void) {
        _symbols = State(initialValue: symbols)
        self.search = search
        self.save = save
    }

    private var query: String { input.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var exactMatch: StockSymbol? { results.first { $0.symbol == query.uppercased() } }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("Search by company name or symbol. Tap a result to add it, or edit your list below.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    HStack {
                        TextField("Company or symbol", text: $input)
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .submitLabel(.done)
                            .onSubmit { if let exactMatch { add(exactMatch) } }
                            .accessibilityIdentifier("custom-stock-input")
                        Button("Add") { if let exactMatch { add(exactMatch) } }
                            .disabled(exactMatch == nil)
                    }
                    if searching { ProgressView("Searching stocks...") }
                    ForEach(results) { stock in
                        Button { add(stock) } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(stock.symbol).bold()
                                    Text(stock.name).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Image(systemName: symbols.contains(stock.symbol) ? "checkmark.circle.fill" : "plus.circle.fill")
                            }
                        }
                        .disabled(symbols.contains(stock.symbol))
                        .accessibilityIdentifier("stock-result-\(stock.symbol)")
                    }
                    if !searching && !input.isEmpty && results.isEmpty && inputError == nil {
                        Text("No matching stocks. Try the company name or another symbol.").font(.caption)
                    }
                    if let inputError { Text(inputError).foregroundStyle(.red) }
                } header: { Text("Find a stock") }
                Section {
                    if symbols.isEmpty { Text("Your custom list is empty.").foregroundStyle(.secondary) }
                    ForEach(symbols, id: \.self) { Text($0) }
                        .onDelete { symbols.remove(atOffsets: $0) }
                        .onMove { symbols.move(fromOffsets: $0, toOffset: $1) }
                } header: {
                    Text("Stocks (\(symbols.count)/\(Self.limit))")
                } footer: {
                    Text("Prices update during market hours. Saving an empty list switches this ticker to Tech / AI.")
                }
                if !symbols.isEmpty {
                    Section {
                        ShareLink(item: symbols.joined(separator: ", ")) { Label("Share stock symbols", systemImage: "square.and.arrow.up") }
                        Text("Share these symbols, then search and add them on another ticker.").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .task(id: input) { await runSearch() }
            .navigationTitle("Custom Stocks")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save(symbols); dismiss() }
                        .disabled(!query.isEmpty)
                        .accessibilityIdentifier("save-custom-stocks")
                }
                ToolbarItem(placement: .bottomBar) { EditButton() }
            }
        }
    }

    private func add(_ stock: StockSymbol) {
        guard !symbols.contains(stock.symbol) else { inputError = "This stock is already in your list."; return }
        guard symbols.count < Self.limit else { inputError = "A custom list can contain up to \(Self.limit) stocks."; return }
        withAnimation(.snappy(duration: 0.15)) { symbols.append(stock.symbol) }
        input = ""
        results = []
        inputError = nil
    }

    /// Search 120 ms after the last keystroke. A new keystroke cancels the earlier search.
    private func runSearch() async {
        results = []
        inputError = nil
        let query = query
        guard !query.isEmpty else { searching = false; return }
        searching = true
        do {
            try await Task.sleep(for: .milliseconds(120))
            let found = try await search(query)
            try Task.checkCancellation()
            results = found
            searching = false
        } catch is CancellationError {
            return
        } catch {
            guard !Task.isCancelled else { return }
            inputError = "Stock search is unavailable. Try again before adding this stock."
            searching = false
        }
    }
}
