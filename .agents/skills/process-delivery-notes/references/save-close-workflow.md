# Target-ledger save, verification and release workflow

Use this workflow only for transport or distribution ledgers explicitly selected during delivery-note processing. It records the user's standing authorization to save and close that target workbook without asking again for each batch. It does not authorize closing unrelated workbooks or accepting conflict, overwrite, authentication, recovery, or security prompts.


## Choose the available route

Live workbook sessions use the live state machine below. For file-based work use the available spreadsheet file-authoring skill. The user has authorized offline saving for these delivery/transport workflows; do not request repeated permission merely because a connected Save command is unavailable. A skill update/test alone does not authorize production edits.

For offline work: create hash-verified backups first; check the exact target for an Excel lock and actual exclusive access. Never write over an open/occupied workbook or kill Excel. Author a staged copy, verify only intended cells changed, preserve all original row heights, widths, formulas, comments and package features, and independently check dependent calculations. Immediately before commit re-read the original and require its hash to match the reviewed backup; otherwise rebuild from the new current file. Commit under exclusive access with recovery to the verified original on failure, flush and close every handle, then re-read saved bytes/cells. Temporarily clearing the DOS read-only attribute is permitted only for an unoccupied authorized target, restoring it in a finally block; do not modify ACLs or Excel security.

Never use wholesale openpyxl/third-party re-save if it drops unsupported workbook features. A staged artifact export can be merged only for reviewed changed cells/styles/caches, with original formula text and unrelated package parts verified unchanged. Handle XML namespaces, inline/shared strings and shared-formula translation; do not use fixed sheet numbers. If reliable recalculation is unavailable, retain the stage and report unverified formulas instead of marking saved. Do not hide a formula error with a blank or fabricated cache.

Offline method is `offline`; close audit is `not_attempted/none` with “offline handles released; Excel not opened”. An empty Excel window is not evidence that a target remains open. Local disk verification is not cloud-upload verification.

## Check open/save/close capability before entry (live route only)

Before editing the first ledger in a batch, verify both the connected Excel tools and the controlled UI fallback. Missing standalone Computer Use tools alone do not establish that UI control is unavailable.

On this Windows installation, use the current available Computer Use skill and its bundled guidance, API, and confirmation references before importing `@oai/sky` through `node_repl`. Do not assume an old package documentation path or API remains valid. Test the documented app discovery and a fresh target-window snapshot before claiming the UI route works. Do not launch a disabled legacy server, change security settings, or substitute raw input injection. If the supported runtime is absent or its documented call fails after one bounded recovery, report that limitation and use the authorized offline route only if the target is unoccupied. Never bypass a disabled native UI API.

Opening the next authorized transport workbook is part of this workflow: use the documented Computer Use interface to launch Excel if needed and open the exact known path through Excel. Confirm the title, editable grid, add-in pane, sign-in, and new connected session before entering data. Never ask the user to open a workbook merely because the connected document command list has no open command.

## Capture the target

Before writing, record the workbook's absolute path, exact Excel window title, initial file modification time, worksheet, and row ranges that will be verified. Require exactly one current connected session matching that target workbook and, before UI fallback, exactly one returned Excel window whose title matches the target. Unrelated or stale sessions must not be selected. Do not choose the frontmost window by assumption.

## Save state machine

1. Complete live read-back verification first.
2. Fetch the current connected-document schemas again. If the selected session advertises a save operation, use it and record `save_method=native`.
3. If no save operation is advertised, use Computer Use against the uniquely matched target window and invoke its Excel Save button once. Prefer a fresh accessibility Save element; otherwise use the visible Save button from the current window screenshot. An add-in pane may intercept Ctrl+S, so a dispatched keyboard shortcut alone is not save evidence. If a shortcut had no disk effect, reobserve and use the explicit Save button once. Record `save_method=ui`. Observe, act once, and refresh immediately; never reuse a stale window, element index, screenshot ID, or coordinate.
4. Stop without confirming if Excel displays Save As, read-only, file-occupied, Nutstore conflict, overwrite, recovery, sign-in, permission, or security UI.
5. Wait for the file modification time to advance. Open the saved workbook read-only from disk and compare the recorded target rows with the verified live values, formulas, dates, text, and number formats needed by the batch.
6. Only after the disk values match, set `save_status=saved`, `ledger_saved=true`, and `saved_mtime` to the observed ISO 8601 modification time. Otherwise leave the save state unverified and block archiving.

## Close state machine

1. Attempt close only after disk save verification. Prefer an advertised connected close operation and record `close_method=native`.
2. Otherwise reactivate the uniquely matched target window and close only that workbook, not the Excel application or another workbook. Record `close_method=ui`.
3. If the target workbook alone asks whether to save, choose Save once, wait for completion, and repeat disk modification-time and row verification before continuing.
4. Stop on every other dialog. Never choose Don't Save, Save As, overwrite, conflict resolution, recovery, authentication, permission, or security actions.
5. Rediscover Excel windows and connected sessions. Set `close_status=closed` only when the exact target workbook is absent from both. If the target remains, set `close_status=failed` and record `close_error`.
6. A verified save with `close_status=failed` may continue to archive. Distinguish workbook-window evidence from connector cache: record `window_closed=true/false/unknown` and `session_status=absent/active/stale/unknown` in a separate close audit. If the exact workbook window is absent but its unchanged old session remains listed, report "workbook window closed; connector disappearance not confirmed", not "workbook still open". Do not repeatedly reopen or close a workbook to clear a cached listing. Keep the conservative `close_status=failed` until both sources confirm absence.

Office.js documentation may describe Workbook.save/close even when the connected session does not advertise them. Documentation is not proof of connector capability; continue capability discovery and the controlled UI fallback. Closing one workbook can leave an empty Excel application window, which is not an open target workbook.

## Failure and recovery

- If the desktop is locked, Computer Use is unavailable, the target window is missing, or more than one title matches, do not send input. Set `close_status=not_attempted` or `failed` with the exact reason.
- If an input call has an unknown outcome, reobserve before a single bounded retry. Do not broaden the action or loop.
- Process grouped ledger work sequentially: write, live-read, save, disk-read, close, then move to the next workbook.
