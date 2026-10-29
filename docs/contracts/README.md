# Offline contracts

These schemas describe the current API boundary. `docs/api.md` lists the routes. They do not install runtime validation or generate clients.

`device-registration-request.json` owns the registration request description. `device-registration.json` references that schema for the existing documentation path.
The former schema required `name` and `metadata`. The route defaults those fields and accepts `pairing_code` and a null profile.
The response schema describes the normalized ticker and nullable pairing code.

Hardware profile request parsing applies defaults and scalar coercion. It accepts the `normal` alias and ignores unknown profile fields.
The input schema preserves this parser envelope. The response schema describes the normalized profile.
The manifest input schema preserves coercion and ignored fields. The response schema describes normalized HTTPS URLs, image bounds, and hashes.
Input schemas do not duplicate Python coercion rules. Offline model tests prove representative coercion and normalization.

Schedule create requests and patch requests have separate schemas. Patch requests accept empty objects.
Request patterns permit case normalization and surrounding whitespace. Repeated request weekdays remain valid and produce sorted, distinct response weekdays.
Schedule responses retain nullable filters, rule identifiers, condition identifiers, scheduled modes, and override deadlines.
The schedule service owns interval ordering, overlap checks, capability checks, and changes that depend on existing rules.
JSON Schema cannot compare two minute fields or query existing blocks. The offline tests exercise interval ordering through the domain model.

The display schema describes the shared envelope and content records. Pairing remains an effective mode.
Family data, health errors, and snapshot staleness remain extensible because the current projection copies those values.
The display schema accepts both the projection output and the enriched route output.
Route metadata has typed profile, schedule, and pairing fields when present.
It does not require route metadata on the lower projection output.

Fixtures use current routes and serializers with clock `1786752000.0`. Pairing codes use `123456` to remove random entropy.
The tests exercise real registration routes and model normalization. They run without network calls.
The local validator supports only the keywords used here. It rejects unsupported keywords and resolves references from this directory.
It is test infrastructure, not a general JSON Schema implementation. No dependency changes are required.

Run the focused checks:

```powershell
python -m py_compile tests/python/protocol/test_offline_contracts.py
python -m pytest tests/python/protocol/test_offline_contracts.py -q
git diff --check
```

## Remaining boundary decisions

- Profile input permits values that later fail Python coercion. The route catches `ValueError` but some nested inputs raise `TypeError`.
- Manifest input permits scalar coercion. Full input validation requires the manifest parser after schema validation.
- Custom profiles require geometry and nonempty modes after parsing. The input envelope does not encode their conditional requirements.
- Schedule overlap and patch filter clearing depend on durable rules. Offline schemas describe their structural boundary.
- Family data needs separate schemas before clients can validate every renderer field.
- The display projection copies arbitrary JSON staleness and health error values. Narrow types require a production contract decision.
