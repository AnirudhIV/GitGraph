"""All Cypher used by the app, in one place.

Every query is parameterised and run through app.db.run_query /
app.db.run_write -- there is no string-concatenated Cypher anywhere.
"""

# ---------------------------------------------------------------------------
# Schema setup (constraints double as indexes on the unique keys)
# ---------------------------------------------------------------------------

CONSTRAINTS = [
    "CREATE CONSTRAINT author_email IF NOT EXISTS FOR (a:Author) REQUIRE a.email IS UNIQUE",
    "CREATE CONSTRAINT commit_hash IF NOT EXISTS FOR (c:Commit) REQUIRE c.hash IS UNIQUE",
    "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
    "CREATE CONSTRAINT module_name IF NOT EXISTS FOR (m:Module) REQUIRE m.name IS UNIQUE",
]

WIPE_BATCH = """
MATCH (n)
WITH n LIMIT $batch_size
DETACH DELETE n
RETURN count(n) AS deleted
"""

# ---------------------------------------------------------------------------
# Load (batched writes, called from seed/load.py)
# ---------------------------------------------------------------------------

# Loaded as its own pass, before LOAD_COMMIT_BATCH, over a list of *already
# deduplicated* {path, extension, module} dicts (one entry per distinct file
# in the whole history -- see seed/mine_git.py::distinct_files). That
# dedup matters: CognoDB's MERGE on a bare relationship pattern (no
# distinguishing property) does not reliably no-op against a match created
# earlier in the *same* statement's UNWIND -- re-merging (file)-[:BELONGS_TO]
# ->(module) once per commit that touches the file (i.e. the same pair,
# repeated dozens of times within one batch) produced duplicate edges in
# testing (1410 BELONGS_TO edges for 421 files). Sourcing this from an
# already-distinct list means each pair is only ever merged once, sidestepping
# the issue rather than relying on the engine to dedupe repeats.
LOAD_FILES_BATCH = """
UNWIND $files AS f
MERGE (file:File {path: f.path})
  ON CREATE SET file.extension = f.extension, file.module = f.module, file.is_deleted = false,
                file.has_rename_history = false
MERGE (module:Module {name: f.module})
MERGE (file)-[:BELONGS_TO]->(module)
RETURN count(*) AS written
"""

# One RENAMED_TO edge per distinct (old_path -> new_path) pair -- see
# seed/mine_git.py::rename_pairs for why renames are tracked explicitly
# instead of showing up as an unrelated delete + add. Read queries below
# walk this edge backwards from a File to roll a renamed file's pre-rename
# history (commits, owners, coupling) into its current path instead of
# losing it at the rename boundary.
#
# has_rename_history flags new_file (the rename's target) so HOTSPOTS can
# skip the expensive lineage rollup for the vast majority of files that were
# never renamed -- see HOTSPOTS_SIMPLE / HOTSPOTS_ROLLUP below.
LOAD_RENAMES_BATCH = """
UNWIND $renames AS r
MATCH (old_file:File {path: r.from})
MATCH (new_file:File {path: r.to})
MERGE (old_file)-[:RENAMED_TO]->(new_file)
SET new_file.has_rename_history = true
RETURN count(*) AS written
"""

LOAD_COMMIT_BATCH = """
UNWIND $commits AS c
MERGE (author:Author {email: c.author_email})
  ON CREATE SET author.name = c.author_name
  ON MATCH SET author.name = c.author_name
MERGE (commit:Commit {hash: c.hash})
  ON CREATE SET
    commit.message = c.message,
    commit.timestamp = c.timestamp,
    commit.additions = c.additions,
    commit.deletions = c.deletions,
    commit.files_changed = size(c.files)
MERGE (author)-[:AUTHORED]->(commit)
WITH commit, c
UNWIND c.files AS f
MATCH (file:File {path: f.path})
MERGE (commit)-[m:MODIFIED]->(file)
  SET m.additions = f.additions, m.deletions = f.deletions, m.change_type = f.change_type
RETURN count(*) AS written
"""

MARK_DELETED_FILES = """
UNWIND $paths AS p
MATCH (f:File {path: p})
SET f.is_deleted = true
RETURN count(f) AS updated
"""

# ---------------------------------------------------------------------------
# Read: repo-wide stats
# ---------------------------------------------------------------------------

REPO_STATS = """
MATCH (f:File) WITH count(f) AS file_count
MATCH (c:Commit) WITH file_count, count(c) AS commit_count, min(c.timestamp) AS first_ts, max(c.timestamp) AS last_ts
MATCH (a:Author) WITH file_count, commit_count, first_ts, last_ts, count(a) AS author_count
MATCH (m:Module)
RETURN file_count, commit_count, author_count, count(m) AS module_count, first_ts, last_ts
"""

# Every coupling-style query below excludes "shotgun commits" -- commits
# that mechanically touch a huge number of files at once (a repo-wide
# reformat, a folder rename, a license header bump). Left in, a single such
# commit makes every file in the repo look coupled to every other file.
# This is the same commit-size filter Tornhill's temporal-coupling analysis
# (Code Maat / CodeScene) applies; here it's a WHERE clause on a precomputed
# Commit.files_changed property rather than a preprocessing pass.

# Hotspots: files with high commit churn, high coupling fan-out, and low bus
# factor (few distinct authors). This kind of "join two aggregates and rank
# by a derived ratio" query is exactly what gets awkward in SQL once the
# underlying fact table (commit x file) is large -- here it's three MATCH
# clauses chained through the graph.
#
# Split into two queries rather than one, run separately and merged/re-sorted
# in Python (see app.routers.repo.get_hotspots): rolling every file's
# rename lineage up via OPTIONAL MATCH ... RENAMED_TO*1..20 (see the note on
# FILE_DETAIL et al.) is correct but was measured at ~4x slower on a modest
# repo (643 files) specifically because HOTSPOTS runs that check against
# *every* candidate file, not one -- unlike the single-file queries, which
# saw no measurable regression at all. Since the overwhelming majority of
# files in any repo were never renamed, HOTSPOTS_SIMPLE handles those with
# the original, un-rolled-up query shape (guarded by has_rename_history,
# set at load time in LOAD_RENAMES_BATCH), and HOTSPOTS_ROLLUP pays the
# lineage-traversal cost only for the small minority that actually need it.
HOTSPOTS_SIMPLE = """
MATCH (f:File {is_deleted: false})
WHERE coalesce(f.has_rename_history, false) = false
MATCH (f)<-[:MODIFIED]-(c:Commit)
WITH f, count(DISTINCT c) AS commit_count
WHERE commit_count >= $min_commits
MATCH (f)<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(other:File)
WHERE other <> f AND c2.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH f, commit_count, count(DISTINCT canonical) AS coupled_file_count
MATCH (a:Author)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f)
WITH f, commit_count, coupled_file_count, count(DISTINCT a) AS author_count
WITH f, commit_count, coupled_file_count, author_count,
     toFloat(coupled_file_count) / commit_count AS coupling_density
RETURN f.path AS path, f.module AS module, commit_count, coupled_file_count, author_count,
       coupling_density,
       coupling_density * (1.0 / author_count) * log(commit_count + 1) AS risk_score
ORDER BY risk_score DESC
LIMIT $limit
"""

# Same computation as HOTSPOTS_SIMPLE, scoped to has_rename_history = true
# files only, with every aggregate computed over `lineage` (the file's own
# path plus every path it was ever renamed from) instead of the bare File
# node -- see the note above FILE_DETAIL for why `lineage` holds path
# strings, re-matched by {path: ...} inside each UNWIND, rather than the
# File nodes themselves.
HOTSPOTS_ROLLUP = """
MATCH (f:File {is_deleted: false})
WHERE f.has_rename_history = true
OPTIONAL MATCH (predecessor:File)-[:RENAMED_TO*1..20]->(f)
WITH f, [f.path] + collect(DISTINCT predecessor.path) AS lineage
UNWIND lineage AS lp
MATCH (lf:File {path: lp})<-[:MODIFIED]-(c:Commit)
WITH f, lineage, count(DISTINCT c) AS commit_count
WHERE commit_count >= $min_commits
UNWIND lineage AS lp2
MATCH (lf2:File {path: lp2})<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(other:File)
WHERE NOT other.path IN lineage AND c2.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH f, lineage, commit_count, count(DISTINCT canonical) AS coupled_file_count
UNWIND lineage AS lp3
MATCH (a:Author)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(lf3:File {path: lp3})
WITH f, commit_count, coupled_file_count, count(DISTINCT a) AS author_count
WITH f, commit_count, coupled_file_count, author_count,
     toFloat(coupled_file_count) / commit_count AS coupling_density
RETURN f.path AS path, f.module AS module, commit_count, coupled_file_count, author_count,
       coupling_density,
       coupling_density * (1.0 / author_count) * log(commit_count + 1) AS risk_score
ORDER BY risk_score DESC
LIMIT $limit
"""

# Params HOTSPOTS is precomputed with at ingest time (see PRECOMPUTE_HOTSPOTS_*
# below and seed/load.py::precompute_hotspots). The frontend only ever calls
# /api/hotspots with the default min_commits/max_files_per_commit -- app.
# routers.repo.get_hotspots checks the request against these same constants
# and serves the cached HOTSPOTS_PRECOMPUTED path only on an exact match,
# falling back to a live HOTSPOTS_SIMPLE/ROLLUP computation for any caller
# who asks with different values. Shared here rather than duplicated as
# literals in both files so the cache and the "is this a cache hit?" check
# can't silently drift apart.
HOTSPOT_DEFAULT_MIN_COMMITS = 8
HOTSPOT_DEFAULT_MAX_FILES_PER_COMMIT = 10

# Write-time twins of HOTSPOTS_SIMPLE / HOTSPOTS_ROLLUP: same computation,
# SET onto the File node as risk_score/hotspot_* instead of RETURNed. Run
# once per ingest (see seed/load.py::precompute_hotspots) rather than once
# per GET /api/hotspots -- this is a write-once-read-many computation (the
# graph only changes on a re-track), so recomputing it on every dashboard
# load was solving that the expensive way. HOTSPOTS_SIMPLE/ROLLUP stay
# in place for the (rare, non-default-params) live-query fallback.
PRECOMPUTE_HOTSPOTS_SIMPLE = """
MATCH (f:File {is_deleted: false})
WHERE coalesce(f.has_rename_history, false) = false
MATCH (f)<-[:MODIFIED]-(c:Commit)
WITH f, count(DISTINCT c) AS commit_count
WHERE commit_count >= $min_commits
MATCH (f)<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(other:File)
WHERE other <> f AND c2.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH f, commit_count, count(DISTINCT canonical) AS coupled_file_count
MATCH (a:Author)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f)
WITH f, commit_count, coupled_file_count, count(DISTINCT a) AS author_count
WITH f, commit_count, coupled_file_count, author_count,
     toFloat(coupled_file_count) / commit_count AS coupling_density
SET f.hotspot_commit_count = commit_count,
    f.hotspot_coupled_file_count = coupled_file_count,
    f.hotspot_author_count = author_count,
    f.hotspot_coupling_density = coupling_density,
    f.risk_score = coupling_density * (1.0 / author_count) * log(commit_count + 1)
RETURN count(f) AS written
"""

PRECOMPUTE_HOTSPOTS_ROLLUP = """
MATCH (f:File {is_deleted: false})
WHERE f.has_rename_history = true
OPTIONAL MATCH (predecessor:File)-[:RENAMED_TO*1..20]->(f)
WITH f, [f.path] + collect(DISTINCT predecessor.path) AS lineage
UNWIND lineage AS lp
MATCH (lf:File {path: lp})<-[:MODIFIED]-(c:Commit)
WITH f, lineage, count(DISTINCT c) AS commit_count
WHERE commit_count >= $min_commits
UNWIND lineage AS lp2
MATCH (lf2:File {path: lp2})<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(other:File)
WHERE NOT other.path IN lineage AND c2.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH f, lineage, commit_count, count(DISTINCT canonical) AS coupled_file_count
UNWIND lineage AS lp3
MATCH (a:Author)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(lf3:File {path: lp3})
WITH f, commit_count, coupled_file_count, count(DISTINCT a) AS author_count
WITH f, commit_count, coupled_file_count, author_count,
     toFloat(coupled_file_count) / commit_count AS coupling_density
SET f.hotspot_commit_count = commit_count,
    f.hotspot_coupled_file_count = coupled_file_count,
    f.hotspot_author_count = author_count,
    f.hotspot_coupling_density = coupling_density,
    f.risk_score = coupling_density * (1.0 / author_count) * log(commit_count + 1)
RETURN count(f) AS written
"""

# Every File not touched by either PRECOMPUTE_HOTSPOTS_* query above (i.e.
# below the min_commits floor) keeps risk_score = null from LOAD_FILES_BATCH,
# so this is a plain indexed sort -- no traversal at read time at all.
HOTSPOTS_PRECOMPUTED = """
MATCH (f:File)
WHERE f.risk_score IS NOT NULL
RETURN f.path AS path, f.module AS module,
       f.hotspot_commit_count AS commit_count,
       f.hotspot_coupled_file_count AS coupled_file_count,
       f.hotspot_author_count AS author_count,
       f.hotspot_coupling_density AS coupling_density,
       f.risk_score AS risk_score
ORDER BY f.risk_score DESC
LIMIT $limit
"""

# ---------------------------------------------------------------------------
# Read: file detail
# ---------------------------------------------------------------------------

# All four file-detail queries below roll up over `lineage` -- the queried
# path plus every path it descends from via RENAMED_TO -- for the same
# reason as HOTSPOTS: without it, looking up a recently renamed file would
# show a history that starts at the rename, hiding everything that happened
# to it under its old name(s). A never-renamed file's lineage is just
# itself, so this is a no-op for the common case.

FILE_DETAIL = """
MATCH (f:File {path: $path})
OPTIONAL MATCH (predecessor:File)-[:RENAMED_TO*1..20]->(f)
WITH f, [f.path] + collect(DISTINCT predecessor.path) AS lineage
OPTIONAL MATCH (f)-[:RENAMED_TO]->(renamed_to:File)
WITH f, lineage, renamed_to
UNWIND lineage AS lp
MATCH (lf:File {path: lp})
OPTIONAL MATCH (lf)<-[:MODIFIED]-(c:Commit)
WITH f, renamed_to, count(c) AS commit_count, min(c.timestamp) AS first_ts, max(c.timestamp) AS last_ts
RETURN f.path AS path, f.extension AS extension, f.module AS module, f.is_deleted AS is_deleted,
       commit_count, first_ts, last_ts, renamed_to.path AS renamed_to
"""

FILE_RECENT_COMMITS = """
MATCH (f:File {path: $path})
OPTIONAL MATCH (predecessor:File)-[:RENAMED_TO*1..20]->(f)
WITH f, [f.path] + collect(DISTINCT predecessor.path) AS lineage
UNWIND lineage AS lp
MATCH (lf:File {path: lp})<-[m:MODIFIED]-(c:Commit)<-[:AUTHORED]-(a:Author)
RETURN c.hash AS hash, c.message AS message, a.name AS author_name, c.timestamp AS timestamp,
       m.additions AS additions, m.deletions AS deletions
ORDER BY c.timestamp DESC
LIMIT $limit
"""

FILE_OWNERS = """
MATCH (f:File {path: $path})
OPTIONAL MATCH (predecessor:File)-[:RENAMED_TO*1..20]->(f)
WITH f, [f.path] + collect(DISTINCT predecessor.path) AS lineage
UNWIND lineage AS lp
MATCH (lf:File {path: lp})<-[:MODIFIED]-(c:Commit)<-[:AUTHORED]-(a:Author)
WITH a, count(DISTINCT c) AS commits
WITH collect({name: a.name, email: a.email, commits: commits}) AS owner_rows, sum(commits) AS total
UNWIND owner_rows AS o
RETURN o.name AS author_name, o.email AS author_email, o.commits AS commit_count,
       toFloat(o.commits) / total AS share
ORDER BY commit_count DESC
LIMIT $limit
"""

# Two-hop traversal: File -> Commit -> File, aggregated and thresholded.
# This is the core "logical coupling" query -- files that keep changing
# together even with no static dependency between them.
#
# Rolled up in *both* directions: `lineage` (the queried file's own rename
# history, as elsewhere) on the way in, and `canonical` on the way out --
# resolving each coupled `other` file forward through its own RENAMED_TO
# chain to whatever it's called today. Without the second half, a coupling
# partner that was itself later renamed would split across two rows (its
# old, now is_deleted path -- filtered out entirely -- and its new one,
# undercounting shared_commits), instead of reporting one partner under its
# current name with its full coupling history.
FILE_CO_CHANGES = """
MATCH (f:File {path: $path})
OPTIONAL MATCH (predecessor:File)-[:RENAMED_TO*1..20]->(f)
WITH f, [f.path] + collect(DISTINCT predecessor.path) AS lineage
UNWIND lineage AS lp
MATCH (lf:File {path: lp})<-[:MODIFIED]-(c:Commit)-[:MODIFIED]->(other:File)
WHERE NOT other.path IN lineage AND c.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH canonical, count(DISTINCT c) AS shared_commits
WHERE canonical.is_deleted = false AND shared_commits >= $min_count
RETURN canonical.path AS path, canonical.module AS module, shared_commits
ORDER BY shared_commits DESC
LIMIT $limit
"""

# ---------------------------------------------------------------------------
# Read: blast radius (1 or 2 degrees of coupling propagation)
# ---------------------------------------------------------------------------

# Rolled up in both directions, same as FILE_CO_CHANGES above. The
# second-degree BLAST_RADIUS_TRANSITIVE hop below is intentionally left as a
# plain File match: it already builds on this query's (rename-aware) direct
# results, and rolling up each *of those* neighbors' own rename lineage too
# would add real query complexity for a second-order, best-effort
# visualization -- a known, accepted gap rather than a fixed one.
BLAST_RADIUS_DIRECT = """
MATCH (f:File {path: $path})
OPTIONAL MATCH (predecessor:File)-[:RENAMED_TO*1..20]->(f)
WITH f, [f.path] + collect(DISTINCT predecessor.path) AS lineage
UNWIND lineage AS lp
MATCH (lf:File {path: lp})<-[:MODIFIED]-(c:Commit)-[:MODIFIED]->(other:File)
WHERE NOT other.path IN lineage AND c.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH canonical, count(DISTINCT c) AS shared_commits
WHERE canonical.is_deleted = false AND shared_commits >= $min_count
RETURN canonical.path AS path, canonical.module AS module, shared_commits
ORDER BY shared_commits DESC
LIMIT $limit
"""

# Second-degree propagation: coupling of the coupled files. Expressing this
# as one recursive step in SQL needs a self-join per hop plus a re-aggregate
# with its own threshold at each hop -- doable with recursive CTEs but the
# per-hop aggregate-then-filter-then-continue shape is what Cypher expresses
# directly as chained MATCH clauses.
BLAST_RADIUS_TRANSITIVE = """
MATCH (f:File {path: $path})<-[:MODIFIED]-(c1:Commit)-[:MODIFIED]->(direct:File)
WHERE direct <> f AND direct.is_deleted = false AND c1.files_changed <= $max_files_per_commit
WITH f, direct
MATCH (direct)<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(indirect:File)
WHERE indirect <> f AND indirect <> direct AND indirect.is_deleted = false
      AND c2.files_changed <= $max_files_per_commit
WITH direct, indirect, count(DISTINCT c2) AS shared_commits
WHERE shared_commits >= $min_count
RETURN direct.path AS via, indirect.path AS path, indirect.module AS module, shared_commits
ORDER BY shared_commits DESC
LIMIT $limit
"""

# ---------------------------------------------------------------------------
# Read: authors
# ---------------------------------------------------------------------------

# PRECOMPUTE_AUTHOR_STATS / AUTHOR_LIST_PRECOMPUTED below handle the
# no-search case (the default, and the only one the frontend hits on first
# load): commit_count/file_count are computed once at ingest instead of
# aggregating over every author's commits on every page load, same
# write-once-read-many reasoning as HOTSPOTS_SIMPLE/ROLLUP.
#
# AUTHOR_LIST stays as the live fallback for an actual search term, but
# reordered from the original shape: it used to aggregate every author's
# commits/files *before* applying the name filter, which meant a search for
# one name still paid the full-table aggregation cost. Filtering by name
# first (cheap, no aggregation) and only then aggregating the (usually much
# smaller) matched subset -- the same order SEARCH_AUTHORS already used --
# fixes that without needing a search term to be precomputable, which it
# isn't (it's arbitrary user input).
PRECOMPUTE_AUTHOR_STATS = """
MATCH (a:Author)-[:AUTHORED]->(c:Commit)
WITH a, count(c) AS commit_count, min(c.timestamp) AS first_ts, max(c.timestamp) AS last_ts
OPTIONAL MATCH (a)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f:File)
WITH a, commit_count, first_ts, last_ts, count(DISTINCT f) AS file_count
SET a.commit_count = commit_count, a.file_count = file_count,
    a.first_commit_at = first_ts, a.last_commit_at = last_ts
RETURN count(a) AS written
"""

AUTHOR_LIST_PRECOMPUTED = """
MATCH (a:Author)
WHERE a.commit_count IS NOT NULL
RETURN a.email AS email, a.name AS name, a.commit_count AS commit_count, a.file_count AS file_count,
       a.first_commit_at AS first_ts, a.last_commit_at AS last_ts
ORDER BY a.commit_count DESC
SKIP $offset LIMIT $limit
"""

AUTHOR_LIST = """
MATCH (a:Author)
WHERE toLower(a.name) CONTAINS toLower($search)
MATCH (a)-[:AUTHORED]->(c:Commit)
WITH a, count(c) AS commit_count, min(c.timestamp) AS first_ts, max(c.timestamp) AS last_ts
OPTIONAL MATCH (a)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f:File)
WITH a, commit_count, first_ts, last_ts, count(DISTINCT f) AS file_count
RETURN a.email AS email, a.name AS name, commit_count, file_count, first_ts, last_ts
ORDER BY commit_count DESC
SKIP $offset LIMIT $limit
"""

AUTHOR_DETAIL = """
MATCH (a:Author {email: $email})-[:AUTHORED]->(c:Commit)
WITH a, count(c) AS commit_count, min(c.timestamp) AS first_ts, max(c.timestamp) AS last_ts
OPTIONAL MATCH (a)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f:File)
RETURN a.email AS email, a.name AS name, commit_count, first_ts, last_ts, count(DISTINCT f) AS file_count
"""

AUTHOR_TOP_FILES = """
MATCH (a:Author {email: $email})-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f:File)
WITH f, count(*) AS commit_count
RETURN f.path AS path, f.module AS module, commit_count
ORDER BY commit_count DESC
LIMIT $limit
"""

AUTHOR_TOP_MODULES = """
MATCH (a:Author {email: $email})-[:AUTHORED]->(:Commit)-[:MODIFIED]->(:File)-[:BELONGS_TO]->(m:Module)
WITH m, count(*) AS touches
RETURN m.name AS name, touches
ORDER BY touches DESC
LIMIT $limit
"""

# Shortest collaboration path between two authors, hopping through the
# files they've both touched. A true unbounded variable-length shortestPath
# here (`-[:AUTHORED|MODIFIED*]-`, undirected, either relationship type at
# each step) is the "obvious" Cypher answer but turned out impractical on
# this instance: undirected wildcard search from a high-activity author
# (700+ commits) explores a combinatorially huge frontier within 2-3 hops
# and blows the server's query deadline. AUTHORED and MODIFIED actually
# only ever point one way relative to a connecting path, though (Author ->
# Commit, Commit -> File), so the search doesn't need to be undirected at
# all -- it's resolved instead as two fixed, fully-directed hop patterns,
# each anchored on one of the two specific authors (so cost scales with
# their activity, not the whole graph): a direct shared file first, falling
# back to one shared bridge author if nothing direct exists.
AUTHOR_DIRECT_CONNECTION = """
MATCH (a1:Author {email: $email_a})-[:AUTHORED]->(c1:Commit)-[:MODIFIED]->(f:File)
      <-[:MODIFIED]-(c2:Commit)<-[:AUTHORED]-(a2:Author {email: $email_b})
WHERE c1 <> c2
RETURN a1.email AS a1_email, a1.name AS a1_name, f.path AS file_path,
       a2.email AS a2_email, a2.name AS a2_name
LIMIT 1
"""

AUTHOR_BRIDGE_CONNECTION = """
MATCH (a1:Author {email: $email_a})-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f1:File)
      <-[:MODIFIED]-(:Commit)<-[:AUTHORED]-(bridge:Author)
WHERE bridge.email <> $email_a AND bridge.email <> $email_b
WITH DISTINCT a1, f1, bridge
MATCH (bridge)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f2:File)
      <-[:MODIFIED]-(:Commit)<-[:AUTHORED]-(a2:Author {email: $email_b})
RETURN a1.email AS a1_email, a1.name AS a1_name, f1.path AS file_path_1,
       bridge.email AS bridge_email, bridge.name AS bridge_name,
       f2.path AS file_path_2, a2.email AS a2_email, a2.name AS a2_name
LIMIT 1
"""

# ---------------------------------------------------------------------------
# Read: modules
# ---------------------------------------------------------------------------

MODULE_LIST = """
MATCH (m:Module)<-[:BELONGS_TO]-(f:File {is_deleted: false})
OPTIONAL MATCH (f)<-[:MODIFIED]-(c:Commit)
OPTIONAL MATCH (c)<-[:AUTHORED]-(a:Author)
RETURN m.name AS name, count(DISTINCT f) AS file_count, count(DISTINCT c) AS commit_count,
       count(DISTINCT a) AS author_count
ORDER BY commit_count DESC
"""

# Module-to-module coupling: roll the file-level co-change graph up one
# level. A relational model would need a pre-aggregated file_changes x
# file_changes join table for this. Note the traversal starts from Commit,
# not Module: starting from Module and fanning out (Module -> File, up to
# ~150 files for a big module) -> Commit -> File -> Module lets the planner
# materialize a huge intermediate path before the files_changed filter ever
# applies. Starting from the (much smaller, and filterable-up-front) set of
# non-shotgun commits and fanning out from there keeps every intermediate
# row set bounded by an actual commit's file count.
#
# Same write-once-read-many situation as HOTSPOTS: this only changes on a
# re-track, so PRECOMPUTE_MODULE_COUPLING (below) runs it once at ingest and
# stores each pair as a COUPLED_WITH edge; MODULE_COUPLING itself becomes
# the live fallback for a caller asking with non-default params.
MODULE_COUPLING_DEFAULT_MIN_COUNT = 2
MODULE_COUPLING_DEFAULT_MAX_FILES_PER_COMMIT = 10

MODULE_COUPLING = """
MATCH (c:Commit)
WHERE c.files_changed >= 2 AND c.files_changed <= $max_files_per_commit
MATCH (c)-[:MODIFIED]->(f1:File)-[:BELONGS_TO]->(m1:Module)
MATCH (c)-[:MODIFIED]->(f2:File)-[:BELONGS_TO]->(m2:Module)
WHERE m1.name < m2.name
WITH m1, m2, count(DISTINCT c) AS shared_commits
WHERE shared_commits >= $min_count
RETURN m1.name AS module_a, m2.name AS module_b, shared_commits
ORDER BY shared_commits DESC
LIMIT $limit
"""

PRECOMPUTE_MODULE_COUPLING = """
MATCH (c:Commit)
WHERE c.files_changed >= 2 AND c.files_changed <= $max_files_per_commit
MATCH (c)-[:MODIFIED]->(f1:File)-[:BELONGS_TO]->(m1:Module)
MATCH (c)-[:MODIFIED]->(f2:File)-[:BELONGS_TO]->(m2:Module)
WHERE m1.name < m2.name
WITH m1, m2, count(DISTINCT c) AS shared_commits
WHERE shared_commits >= $min_count
MERGE (m1)-[r:COUPLED_WITH]->(m2)
SET r.shared_commits = shared_commits
RETURN count(*) AS written
"""

MODULE_COUPLING_PRECOMPUTED = """
MATCH (m1:Module)-[r:COUPLED_WITH]->(m2:Module)
RETURN m1.name AS module_a, m2.name AS module_b, r.shared_commits AS shared_commits
ORDER BY r.shared_commits DESC
LIMIT $limit
"""

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

SEARCH_FILES = """
MATCH (f:File)
WHERE toLower(f.path) CONTAINS toLower($q)
OPTIONAL MATCH (f)<-[:MODIFIED]-(c:Commit)
WITH f, count(c) AS commit_count
RETURN f.path AS path, f.extension AS extension, f.module AS module, commit_count, f.is_deleted AS is_deleted
ORDER BY commit_count DESC
LIMIT $limit
"""

SEARCH_AUTHORS = """
MATCH (a:Author)-[:AUTHORED]->(c:Commit)
WHERE toLower(a.name) CONTAINS toLower($q)
WITH a, count(c) AS commit_count, min(c.timestamp) AS first_ts, max(c.timestamp) AS last_ts
OPTIONAL MATCH (a)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f:File)
RETURN a.email AS email, a.name AS name, commit_count, count(DISTINCT f) AS file_count, first_ts, last_ts
ORDER BY commit_count DESC
LIMIT $limit
"""

SEARCH_COMMITS = """
MATCH (c:Commit)<-[:AUTHORED]-(a:Author)
WHERE toLower(c.message) CONTAINS toLower($q)
RETURN c.hash AS hash, c.message AS message, a.name AS author_name, c.timestamp AS timestamp,
       c.additions AS additions, c.deletions AS deletions
ORDER BY c.timestamp DESC
LIMIT $limit
"""
