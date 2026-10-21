# Stock autocomplete and Mini recovery

Date: 2026-10-20

## Owners and replaced paths

The stock symbol catalog owns confirmed provider symbol searches and its bounded cache.
The iOS custom editor replaces syntax-only additions with company and symbol search results.
The stock source prioritizes missing custom quotes and publishes each successful quote immediately.
The snapshot scheduler reads shared stock quotes every two seconds instead of every 30 seconds.
The Mini replaces the separate stock logo canvas with the production sports logo canvas.
The Mini clears obsolete logo plans when the selected list becomes empty.
Startup no longer waits up to ten seconds for USB serial before preparing the display.
It waits at most 250 milliseconds. The display validation and rollback checks remain unchanged.

## Evidence

Focused provider and API checks validate search results, exact-match order, caching, and sanitized failures.
An injected quote test adds ZZZ while AAA is being read.
The source reads ZZZ before BBB and publishes ZZZ while the market sweep is still running.
The Mini candidate requires a successful OTA boot, continued heartbeats, and live logo rendering before completion.
Version 1.3.37 remains quarantined. The previous working image is 1.3.36.
Candidate version: mini-1.3.38.


## Validation before publication

The Mac passes the Swift package tests and the Debug simulator app build.
The production esp32s3 build passes.
Native stock rendering and immutable sprite routes remain part of the full release checks.
The rebuilt layout gallery identifies mini-1.3.38 and passes provenance verification.
Provider search uses the Finnhub symbol lookup contract with the US exchange filter.
Reference: https://github.com/Finnhub-Stock-API/finnhub-go/blob/master/api/openapi.yaml

The full suite passes 1,134 tests, with ten skips.
The critical suite passes 783 tests, with ten skips and 351 deselected tests.
The signed Release phone build passes on the Mac.
