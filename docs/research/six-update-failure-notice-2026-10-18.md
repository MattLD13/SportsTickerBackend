# Ticker Six update failure notice

## Ownership

The updater owns the durable result in `update-result.json`.
The polling worker delivers terminal results to the application, including during network retry waits.
The runtime owns the notice lifetime and completed command identity.
The frame builder adds the notice over the active content.
The update journal stores display acknowledgement separately from server acknowledgement.

## Replaced path

The former path reported failures to the server without a display event.
The new path delivers the same saved result to both consumers.
A completed command cannot restart the updating display while its server command remains pending.

## Display behavior

- Show `UPDATE FAILED` in the lower right corner.
- Show `OLD KEPT` when preparation fails before activation.
- Show `RESTORED` when the updater restores the previous release.
- Keep the selected mode and its animation active.
- Clear the notice ten seconds after its first successful presentation.
- Acknowledge display delivery only after the output driver accepts the frame.
- Keep an unseen notice pending through a restart.
- Do not repeat a notice after display acknowledgement.

## Failure process

The updater downloads an immutable release into a separate folder.
It compiles the runtime before activation.
If preparation fails, the previous release remains active.
After activation, it waits up to 90 seconds for an active service and a valid frame receipt.
If that check fails, it restores the previous release and restarts the service.
If power fails during activation, the startup guard checks the saved activation record and restores the previous release when necessary.
The device stores the result locally and reports it when the backend becomes reachable.
After a rollback report, the backend blocks that version for other Ticker Six devices and cancels their pending updates.
A failed download alone does not block the version across the fleet.
Mini releases use a separate product family.

## Validation

Two real-shaped journal results pass through worker delivery, runtime state, the application, and production 384x32 rendering.
The checks cover a temporary output failure, display acknowledgement, stale pending commands, restart deduplication, and notice expiration.
Every pixel outside the corner remains unchanged.
The public demo includes both failure outcomes through the same production renderer.
