"""Hold feature manifests, playlists, and records. Compose the screens of each ticker.

The hub has no I/O. The supervisor feeds it worker messages. The device streams
read its compositions. Two callbacks report changes:

- `on_wanted(feature, subs)` when the subscription set of a feature changes.
- `on_screens(ticker_id, composition)` when the screens of a ticker change.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ticker3.contract import ContractError
from ticker3.contract.manifest import validate_manifest
from ticker3.contract.records import Reference, reference, references, validate_record
from ticker3.contract.settings import expand, normalize, normalize_config, subscription_key
from ticker3.contract.wire import canonical

from .builtin import Builtin

APP_ID = re.compile(r"^[a-z0-9]{1,16}$")
Key = tuple[str, str]


@dataclass(frozen=True)
class App:
    id: str
    feature: str
    settings: dict[str, Any]


@dataclass(frozen=True)
class Composition:
    screens: tuple[dict[str, Any], ...]
    overlays: tuple[dict[str, Any], ...]
    errors: tuple[str, ...] = ()
    next_change: float | None = None

    def same_as(self, other: Composition | None) -> bool:
        return other is not None and canonical([self.screens, self.overlays, self.errors]) == canonical(
            [other.screens, other.overlays, other.errors])


@dataclass
class _Plan:
    app: App
    keys: tuple[str, ...] = ()
    configs: tuple[dict[str, Any], ...] = ()
    filters: dict[str, tuple[str, ...]] = field(default_factory=dict)
    view: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Hub:
    def __init__(self, *, clock: Callable[[], float] = time.time,
                 on_wanted: Callable[[str, dict[str, dict[str, Any]]], None] | None = None,
                 on_screens: Callable[[str, Composition], None] | None = None) -> None:
        self.clock = clock
        self.on_wanted = on_wanted or (lambda feature, subs: None)
        self.on_screens = on_screens or (lambda ticker, composition: None)
        self.manifests: dict[str, dict[str, Any]] = {}
        self.builtins: dict[str, Builtin] = {}
        self.playlists: dict[str, tuple[App, ...]] = {}
        self._ticker_values: dict[str, dict[str, Any]] = {}
        self._plans: dict[str, list[_Plan]] = {}
        self._records: dict[Key, dict[str, dict[str, Any]]] = {}
        self._received: dict[tuple[str, str, str], float] = {}
        self._app_users: dict[Key, set[str]] = defaultdict(set)
        self._ref_targets: dict[Key, dict[Key, dict[str, Any]]] = {}
        self._ref_users: dict[Key, set[Key]] = defaultdict(set)
        self._ref_keys: dict[str, Key | None] = {}
        self._ref_configs: dict[str, dict[str, Any] | None] = {}
        self._sent_wanted: dict[str, dict[str, dict[str, Any]]] = {}
        self._compositions: dict[str, Composition] = {}

    # Features

    def register(self, manifest: dict[str, Any], *, builtin: Builtin | None = None) -> None:
        """Accept the manifest of a feature. A new manifest replaces the old one."""
        manifest = validate_manifest({**manifest, "templates": list(manifest["templates"].values())}
                                     if isinstance(manifest.get("templates"), dict) else manifest)
        feature = manifest["feature"]
        if self.manifests.get(feature) is not None and canonical(self.manifests[feature]) == canonical(manifest):
            return
        self.manifests[feature] = manifest
        if builtin is not None:
            self.builtins[feature] = builtin
        self._ref_keys.clear()
        self._ref_configs.clear()
        for ticker, apps in self.playlists.items():
            if any(app.feature == feature for app in apps):
                self._plan(ticker)
        for source in list(self._ref_targets):
            self._index_references(source)
        self._update_wanted()
        self._compose(self.playlists)

    def templates(self) -> dict[str, dict[str, Any]]:
        """Return each template of each registered feature."""
        return {identifier: template for manifest in self.manifests.values() for identifier, template in manifest["templates"].items()}

    # Playlists

    def set_playlist(self, ticker: str, apps: Iterable[App]) -> None:
        """Replace the apps of one ticker. Raise ContractError for an unknown feature or invalid settings."""
        apps = tuple(apps)
        identifiers = [app.id for app in apps]
        if len(set(identifiers)) != len(identifiers) or not all(APP_ID.match(identifier) for identifier in identifiers):
            raise ContractError("each app needs a unique id of 1 to 16 lower-case letters or digits")
        for app in apps:
            manifest = self.manifests.get(app.feature)
            if manifest is None:
                raise ContractError(f"unknown feature {app.feature!r}")
            normalize(manifest["settings"], app.settings)
        self.playlists[ticker] = apps
        self._plan(ticker)
        self._update_wanted()
        self._compose([ticker])

    def set_ticker_values(self, ticker: str, values: dict[str, Any]) -> None:
        """Set values that each screen of one ticker gets as `ticker.<name>`, such as the time zone."""
        self._ticker_values[ticker] = {f"ticker.{name}": value for name, value in values.items()}
        self._compose([ticker])

    def remove_ticker(self, ticker: str) -> None:
        self._ticker_values.pop(ticker, None)
        self.playlists.pop(ticker, None)
        self._unplan(ticker)
        self._compositions.pop(ticker, None)
        self._update_wanted()

    def wanted(self, feature: str) -> dict[str, dict[str, Any]]:
        """Return the subscriptions of one feature: those of apps and those of references."""
        subs: dict[str, dict[str, Any]] = {}
        for plans in self._plans.values():
            for plan in plans:
                if plan.app.feature == feature and plan.error is None:
                    subs.update(zip(plan.keys, plan.configs, strict=True))
        for targets in self._ref_targets.values():
            for (target_feature, key), config in targets.items():
                if target_feature == feature:
                    subs[key] = config
        return subs

    # Records

    def apply(self, feature: str, message: dict[str, Any]) -> bool:
        """Apply one validated sync or delta. Return False if the core does not want that subscription."""
        key = message["sub"]
        if key not in self._sent_wanted.get(feature, {}):
            return False
        now = self.clock()
        if message["t"] == "sync":
            records = {record["id"]: record for record in message["records"]}
            for identifier in self._records.get((feature, key), {}):
                if identifier not in records:
                    self._received.pop((feature, key, identifier), None)
        else:
            records = dict(self._records.get((feature, key), {}))
            for identifier in message["remove"]:
                records.pop(identifier, None)
                self._received.pop((feature, key, identifier), None)
            records.update((record["id"], record) for record in message["upsert"])
        for record in (message["records"] if message["t"] == "sync" else message["upsert"]):
            self._received[(feature, key, record["id"])] = now
        self._records[(feature, key)] = records
        self._index_references((feature, key))
        self._update_wanted()
        self._compose(self._users((feature, key)))
        return True

    def tick(self) -> None:
        """Compose again each ticker whose records expired since its last composition."""
        now = self.clock()
        due = [ticker for ticker, composition in self._compositions.items()
               if composition.next_change is not None and composition.next_change <= now]
        if due:
            self._compose(due)

    def composition(self, ticker: str) -> Composition:
        composition = self._compositions.get(ticker)
        if composition is None:
            composition = self._compose_one(ticker)
            self._compositions[ticker] = composition
        return composition

    # Planning

    def _plan(self, ticker: str) -> None:
        self._unplan(ticker)
        plans = []
        for app in self.playlists.get(ticker, ()):
            plan = _Plan(app)
            manifest = self.manifests.get(app.feature)
            try:
                if manifest is None:
                    raise ContractError(f"feature {app.feature} is not registered")
                expansion = expand(manifest["settings"], normalize(manifest["settings"], app.settings))
            except ContractError as error:
                plan.error = str(error)
            else:
                plan.configs = expansion.configs
                plan.keys = tuple(subscription_key(config) for config in expansion.configs)
                plan.filters, plan.view = expansion.filters, expansion.view
                for key in plan.keys:
                    self._app_users[(app.feature, key)].add(ticker)
            plans.append(plan)
        self._plans[ticker] = plans

    def _unplan(self, ticker: str) -> None:
        for plan in self._plans.pop(ticker, ()):
            for key in plan.keys:
                users = self._app_users.get((plan.app.feature, key))
                if users is not None:
                    users.discard(ticker)
                    if not users:
                        del self._app_users[(plan.app.feature, key)]

    def _index_references(self, source: Key) -> None:
        for target in self._ref_targets.pop(source, {}):
            self._ref_users[target].discard(source)
        targets = {}
        for record in self._records.get(source, {}).values():
            for _, ref in references(record):
                target = self._reference_key(ref)
                if target is not None:
                    targets[target] = self._ref_config(ref)
        if targets:
            self._ref_targets[source] = targets
            for target in targets:
                self._ref_users[target].add(source)

    def _reference_key(self, ref: Reference) -> Key | None:
        if ref.identity not in self._ref_keys:
            manifest = self.manifests.get(ref.feature)
            try:
                config = normalize_config(manifest["settings"], ref.config) if manifest else None
            except ContractError:
                config = None
            self._ref_keys[ref.identity] = None if config is None else (ref.feature, subscription_key(config))
            self._ref_configs[ref.identity] = config
        return self._ref_keys[ref.identity]

    def _ref_config(self, ref: Reference) -> dict[str, Any]:
        return self._ref_configs[ref.identity]

    def _update_wanted(self) -> None:
        for feature in self.manifests:
            subs = self.wanted(feature)
            if canonical(subs) == canonical(self._sent_wanted.get(feature, {})):
                continue
            self._sent_wanted[feature] = subs
            for (record_feature, key) in [stored for stored in self._records if stored[0] == feature and stored[1] not in subs]:
                del self._records[(record_feature, key)]
                for target in self._ref_targets.pop((record_feature, key), {}):
                    self._ref_users[target].discard((record_feature, key))
            builtin = self.builtins.get(feature)
            if builtin is None:
                self.on_wanted(feature, subs)
                continue
            for key, config in subs.items():
                if (feature, key) not in self._records:
                    records = [validate_record(record) for record in builtin.records(config)]
                    self.apply(feature, {"t": "sync", "sub": key, "records": records})

    def _users(self, key: Key) -> set[str]:
        users = set(self._app_users.get(key, ()))
        for source in self._ref_users.get(key, ()):
            users.update(self._app_users.get(source, ()))
        return users

    # Composition

    def _compose(self, tickers: Iterable[str]) -> None:
        for ticker in list(tickers):
            if ticker not in self.playlists:
                continue
            composition = self._compose_one(ticker)
            previous = self._compositions.get(ticker)
            self._compositions[ticker] = composition
            if not composition.same_as(previous):
                self.on_screens(ticker, composition)

    def _compose_one(self, ticker: str) -> Composition:
        now = self.clock()
        screens, overlays, errors, next_change = [], [], [], None
        for plan in self._plans.get(ticker, ()):
            if plan.error:
                errors.append(f"{plan.app.id}: {plan.error}")
                continue
            templates = self.manifests[plan.app.feature]["templates"]
            found = []
            for position, key in enumerate(plan.keys):
                for record in self._records.get((plan.app.feature, key), {}).values():
                    found.append((record["order"], position, record["id"], key, record))
            for _, _, _, key, record in sorted(found, key=lambda item: item[:3]):
                if record["template"] not in templates or not _passes(record, plan.filters):
                    continue
                ends = record["expires_at"]
                if record["overlay"] is not None:
                    ends = self._received[(plan.app.feature, key, record["id"])] + record["overlay"]["ttl"]
                if ends is not None:
                    if ends <= now:
                        continue
                    next_change = ends if next_change is None else min(next_change, ends)
                screen = {"id": f"{plan.app.id}/{record['id']}", "template": record["template"],
                          "values": {**self._values(record, plan.view), **self._ticker_values.get(ticker, {})}}
                (overlays if record["overlay"] is not None else screens).append(screen)
        return Composition(tuple(screens), tuple(overlays), tuple(errors), next_change)

    def _values(self, record: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
        values = {}
        for name, value in record["values"].items():
            ref = reference(value)
            if ref is None:
                values[name] = value
                continue
            target = self._reference_key(ref)
            linked = self._records.get(target, {}).get(ref.record) if target else None
            if linked is None:
                continue
            for linked_name, linked_value in linked["values"].items():
                if not isinstance(linked_value, dict):
                    values[f"{name}.{linked_name}"] = linked_value
        values.update((f"app.{name}", value if not isinstance(value, list) else ",".join(map(str, value)))
                      for name, value in view.items())
        return values


def _passes(record: dict[str, Any], filters: dict[str, tuple[str, ...]]) -> bool:
    tags = set(record["tags"])
    return all(tags.intersection(allowed) for allowed in filters.values())
