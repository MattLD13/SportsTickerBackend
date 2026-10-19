# Hockey headers, college overtime, and Mini boot registration

Date: 2026-10-16

Mini release: `mini-1.3.10`

## Hockey manpower

The shared NHL projection now publishes `manpower.powerPlayLabel`.
The label puts the team with the advantage first, including home power plays.
Examples include `5v4`, `5v3`, and `4v3`.
The Mini and both Pi layouts consume this field instead of drawing `PP`.
The scrolling layout places the label above the team with the advantage.
The pinned Pi layout places its badge in the header near that team's score.
The Mini reserves a narrower center header span to separate the clock from three-character badges.
Empty-net badges retain their explicit state and precedence.

## Football layout and overtime

Compact goal-to-go footers use the remaining width to widen their word spaces.
`2ND & GOAL` occupies the full 28-pixel Mini footer.

The live ECU–UAB capture reports period five, `0:00`, and `STATUS_IN_PROGRESS`.
The former zero-clock rule incorrectly produces `OT END`.
The shared status projection now treats FBS and FCS extra periods as untimed.
It displays `OT`, `OT2`, and later periods until the provider reports a final result.
Timed regulation periods retain their period-end labels.

The [NCAA statistics manual](https://fs.ncaa.org/Docs/stats/Stats_Manuals/Football.pdf) describes college overtime periods as untimed.
The captured ESPN input is `tests/fixtures/display/fbs_untimed_overtime.json`.

## Boot registration failure

The Mini reports `REG -1` while Wi-Fi remains connected.
The initial error occurs before a TLS handshake and before an HTTP response.
Instrumented boot checks confirm that DNS returns no address from the guest network's `8.8.8.8` resolver.
Both the Arduino resolver and `getaddrinfo` time out.
One retry sequence takes over a minute. A later boot still fails after 100 seconds.

The Mini now resolves backend names through verified HTTPS requests to Cloudflare's public resolver.
This replaces UDP name lookup for backend requests, sprite downloads, firmware manifests, and firmware binaries.
It uses Cloudflare's published `1.1.1.1` bootstrap address and verifies the `cloudflare-dns.com` certificate and hostname.
The client also verifies the original backend hostname after resolving its address.
The implementation never disables certificate validation and never pins the backend to a fixed IP address.

The resolver caches complete IPv4 answers only until their shortest returned TTL expires.
The cache respects zero TTL values and clock rollover.
The parser rejects DNS error replies, truncated replies, mismatched questions, and invalid IPv4 data.
The cache holds one hostname and one answer, under the existing network mutex.

If name lookup or connection attempts fail, the Mini renews its saved Wi-Fi connection.
Startup registration renews after its first failure. Normal operation requires three consecutive failures.
A 30-second minimum interval limits repeated renewals.
A successful HTTP response clears the failure count.
The runtime clears the disconnected timeout after reassociation.
New Wi-Fi credentials cancel recovery for the former connection.

Serial and heartbeat diagnostics include registration status, error stage, resolver method, resolved address, and renewal count.
The registration screen identifies DNS, connection, and TLS failures separately.

Protocol reference: [Cloudflare DNS over HTTPS JSON](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/).

## Verification

- The full Python suite passes 620 tests. The critical suite passes 293 tests.
- Canonical manpower vectors cover both teams and `5v4`, `5v3`, and `4v3`.
- Native pixel checks verify Mini badges, clear header gutters, and full-width goal-to-go text.
- Physical frame captures match all 6,144 submitted RGB bytes for the changed Mini layouts.
- Production Pi renderers generate real 384x32 scrolling and pinned frames.
- A captured live college football status verifies active overtime despite a zero game clock.
- An injected three-query DNS failure renews Wi-Fi and restores HTTP 200 on the physical Mini.
- HTTPS DNS passes three real-device boots, reaching registration and live data in 24.16, 24.18, and 23.84 seconds.
- Native DNS checks cover answer validation, TTL expiry, zero TTL, and clock rollover.

## Change notes

Owner: The shared sports projection owns manpower labels and untimed overtime status.
Each renderer owns spacing and placement. The Mini TLS adapter owns verified HTTPS name resolution.
The network recovery state machine owns renewal thresholds and timing.

Former path: Remove literal `PP` badges and the college-overtime zero-clock end rule.
Replace UDP backend name lookup and indefinite retries on an unhealthy Wi-Fi association.

Real input: Canonical NHL manpower facts, captured ESPN overtime data, guest-network DNS failures, and physical Mini boot telemetry.
Real output: Correct manpower headers, readable Mini spacing, active college overtime labels, and repeatable successful boot registration.
