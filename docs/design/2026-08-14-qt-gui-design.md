# Regalia Qt GUI — design

Date: 2026-08-14
Status: approved
Extends: `2026-08-14-regalia-design.md` and `2026-08-14-nexus-integration-design.md`

## Purpose

Add a native, image-rich Linux desktop interface to regalia. The GUI serves one
person on one machine and gives equal weight to local mod health and Nexus Mods
discovery. It coexists with the current Textual interface and reuses the same
domain logic.

## Scope

The first GUI release has full feature parity with the terminal app:

- Dashboard with local status and Nexus discovery.
- Local library management: scan, install, enable, disable, remove, repair,
  identify, update checks, conflicts, and multi-selection.
- Nexus search, browsing, file selection, downloads, and full image galleries.
- Collection browsing, manifests, optional member selection, downloads, and
  installation.
- Signature-bypass patch detection, installation, and Proton override guidance.
- Settings for the Nexus key, scan directories, game path, theme, image cache,
  and `nxm://` registration status.
- Current-session activity history, progress, and actionable errors.
- Automatic discovery of archives delivered by the existing `nxm://` handler.

Adult-content mods and images are shown normally. Nexus videos are not embedded.
There are no automated tests.

## Technical approach

Use PySide6 with Qt Widgets and a small set of custom-painted image components.
Qt Widgets provides native desktop behavior and direct reuse of the Python
backend. QML is not used because its extra state boundary would slow development;
an embedded web interface is not used because it would complicate filesystem and
desktop integration.

The existing `regalia` command continues to launch Textual. A new
`regalia-gui` command launches the Qt application. Both interfaces use the same
configuration, credentials, catalog, installer, patch, Nexus, and collection
modules. GUI code must not move presentation concerns into those modules.

## Architecture

GUI-specific code lives under `src/regalia/gui/` and is split by responsibility:

```text
gui/
  application.py       Qt bootstrap, theme, shared services, and shutdown
  main_window.py       navigation rail, top bar, and stacked page workspace
  tasks.py             background task coordination and structured task events
  images.py            image requests, decoding, disk cache, and prefetching
  models/              Qt adapters over catalog and Nexus records
  pages/               one module per Dashboard, Library, Nexus, Collections,
                       Patch, Activity, and Settings page
  widgets/             reusable cards, image tiles, badges, detail panel, gallery
```

Each page owns its controller and presentation model. Pages call existing domain
services and react to typed results; they do not perform archive, filesystem, or
HTTP work inside widgets. The main window preserves each page's filters, scroll
position, and selection when navigating.

`tasks.py` provides one coordinator over Qt's thread pool. It runs folder scans,
archive inspection, hashing, Nexus calls, image loading, downloads, extraction,
link operations, and patch work away from the GUI thread. Tasks emit structured
started, progress, succeeded, failed, and cancelled events. Conflicting actions
against a busy mod are disabled until its task finishes.

## Application shell

A persistent left rail contains:

1. Dashboard
2. Library
3. Nexus
4. Collections
5. Patch
6. Activity
7. Settings

The top bar contains global Nexus search, current background activity, and Nexus
account status. The central workspace uses a stacked page container. Detail views
open within that workspace or in a side panel; only confirmations, settings
pickers, and the image lightbox use separate dialogs.

## Dashboard

The approved visual direction is **Command Center**: a compact operational layer
above image-led discovery, rather than an editorial landing page or a dense bento
grid.

The upper row reports installed and enabled counts, available updates, patch
health, game detection, and active downloads. Below it, horizontal image rails
show recently viewed mods, trending Nexus mods, recently updated mods, and
collections. Cards provide relevant quick actions and open a complete detail view
when clicked.

Dashboard sections load independently. Local status appears immediately. Nexus
sections show placeholders until their asynchronous requests finish and retain
cached content when the network is unavailable.

## Library

Library uses an image-enhanced list, not oversized cards, so local management
stays efficient. It supports search, hero and state filters, adjustable comfortable
or compact density, multi-selection, and all current mod actions.

Selecting a row opens a side panel containing the Nexus cover image when known,
metadata, local files, state, warnings, collection membership, and available
actions. Conflict, newer-version, unsupported, broken-link, and load-order states
remain visible in the list without opening the panel.

## Nexus

Nexus uses responsive image cards with search, sorting, category filters, and
pagination. Search results open a mod detail page containing:

- Cover image and Nexus metadata.
- Cleaned description.
- Selectable file variants with version, category, size, and held state.
- Install, download-only, and open-on-Nexus actions.
- A full image gallery.

The gallery opens images in a keyboard-navigable lightbox. Left and right move
between images, Escape closes it, and zoom requests a larger cached rendition or
the original. Adult images are neither hidden nor blurred.

## Collections

Collections use image cards and expose the existing sort and discovery data.
A collection detail page shows its cover image, metadata, description, members,
required or optional status, held-file state, version, size, and total planned
download size. Required members cannot be deselected. Optional members are chosen
individually before installation.

The install flow skips files already held, reports per-file and overall progress,
tags installed catalog entries with collection membership, and keeps the existing
intentional-overlap conflict behavior.

## Patch, Activity, and Settings

Patch presents the three existing checks: bypass files, archive availability, and
the Proton DLL override. It can install the bypass through the existing patch
service and never writes Steam's configuration.

Activity lists current and completed operations from the current application
session with progress, result, timestamp, and error details. It is the durable
in-session place for information that also appears in short notifications; it is
cleared on restart. The top bar condenses concurrent work into one activity
indicator.

Settings manages the Nexus API key, scan directories, game-root override, theme,
library density, image-cache limit, and `nxm://` registration status. Credentials
continue to use the existing mode-0600 credentials file and remain masked.

## Image pipeline

Typed Nexus models gain one normalized image record used by mod cards, mod
galleries, and collection cards. It contains a stable identity, original URL,
thumbnail URL when Nexus supplies one, width and height when supplied, caption,
and display order. Query adapters map the Nexus response into this record, so Qt
widgets do not depend on GraphQL field names.

`images.py` owns all image fetching and decoding. It exposes an asynchronous
request keyed by source URL and requested rendition size. Widgets first paint a
neutral placeholder, then update when the decoded image is ready. Failed requests
paint a restrained fallback and remain retryable.

The disk cache lives beneath the regalia data directory in an `images` subtree.
Its key combines the source URL and requested size. It stores downloaded bytes and
enough metadata to track access time and byte size. The default limit is 1 GiB and
Settings allows 256 MiB, 512 MiB, 1 GiB, 2 GiB, 5 GiB, or 10 GiB. Cleanup uses
least-recently-used ordering when the selected limit is exceeded. Original URLs remain the
source of truth; image bytes and URLs are not embedded in `catalog.json`.

Opening a mod loads metadata and the first gallery page. The selected image and
adjacent images are prefetched. Cards request thumbnail-sized renditions; detail
views request gallery-sized renditions; zoom may request the original. Decoding
and scaling never run on the GUI thread.

Custom painting is limited to aspect-ratio crops, placeholders, selection states,
and image status overlays. Standard Qt controls handle forms, tables, menus,
dialogs, focus, and accessibility.

## Data flow

At startup:

1. Load configuration, credentials, and the local catalog.
2. Construct the main window and render local state immediately.
3. Discover the game and reconcile catalog state in the background.
4. Validate the Nexus account when a key exists.
5. Refresh dashboard Nexus sections independently.
6. Poll configured scan directories for archives delivered by the separate
   `nxm://` handler.

Local and remote state remain separate. Network failures never block library,
patch, or settings features. After a successful download, the existing scan and
install path becomes authoritative rather than creating a GUI-only catalog path.

## Visual system

The default GUI theme is the approved dark Command Center palette:

| Role | Value |
|---|---|
| Ground | near-black |
| Surface | charcoal |
| Primary text | warm off-white |
| Interaction accent | violet |
| Healthy state | green |
| Warning/update state | amber |

Settings also offers the existing parchment light theme, translated to the same
GUI component system. Theme changes apply immediately and persist through the
existing configuration.

Images supply most of the color. Geometry is square and deliberate, continuing
the current product identity without imitating a terminal. Cards use consistent
aspect ratios, restrained title overlays, and subtle hover elevation. Typography
uses compact uppercase section labels, strong mod titles, and quiet metadata.

The layout remains usable on a small laptop and adds columns on larger displays.
Visible buttons expose every primary action; context menus may duplicate actions
but must not contain unique functionality.

Keyboard operation remains first-class: navigation shortcuts, search focus, list
movement, selection, install, enable, disable, Escape dismissal, and arrow-key
gallery navigation. Focus indicators must remain visible.

## Error handling

Errors appear as concise notifications with a corresponding Activity entry.
Actions are explicit:

| Condition | Behavior |
|---|---|
| Offline or Nexus transport failure | Keep local features active; offer retry and show cached images/content. |
| Missing or invalid key | Open Settings guidance; unauthenticated Nexus reads remain available. |
| Premium required | Explain the requirement and offer to open the Nexus page. |
| Rate limited | Show reset timing and retry when allowed by the existing client policy. |
| Failed image | Paint a fallback and permit a later retry. |
| Failed or cancelled download | Remove the partial file and leave catalog state unchanged. |
| Failed extraction | Preserve the existing partial-store cleanup and leave the mod available. |
| Existing link target | Use the existing overwrite, skip, or cancel decision. |
| Missing game | Keep Nexus and settings usable and guide the user to select the game root. |
| Deleted `~mods` links | Mark affected mods broken and expose Repair. |

## Verification

No automated tests will be added. Before handoff, perform a manual smoke pass:

1. Launch the GUI and the existing Textual interface independently.
2. Scan local archives and exercise install, enable, disable, remove, and repair.
3. Search Nexus, open mod details, browse the full gallery, and use the lightbox.
4. Download and install a single mod and a collection with optional members.
5. Verify patch status and installation guidance.
6. Change settings and restart to confirm persistence.
7. Confirm offline local operation and actionable Nexus errors.
8. Confirm an archive delivered through `nxm://` appears in a running GUI.

## Decisions and rationale

- **Coexist instead of replace.** The Textual app remains a working fallback while
  the GUI settles in.
- **Qt Widgets over QML.** Direct Python reuse and rapid development matter more
  than a highly animated consumer interface.
- **Balanced dashboard.** Local health stays visible while Nexus images make
  discovery inviting.
- **Disk-backed image cache.** Galleries remain responsive without bloating the
  catalog or repeatedly downloading the same media.
- **Domain services remain shared.** The GUI is another presentation layer, not a
  second implementation of mod management.
- **No automated tests.** The owner explicitly requested rapid development without
  tests; the release gate is the manual smoke pass above.
