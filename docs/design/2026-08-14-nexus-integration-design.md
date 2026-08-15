# Nexus Mods integration — design

Date: 2026-08-14
Status: approved
Extends: `2026-08-14-regalia-design.md`

## Purpose

Connect regalia to Nexus Mods. The tool identifies the archives you already
have, tells you when a newer version exists, downloads new mods and collections,
and accepts one-click downloads from the browser.

## Scope

In scope:

1. Identify local archives by MD5.
2. Check for updates.
3. Search and browse mods.
4. Download and install mods.
5. Browse and install collections.
6. Handle `nxm://` links from the browser.

Out of scope: endorsing, comments, uploading, image thumbnails, OAuth, and
writes to your tracked list.

## Verified facts

Every statement below was tested against the live API on 2026-08-14.

| Fact | Value |
|---|---|
| Game domain | `marvelrivals` |
| Game id | `7106` |
| v1 base | `https://api.nexusmods.com/v1` |
| v2 base | `https://api.nexusmods.com/v2/graphql` |
| v1 auth header | `apikey` |
| Account used to verify | a Premium account |
| Premium rate limit | 2000 per hour, 20000 per day |
| Rate limit headers | `x-rl-hourly-remaining`, `x-rl-daily-remaining`, and the matching reset times |
| Collections for this game | 92 |

## The two APIs

The split between the two APIs decides the whole design.

| Capability | API | Needs a key |
|---|---|---|
| Search mods | v2 GraphQL | No |
| Identify archives by MD5, in one batch | v2 GraphQL | No |
| Mod details and file lists | v2 GraphQL | No |
| Collection lists and revision manifests | v2 GraphQL | No |
| Which mods changed recently | v1 REST | Yes |
| Generate a download link | v1 REST | Yes, and Premium |
| Validate the key, read tracked mods | v1 REST | Yes |

Most reads need no key. Only downloads do. The Nexus screens therefore work
before you add a key, and every Nexus failure leaves the local features alone.

## Credentials

The key lives in `~/.config/regalia/credentials.toml`, mode 0600.

```toml
nexus_api_key = "..."
```

`NEXUS_API_KEY` in the environment overrides the file. The key never enters
`config.toml`, the catalog, the log tab, or git. The interface shows it masked,
as `****` plus the last four characters.

## Modules

```
src/regalia/nexus/
  client.py       HTTP: GraphQL POST and v1 REST GET, rate limiting, typed errors
  queries.py      the GraphQL documents
  models.py       NexusMod, NexusFile, HashMatch, Collection, CollectionMod
  identify.py     MD5 hashing, batched lookup, cache
  updates.py      which local mods have a newer file
  download.py     streamed download into the scan folder
  collections.py  revision manifests, install and remove a whole collection
src/regalia/
  credentials.py  the 0600 key file
  nxm.py          nxm:// parsing and desktop registration
```

### client.py

One class, `NexusClient`. Two methods: `graphql(document, variables)` and
`rest(path)`. Both set `User-Agent: regalia/<version> (Linux; x86_64)`.

Rate limiting:

- The client reads the `x-rl-*` headers after every v1 call and stores the
  remaining counts. The interface shows them.
- A token bucket limits bursts to 500 requests and recovers one per second.
  These numbers match the official client.
- A `429` waits for the reset time, then retries once.
- GraphQL publishes no limit. The defence is batching: one request for all
  hashes, one for a whole collection manifest.

Errors are typed: `NexusAuthError` (401), `NexusPremiumRequired` (403 on a
download link), `NexusRateLimited` (429), `NexusOffline` (any transport error).
Each one maps to a distinct message in the interface.

### identify.py

1. Compute the MD5 of each archive. Cache it in the catalog, keyed by path,
   size, and modification time, so the work happens once.
2. Send the unknown hashes in one query, in chunks of 100:

   ```graphql
   query($m: [String!]!) {
     fileHashes(md5s: $m) {
       md5 fileName fileSize modFileId
       modFile { fileId name version modId mod { name author summary adultContent } }
     }
   }
   ```

3. Store the result on the mod.

This recovers facts the file name cannot give. The archive
`Cyclops Slutty - Just Visor.zip` carries no version and no mod id; the hash
identifies it as mod 9652, file 25132, version 1.2, "Cyclops Revealing Suit v2"
by VolqenMods.

### Which name wins

Nexus wins where Nexus knows better. The parser keeps the job Nexus cannot do.

| Field | Source |
|---|---|
| Version, mod id, file id, author | Nexus. Authoritative. |
| Hero | The parser, but run on the Nexus mod name, which is cleaner than the file name. |
| Variant | The parser, run on the Nexus file name. |
| Everything, when the hash matches nothing | The parser, exactly as today. |

A `✓` in the table marks a row confirmed by hash.

### updates.py

One v1 call returns every mod in the game that changed in the period:
`GET /v1/games/marvelrivals/mods/updated.json?period=1m`. It returned 1653
entries in the test. The tool intersects that list with the mod ids it owns,
then calls `modFiles` only for the few that changed. One request covers the
whole library.

A newer file raises the existing `↑` badge, which until now only meant "you
hold two versions of this".

### download.py

1. `GET /v1/games/marvelrivals/mods/{modId}/files/{fileId}/download_link.json`
   returns seven CDN choices. The tool takes the first, which is the Nexus
   global CDN.
2. Stream to `<scan_dir>/<canonical name>.part`, then rename.
3. The existing install path takes over with no change.

When an `nxm://` link supplies `key` and `expires`, the tool appends them. That
path also works without Premium, so the feature survives if the account lapses.

## Collections

A collection is a curated list of mod files. The popular ones for this game hold
137 to 216 mods.

### Reading a collection

`collectionsV2` lists them. `collectionRevision` returns the manifest, and one
request gives the whole thing:

```graphql
{
  collectionRevision(slug: $slug, domainName: "marvelrivals", viewAdultContent: true) {
    revisionNumber modCount totalSize installationInfo
    modFiles {
      optional updatePolicy fileId
      file { fileId name version size modId mod { name author adultContent } }
    }
  }
}
```

The test collection `sdsnix` returned 137 files, 0.87 GB, 9 of them optional.

### Installing a collection

1. Show the manifest first: name, revision, mod count, download size, and an
   estimate of the extracted size. Nothing downloads until you confirm.
2. Optional mods appear as a checklist, unchecked by default.
3. Fetch exactly the file the manifest names. The update policy is recorded but
   never used to substitute a different file. One mod page usually holds many
   unrelated files rather than a chain of versions: page 5095 offers eight body
   variants and two add-ons, and one collection picks three of them. Reading
   "prefer" as "take the newest file on the page" collapsed those three choices
   into three copies of one file, which discarded the curator's selection and
   made several members race to write the same download. A newer file is still
   reported by the update check, where a person can judge it.
4. Skip any file already in the store. A second collection that shares mods with
   the first costs nothing.
5. Download at most 3 files at once. Each failure retries twice, then the file is
   recorded as failed and the run continues.
6. Install each member and switch it on. A pack is meant to be played whole, so
   members already held but switched off are turned on as well.
7. The whole run can be cancelled. Finished mods stay; the rest are dropped.
8. Each download writes to a scratch name that carries the worker's id, and a
   member whose archive another worker already finished keeps that copy. Two
   workers sharing one scratch path made the second rename fail.
9. A failure of any kind is caught, recorded, and stepped over. The pool would
   otherwise re-raise the first one and abandon the remaining hundred.

### Collection membership

Each mod records the collections it arrived with, on the mod itself and not on
its Nexus record. Membership is a local fact, known the moment an archive is
downloaded. Holding it on the Nexus record would leave it empty until the
archive was identified, and the conflict rule below would never fire for the
case it exists to serve.

This matters for two reasons.

- **Conflicts.** Two mods that change the same hero normally earn a warning.
  Inside one collection that overlap is deliberate, because the curator chose
  it. Warnings are therefore suppressed between members of the same collection,
  and raised as usual against anything outside it. Without this rule a 137-mod
  collection would mark almost every row and the warning would stop meaning
  anything.
- **Removal.** Removing a collection removes its members, except any mod that
  another collection still claims or that you installed on your own.

### Load order

Collections rely on the same `_9999999_P` convention as single mods. The tool
still flags a member that lacks the suffix, because that member can fail to
override the base game.

## Interface

Two new tabs, so six in total: LIBRARY, INSTALLED, **NEXUS**, **COLLECTIONS**,
PATCH, LOG.

### NEXUS tab

```
┌ REGALIA ─────────────────── ● patch ok ── yourname ★premium ── 1998/2000 ┐
│  LIBRARY   INSTALLED   NEXUS   COLLECTIONS   PATCH   LOG                     │
├──────────────────────────────────────────────────────────────────────────────┤
│  search ▏muscular                          [ SEARCH ] [ TRENDING ] [ TRACKED ]│
├────────┬──────────────────────────────┬────────────┬─────────┬───────────────┤
│  2805  │ Muscular Punisher            │ SIT        │  12.4k  │ ✓ have v1.2.0 │
│  2474  │ Muscular Iron Fist           │ SIT        │   9.8k  │ ↑ v1.2.0 new  │
│  4554  │ Muscular Daredevil           │ SIT        │   7.1k  │               │
├────────┴──────────────────────────────┴────────────┴─────────┴───────────────┤
│  Muscular Daredevil · SIT · 3 files · adult                                  │
│  enter files · d download · o open in browser                                │
└ / search · r rescan · q quit ────────────────────────────────────────────────┘
```

Pressing enter opens the file list for a mod. `d` downloads the highlighted
file. Rows the library already holds are marked, so browsing shows what is new.

### COLLECTIONS tab

The list shows slug, name, curator, mod count, and size. Selecting one opens the
manifest with the optional mods as a checklist and a summary line: how many
files are new, how many are already in the store, and the download size after
that subtraction. `i` starts the run and the progress bar reports
`42/137 · 380 MB of 870 MB`.

### Masthead

The masthead gains the account name, a Premium star, and the remaining hourly
quota. With no key it reads `no nexus key`.

## The nxm:// handler

`regalia register-nxm` writes
`~/.local/share/applications/regalia-nxm.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=regalia
Exec=/path/to/regalia/.venv/bin/regalia nxm %u
MimeType=x-scheme-handler/nxm
NoDisplay=true
Terminal=false
```

It then runs `xdg-mime default regalia-nxm.desktop x-scheme-handler/nxm` and
`update-desktop-database`. `unregister-nxm` reverses this.

Clicking "Mod Manager Download" in Chrome invokes:

```
regalia nxm "nxm://marvelrivals/mods/3561/files/8631?key=...&expires=...&user_id=..."
```

The handler runs without a terminal. It parses the link, refuses any game other
than `marvelrivals`, downloads into the first scan folder, and reports the
result with `notify-send`.

A running interface polls the modification time of the scan folders every five
seconds and rescans when something new lands. There is no daemon and no socket.

## Data model changes

`Mod` gains two fields:

```python
nexus: NexusInfo | None
md5: str | None
```

```python
@dataclass
class NexusInfo:
    mod_id: int
    file_id: int | None
    mod_name: str
    file_name: str
    author: str
    version: str | None
    adult: bool
    verified: bool  # True when an MD5 match proved it
    latest_file_id: int | None
    latest_version: str | None
    collections: list[str]  # slugs that claim this mod
```

The existing `Mod.nexus_id`, parsed from the file name, becomes a hint used only
until a hash or a download proves the real id.

The catalog file version rises to 2. A version 1 file loads without the new
fields and gains them on the next scan.

## Error handling

| Case | Behaviour |
|---|---|
| No key | Search, identify, and collection browsing still work. Downloads and the tracked list are disabled with a prompt that explains why. |
| Key rejected (401) | A re-entry prompt. Everything else keeps working. |
| Not Premium (403 on a link) | Offer to open the mod page in a browser. |
| Rate limited (429) | Wait for the reset shown in the headers, retry once, and show the remaining quota. |
| Offline | The Nexus tabs show `offline` and any cached data. Local features are untouched. |
| Hash matches nothing | The row keeps its parsed name and gains no `✓`. This is normal. |
| `nxm://` for another game | Report it with a notification and exit non-zero. |
| A collection member fails | Retry twice, record the failure, continue. Report the failures at the end. |
| A collection run is cancelled | Finished mods stay installed. Nothing is rolled back. |

## Steam launch options

The wizard can set the DLL override itself. Steam holds `localconfig.vdf` open
and writes it out when it quits, so a change made while Steam runs is lost.

The order is fixed:

1. Detect the running client by process name, `steam` and `steamwebhelper`.
2. Run `steam -shutdown` and poll for up to 30 seconds. If the client is still
   there, stop and change nothing.
3. Copy the file into `~/.local/share/regalia/backups/`, keeping the last ten.
4. Merge, rather than replace. Existing options are kept: an entry is folded
   into an existing `WINEDLLOVERRIDES` list, or inserted before `%command%`.
   Another game in the same file carries Proton settings that must survive.
5. Edit only the `LaunchOptions` key inside the app block, found by walking
   braces from the `apps` section while tracking quoted strings.
6. Write to a temporary file in the same directory and rename it into place.
7. Read the value back. If it does not match, restore the backup and report a
   failure.
8. Offer to start Steam again.

The operation is safe to repeat. A value that already carries the override is
left alone.

## Detail screens

Two full screens, each returning a decision that the application carries out.

**Mod detail** opens from the library or from the Nexus list. It shows the mod,
its author and counts, and every current file. Variants live at the file level
for many mods: mod 9652 alone offers nine. The file the library already holds is
marked. Choosing another swaps them, because two variants of one mod claim the
same slot and keeping both would leave the result to load order.

**Collection detail** opens from the collection list. It shows the full member
list with each file, version, size, and whether it is already held, and it marks
optional members. Optional members are picked one at a time here.

Both screens claim the keys the library binds, such as `x` and `i`, and make
them do nothing. A screen's bindings are checked before the application's, so
without this a key pressed on a detail screen would act on the library row
behind it.

## Order of work

Phase 1 is useful on its own. Phase 2 is the larger half.

**Phase 1** — credentials, client, identify, updates, download, the nxm handler,
and the NEXUS tab.

**Phase 2** — collection browsing, the manifest screen, the install run, and
membership-aware conflicts and removal.

## Decisions and reasons

- **v2 for reads, v1 for downloads.** v2 needs no key and batches; v1 is the
  only place that mints download links.
- **One batched hash query, not one call per file.** v1 offers
  `md5_search/{hash}`, which would cost 28 requests. v2's `fileHashes` costs one.
- **The bulk `updated` endpoint, not a query per mod.** One request covers the
  library however large it grows.
- **No daemon for `nxm://`.** A five-second poll of a folder's modification time
  is enough, and it cannot leave a stale socket behind.
- **Suppress conflicts inside a collection.** A curated pack overlaps on purpose.
  A warning that fires on nearly every row is worse than no warning.
- **No tests**, as with the rest of this project. Correctness comes from the
  layout: the game folder holds only links, downloads land in the scan folder as
  ordinary archives, and the key sits in one file at 0600.
