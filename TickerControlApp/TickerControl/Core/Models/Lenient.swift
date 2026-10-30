import Foundation

/// A coding key from a string, for reading content fields by name.
struct FieldKey: CodingKey {
    let stringValue: String
    var intValue: Int? { nil }
    init(_ value: String) { stringValue = value }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}

/// Content data comes from many providers, so a field can be text or a number. These readers accept both.
extension KeyedDecodingContainer where Key == FieldKey {
    func text(_ name: String) -> String? {
        let key = FieldKey(name)
        if let value = try? decode(String.self, forKey: key) { return value }
        if let value = try? decode(Int.self, forKey: key) { return String(value) }
        if let value = try? decode(Double.self, forKey: key) { return String(format: "%.0f", value) }
        return nil
    }

    func int(_ name: String) -> Int? {
        let key = FieldKey(name)
        if let value = try? decode(Int.self, forKey: key) { return value }
        if let value = try? decode(Double.self, forKey: key), value.isFinite { return Int(value) }
        return nil
    }

    func double(_ name: String) -> Double? {
        let key = FieldKey(name)
        if let value = try? decode(Double.self, forKey: key) { return value }
        if let value = try? decode(String.self, forKey: key) { return Double(value) }
        return nil
    }

    func bool(_ name: String) -> Bool? { try? decode(Bool.self, forKey: FieldKey(name)) }

    func object(_ name: String) -> KeyedDecodingContainer<FieldKey>? {
        try? nestedContainer(keyedBy: FieldKey.self, forKey: FieldKey(name))
    }

    func value<T: Decodable>(_ type: T.Type, _ name: String) -> T? { try? decode(type, forKey: FieldKey(name)) }

    /// Decode each element of an array of objects with `read`. An element that is not an object is skipped.
    func objects<T>(_ name: String, _ read: (KeyedDecodingContainer<FieldKey>) -> T) -> [T]? {
        guard var array = try? nestedUnkeyedContainer(forKey: FieldKey(name)) else { return nil }
        var result: [T] = []
        while !array.isAtEnd {
            if let element = try? array.nestedContainer(keyedBy: FieldKey.self) { result.append(read(element)) }
            else { _ = try? array.decode(Discard.self) }
        }
        return result
    }
}

private struct Discard: Decodable {}
