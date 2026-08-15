# Regalia Qt GUI product-depth improvements — design

Date: 2026-08-14
Status: approved by standing user direction
Extends: `2026-08-14-qt-gui-design.md`

## Purpose

Turn the first native GUI into a durable daily-use mod manager. Improve product
depth before adding decorative complexity: correct pagination, expressive search,
first-class variant management, persistent navigation state, and faster workflows.

## First campaign

### Paged results

Nexus and collection list methods return a typed page containing items, total
count, offset, and requested count. Pages retain their query, sort, filters, and
offset. Previous, next, first, and last controls show the current item range and
disable impossible actions. A changed query resets to the first page; opening and
closing details does not.

### Search

Nexus accepts ordinary text plus structured terms: `author:`, `id:`, and
`category:`. A numeric ID opens that mod directly. Search history is available in
the field. Search requests are generation-tagged so a slow old response cannot
replace a newer query.

Library search covers hero, variant, source archive, Nexus mod and file names,
author, Nexus ID, version, state, collection, and warning text. Dedicated filters
cover hero, state, installed/held availability, updates, conflicts, collection,
and verification. A result summary explains active filters and visible counts.

### Variants

Local rows are grouped by Nexus mod ID when verified, otherwise by parsed
identity. The library can switch between flat and grouped views. A group exposes
all held variants and versions, identifies the active variant, and can enable a
held variant atomically: unlink active siblings, then link the chosen variant. A
failed link restores the former active set.

The Nexus detail file table labels held, active, update, old, archived, main, and
optional files. Download-and-install treats another active file from the same mod
as a swap and asks for confirmation. The old extracted variant remains held but
disabled unless explicitly removed.

### Navigation and workflow

The main window maintains back/forward history for page changes and mod details.
Global search moves into Nexus without discarding the prior Nexus state. Keyboard
shortcuts cover paging, back/forward, filters, variant activation, and detail
dismissal. Page state persists for the current session; saved searches and durable
preferences follow in later slices.

## Subsequent campaigns

- Rich collection cards, images, manifest search, select-all optional controls,
  and failure retry.
- Detail pages inside the main workspace rather than blocking dialogs.
- Saved searches, recently viewed mods, favorites, and dashboard customization.
- Command palette, context menus, drag-aware gallery, image zoom, and comparison.
- Split focused GUI modules, improve cache observability, and harden cancellation.

## Error and performance rules

All remote list requests remain asynchronous. Stale results are ignored. Paging
never clears the current page until replacement data succeeds. Variant swaps are
transactional at the link layer and persist the catalog only after success.
Network errors leave local management available and expose retry without losing
the query or page.

## Verification

There are no automated tests by user request. Each campaign receives fresh lint,
bytecode compilation, query-level live API checks, headless Qt interaction smoke,
render inspection where visual behavior changes, and diff review before commit.
