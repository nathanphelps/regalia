"""The GraphQL documents.

Every query here runs without an API key. Only the v1 REST calls need one.
"""

from __future__ import annotations

# Identify local archives. One request covers every hash, which is why the v2
# endpoint is used instead of v1's one-hash-per-request md5_search.
FILE_HASHES = """
query($md5s: [String!]!) {
  fileHashes(md5s: $md5s) {
    md5
    fileName
    fileSize
    modFile {
      fileId
      name
      version
      modId
      mod { name author summary adultContent }
    }
  }
}
"""

SEARCH_MODS = """
query($game: String!, $q: String!, $count: Int!, $offset: Int!) {
  mods(
    filter: {
      gameDomainName: [{ value: $game, op: EQUALS }]
      nameStemmed: [{ value: $q, op: WILDCARD }]
    }
    sort: [{ relevance: { direction: DESC } }]
    count: $count
    offset: $offset
  ) {
    totalCount
    nodes {
      modId name author version summary
      adultContent downloads endorsements updatedAt
      pictureUrl thumbnailUrl thumbnailLargeUrl
    }
  }
}
"""

SEARCH_MODS_ADVANCED = """
query($game: String!, $count: Int!, $offset: Int!%(variables)s) {
  mods(
    filter: {
      gameDomainName: [{ value: $game, op: EQUALS }]
      %(filters)s
    }
    sort: [{ %(sort)s: { direction: DESC } }]
    count: $count
    offset: $offset
  ) {
    totalCount
    nodes {
      modId name author version summary category
      adultContent downloads endorsements updatedAt
      pictureUrl thumbnailUrl thumbnailLargeUrl
    }
  }
}
"""

# The browse lists differ from the search only in the sort and the missing
# name filter.
BROWSE_MODS = """
query($game: String!, $count: Int!, $offset: Int!) {
  mods(
    filter: { gameDomainName: [{ value: $game, op: EQUALS }] }
    sort: [{ %(sort)s: { direction: DESC } }]
    count: $count
    offset: $offset
  ) {
    totalCount
    nodes {
      modId name author version summary category
      adultContent downloads endorsements updatedAt
      pictureUrl thumbnailUrl thumbnailLargeUrl
    }
  }
}
"""

MOD_BY_ID = """
query($modId: ID!, $gameId: ID!) {
  mod(modId: $modId, gameId: $gameId) {
    modId name author version summary
    adultContent downloads endorsements updatedAt
    pictureUrl thumbnailUrl thumbnailLargeUrl
  }
}
"""

MOD_FILES = """
query($modId: ID!, $gameId: ID!) {
  modFiles(modId: $modId, gameId: $gameId) {
    fileId name version size date category description
  }
}
"""

# Nexus's public media index is the only gallery surface exposed by v2. The
# exact mod name keeps results relevant; the mod's own picture is always placed
# first by the client so a detail page still has useful art when the index has
# no matching uploads.
MOD_MEDIA = """
query($game: String!, $query: String!, $count: Int!) {
  media(
    filter: {
      gameId: [{ value: $game, op: EQUALS }]
      generalSearch: [{ value: $query, op: WILDCARD }]
    }
    count: $count
  ) {
    nodes {
      __typename
      ... on Image { id title caption url thumbnailUrl siteUrl }
      ... on SupporterImage { id title caption url thumbnailUrl siteUrl }
    }
  }
}
"""

LIST_COLLECTIONS = """
query($game: String!, $count: Int!, $offset: Int!%(variables)s) {
  collectionsV2(
    filter: {
      gameDomain: [{ value: $game, op: EQUALS }]
      %(filters)s
    }
    sort: [{ %(sort)s: { direction: DESC } }]
    count: $count
    offset: $offset
  ) {
    totalCount
    nodes {
      slug name summary endorsements
      updatedAt totalDownloads uniqueDownloads
      overallRating overallRatingCount
      user { name }
      tileImage { url thumbnailUrl(size: med) }
      headerImage { url thumbnailUrl(size: large) }
      currentRevision {
        revisionNumber modCount totalSize adultContent
      }
    }
  }
}
"""

# One request returns the whole manifest, however many mods it holds.
COLLECTION_REVISION = """
query($slug: String!, $game: String!) {
  collectionRevision(slug: $slug, domainName: $game, viewAdultContent: true) {
    revisionNumber modCount totalSize installationInfo adultContent
    collection {
      name summary endorsements
      updatedAt totalDownloads uniqueDownloads
      overallRating overallRatingCount
      user { name }
      tileImage { url thumbnailUrl(size: med) }
      headerImage { url thumbnailUrl(size: large) }
    }
    modFiles {
      optional
      updatePolicy
      fileId
      file {
        fileId name version size modId
        mod { name author adultContent }
      }
    }
  }
}
"""
