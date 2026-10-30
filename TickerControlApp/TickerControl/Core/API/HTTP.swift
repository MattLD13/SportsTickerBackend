import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Sends one request and returns the body and the HTTP response.
protocol HTTPTransport {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

struct URLSessionTransport: HTTPTransport {
    var session: URLSession = .shared

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        return (data, response)
    }
}

/// A failed request. The server sends `{"error": {"code": "...", "message": "..."}}` with its status.
enum APIError: LocalizedError, Equatable {
    case invalidServerURL
    case notPaired
    case transport(String)
    case server(status: Int, code: String?, message: String?)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .invalidServerURL: return "The server URL is not valid."
        case .notPaired: return "Pair this ticker before you change it."
        case .transport(let message): return message
        case .server(let status, _, let message):
            return "The server rejected the request (HTTP \(status))." + (message.map { " \($0)" } ?? "")
        case .invalidResponse: return "The server returned an invalid response."
        }
    }

    /// Read the structured error of a failed response. A message longer than 200 characters is cut.
    static func server(status: Int, body: Data) -> APIError {
        struct Envelope: Decodable { struct Detail: Decodable { let code: String?; let message: String? }; let error: Detail }
        let detail = try? JSONDecoder().decode(Envelope.self, from: body).error
        let message = detail?.message?.trimmingCharacters(in: .whitespacesAndNewlines)
        return .server(status: status, code: detail?.code, message: message.flatMap { $0.isEmpty ? nil : String($0.prefix(200)) })
    }
}

/// A response that the app does not read.
struct Empty: Decodable {}

/// Sends the endpoints of the ticker server.
final class APIClient {
    private let transport: any HTTPTransport
    private(set) var baseURL: String

    init(baseURL: String, transport: any HTTPTransport = URLSessionTransport()) {
        self.baseURL = APIClient.normalized(baseURL)
        self.transport = transport
    }

    func setBaseURL(_ value: String) { baseURL = APIClient.normalized(value) }

    static func normalized(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    func request<Response>(_ endpoint: Endpoint<Response>, token: String?) throws -> URLRequest {
        guard var components = URLComponents(string: baseURL + endpoint.path) else { throw APIError.invalidServerURL }
        if !endpoint.query.isEmpty { components.queryItems = endpoint.query.map { URLQueryItem(name: $0.0, value: $0.1) } }
        guard let url = components.url, url.scheme != nil else { throw APIError.invalidServerURL }
        var request = URLRequest(url: url)
        request.httpMethod = endpoint.method
        request.timeoutInterval = endpoint.timeout
        if endpoint.authorized {
            guard let token else { throw APIError.notPaired }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body = endpoint.body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
        }
        return request
    }

    func send<Response>(_ endpoint: Endpoint<Response>, token: String? = nil) async throws -> Response {
        let request = try request(endpoint, token: token)
        let data: Data
        let response: HTTPURLResponse
        do {
            (data, response) = try await transport.send(request)
        } catch let error as APIError {
            throw error
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
        guard (200...299).contains(response.statusCode) else { throw APIError.server(status: response.statusCode, body: data) }
        do {
            return try endpoint.decode(data)
        } catch {
            throw APIError.invalidResponse
        }
    }
}
