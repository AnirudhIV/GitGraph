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
    "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE",
]

WIPE_BATCH = """
MATCH (n)
WITH n LIMIT $batch_size
DETACH DELETE n
RETURN count(n) AS deleted
"""

# Scoped wipe of just the function/call-graph subgraph, run unconditionally
# at the start of every ingest (independent of the top-level --clear flag) --
# see seed/parse/__init__.py for why this side of the graph is always fully
# re-derived from the current working tree rather than accumulated like the
# git-history side.
WIPE_FUNCTIONS_BATCH = """
MATCH (n:Function)
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

# Functions are only ever parsed out of files already in the mined file
# list (see seed/parse/__init__.py::parse_repo's caller in seed/load.py),
# and load_files() has already run by the time this executes -- so a plain
# MATCH is correct here, not a defensive MERGE: every fn.path is guaranteed
# to already have a File node.
LOAD_FUNCTIONS_BATCH = """
UNWIND $functions AS fn
MATCH (file:File {path: fn.path})
MERGE (func:Function {id: fn.id})
SET func.path = fn.path, func.name = fn.name, func.qualname = fn.qualname, func.language = fn.language,
    func.start_line = fn.start_line, func.end_line = fn.end_line, func.is_exported = fn.is_exported,
    func.is_method = fn.is_method, func.source = fn.source, func.change_count = fn.change_count,
    func.risk_score = fn.risk_score, func.complexity = fn.complexity
MERGE (func)-[:DEFINED_IN]->(file)
RETURN count(*) AS written
"""

# One CALLS edge per distinct (caller, callee) pair, deduped/aggregated in
# Python before this write (same idiom as mine_git.py::rename_pairs) -- see
# seed/parse/__init__.py for how call_count/call_lines/confidence are
# rolled up across multiple call sites between the same pair.
LOAD_CALLS_BATCH = """
UNWIND $calls AS c
MATCH (caller:Function {id: c.caller_id})
MATCH (callee:Function {id: c.callee_id})
MERGE (caller)-[r:CALLS]->(callee)
SET r.confidence = c.confidence, r.resolution = c.resolution, r.call_count = c.call_count, r.call_lines = c.call_lines
RETURN count(*) AS written
"""

# Only ever written for imports resolved to an in-repo file -- an
# unresolved/dynamic/external import is dropped in Python before it gets
# here, not stored with a null target.
LOAD_IMPORTS_BATCH = """
UNWIND $imports AS i
MATCH (from_file:File {path: i.from_path})
MATCH (to_file:File {path: i.to_path})
MERGE (from_file)-[r:IMPORTS]->(to_file)
SET r.imported_names = i.imported_names
RETURN count(*) AS written
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
#   ((now.epochSeconds - datetime(c.timestamp).epochSeconds) / 86400.0) is a
#   commit's age in days as a plain float (avoiding duration.between(...).days,
#   which is a calendar *component*, not total elapsed days -- the wrong
#   thing to feed exp() here). exp(-age / $half_life_days) is 1.0 for a
#   commit right now, 0.5 at exactly one half-life, and asymptotic to 0 for
#   old history. commit_weight_recent sums that per commit (replacing a flat
#   COUNT); coupled_file_weight_recent sums, per distinct coupled file, the
#   *most recent* co-change commit's decay (so a file coupled both 3 years
#   ago and last week counts once, weighted by the recent occurrence) --
#   replacing a flat COUNT DISTINCT. Same coupling_density/author_count/log
#   shape as risk_score, just built from decayed sums instead of counts.
HOTSPOTS_SIMPLE = """
MATCH (f:File {is_deleted: false})
WHERE coalesce(f.has_rename_history, false) = false
MATCH (f)<-[:MODIFIED]-(c:Commit)
WITH f, count(DISTINCT c) AS commit_count,
     sum(exp(-((datetime().epochSeconds - datetime(c.timestamp).epochSeconds) / 86400.0) / $half_life_days)) AS commit_weight_recent
WHERE commit_count >= $min_commits
MATCH (f)<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(other:File)
WHERE other <> f AND c2.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH f, commit_count, commit_weight_recent, canonical,
     max(exp(-((datetime().epochSeconds - datetime(c2.timestamp).epochSeconds) / 86400.0) / $half_life_days)) AS file_decay
WITH f, commit_count, commit_weight_recent,
     count(DISTINCT canonical) AS coupled_file_count, sum(file_decay) AS coupled_file_weight_recent
MATCH (a:Author)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f)
WITH f, commit_count, coupled_file_count, commit_weight_recent, coupled_file_weight_recent,
     count(DISTINCT a) AS author_count
WITH f, commit_count, coupled_file_count, author_count,
     toFloat(coupled_file_count) / commit_count AS coupling_density,
     commit_weight_recent, coupled_file_weight_recent,
     coupled_file_weight_recent / commit_weight_recent AS coupling_density_recent
RETURN f.path AS path, f.module AS module, commit_count, coupled_file_count, author_count,
       coupling_density,
       coupling_density * (1.0 / author_count) * log(commit_count + 1) AS risk_score,
       coupling_density_recent * (1.0 / author_count) * log(commit_weight_recent + 1) AS risk_score_recent
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
WITH f, lineage, count(DISTINCT c) AS commit_count,
     sum(exp(-((datetime().epochSeconds - datetime(c.timestamp).epochSeconds) / 86400.0) / $half_life_days)) AS commit_weight_recent
WHERE commit_count >= $min_commits
UNWIND lineage AS lp2
MATCH (lf2:File {path: lp2})<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(other:File)
WHERE NOT other.path IN lineage AND c2.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH f, lineage, commit_count, commit_weight_recent, canonical,
     max(exp(-((datetime().epochSeconds - datetime(c2.timestamp).epochSeconds) / 86400.0) / $half_life_days)) AS file_decay
WITH f, lineage, commit_count, commit_weight_recent,
     count(DISTINCT canonical) AS coupled_file_count, sum(file_decay) AS coupled_file_weight_recent
UNWIND lineage AS lp3
MATCH (a:Author)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(lf3:File {path: lp3})
WITH f, commit_count, coupled_file_count, commit_weight_recent, coupled_file_weight_recent,
     count(DISTINCT a) AS author_count
WITH f, commit_count, coupled_file_count, author_count,
     toFloat(coupled_file_count) / commit_count AS coupling_density,
     commit_weight_recent, coupled_file_weight_recent,
     coupled_file_weight_recent / commit_weight_recent AS coupling_density_recent
RETURN f.path AS path, f.module AS module, commit_count, coupled_file_count, author_count,
       coupling_density,
       coupling_density * (1.0 / author_count) * log(commit_count + 1) AS risk_score,
       coupling_density_recent * (1.0 / author_count) * log(commit_weight_recent + 1) AS risk_score_recent
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
WITH f, count(DISTINCT c) AS commit_count,
     sum(exp(-((datetime().epochSeconds - datetime(c.timestamp).epochSeconds) / 86400.0) / $half_life_days)) AS commit_weight_recent
WHERE commit_count >= $min_commits
MATCH (f)<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(other:File)
WHERE other <> f AND c2.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH f, commit_count, commit_weight_recent, canonical,
     max(exp(-((datetime().epochSeconds - datetime(c2.timestamp).epochSeconds) / 86400.0) / $half_life_days)) AS file_decay
WITH f, commit_count, commit_weight_recent,
     count(DISTINCT canonical) AS coupled_file_count, sum(file_decay) AS coupled_file_weight_recent
MATCH (a:Author)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(f)
WITH f, commit_count, coupled_file_count, commit_weight_recent, coupled_file_weight_recent,
     count(DISTINCT a) AS author_count
WITH f, commit_count, coupled_file_count, author_count,
     toFloat(coupled_file_count) / commit_count AS coupling_density,
     commit_weight_recent, coupled_file_weight_recent,
     coupled_file_weight_recent / commit_weight_recent AS coupling_density_recent
SET f.hotspot_commit_count = commit_count,
    f.hotspot_coupled_file_count = coupled_file_count,
    f.hotspot_author_count = author_count,
    f.hotspot_coupling_density = coupling_density,
    f.risk_score = coupling_density * (1.0 / author_count) * log(commit_count + 1),
    f.risk_score_recent = coupling_density_recent * (1.0 / author_count) * log(commit_weight_recent + 1)
RETURN count(f) AS written
"""

PRECOMPUTE_HOTSPOTS_ROLLUP = """
MATCH (f:File {is_deleted: false})
WHERE f.has_rename_history = true
OPTIONAL MATCH (predecessor:File)-[:RENAMED_TO*1..20]->(f)
WITH f, [f.path] + collect(DISTINCT predecessor.path) AS lineage
UNWIND lineage AS lp
MATCH (lf:File {path: lp})<-[:MODIFIED]-(c:Commit)
WITH f, lineage, count(DISTINCT c) AS commit_count,
     sum(exp(-((datetime().epochSeconds - datetime(c.timestamp).epochSeconds) / 86400.0) / $half_life_days)) AS commit_weight_recent
WHERE commit_count >= $min_commits
UNWIND lineage AS lp2
MATCH (lf2:File {path: lp2})<-[:MODIFIED]-(c2:Commit)-[:MODIFIED]->(other:File)
WHERE NOT other.path IN lineage AND c2.files_changed <= $max_files_per_commit
MATCH (other)-[:RENAMED_TO*0..20]->(canonical:File)
WHERE NOT (canonical)-[:RENAMED_TO]->()
WITH f, lineage, commit_count, commit_weight_recent, canonical,
     max(exp(-((datetime().epochSeconds - datetime(c2.timestamp).epochSeconds) / 86400.0) / $half_life_days)) AS file_decay
WITH f, lineage, commit_count, commit_weight_recent,
     count(DISTINCT canonical) AS coupled_file_count, sum(file_decay) AS coupled_file_weight_recent
UNWIND lineage AS lp3
MATCH (a:Author)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(lf3:File {path: lp3})
WITH f, commit_count, coupled_file_count, commit_weight_recent, coupled_file_weight_recent,
     count(DISTINCT a) AS author_count
WITH f, commit_count, coupled_file_count, author_count,
     toFloat(coupled_file_count) / commit_count AS coupling_density,
     commit_weight_recent, coupled_file_weight_recent,
     coupled_file_weight_recent / commit_weight_recent AS coupling_density_recent
SET f.hotspot_commit_count = commit_count,
    f.hotspot_coupled_file_count = coupled_file_count,
    f.hotspot_author_count = author_count,
    f.hotspot_coupling_density = coupling_density,
    f.risk_score = coupling_density * (1.0 / author_count) * log(commit_count + 1),
    f.risk_score_recent = coupling_density_recent * (1.0 / author_count) * log(commit_weight_recent + 1)
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
       f.risk_score AS risk_score,
       f.risk_score_recent AS risk_score_recent
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
       commit_count, first_ts, last_ts, renamed_to.path AS renamed_to,
       f.risk_score AS risk_score, f.risk_score_recent AS risk_score_recent
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

# Author criticality: a per-author bus-factor number, generalizing
# AUTHOR_SOLE_OWNED_FILES's binary "does this author solely own the file"
# check into a continuous ownership-share measure. For each (author, file)
# pair, share = this author's commits on the file / the file's total
# commits; a file only counts toward the score once that share clears
# $concentration_threshold (below that, no single author is concentrated
# enough on it to matter).
#
# Each qualifying file contributes two additive terms, not one:
#   1. risk_score * share * boost -- the churn/coupling-driven term.
#      risk_score is read straight off the File node (PRECOMPUTE_HOTSPOTS_*
#      already wrote it), coalesced to 0 for a file that never cleared the
#      hotspot gate (>=8 commits + real coupling) rather than letting a
#      null collapse the whole sum. boost applies only at share == 1.0
#      (true sole ownership, not just "does most of the work").
#   2. $sole_ownership_baseline, added flat whenever share == 1.0,
#      independent of risk_score. Without this, a stable, rarely-touched-
#      but-important file a single person solely owns -- exactly the kind
#      that's *least* likely to ever clear the hotspot gate, since it by
#      nature has low churn and rarely co-changes with anything -- silently
#      contributed 0. That's backwards: knowledge concentration on a file
#      is a real risk independent of how often the file happens to churn,
#      and this app has no independent "importance" signal to weight it by
#      (no import graph, no call graph -- only git history), so a flat
#      per-file floor is the honest choice over pretending a churn-based
#      proxy could tell "quiet because stable" from "quiet because nobody
#      needs it."
#
# sole_owned_file_count is tracked alongside the score, not folded into it,
# for display as its own flag (same split GraphNode.sole_owned/
# trending_worse already use). Single pass over the whole repo, not one
# query per author -- same shape as HOTSPOTS_SIMPLE/ROLLUP -- so this is
# write-once-read-many too (see seed/load.py::precompute_author_criticality).
PRECOMPUTE_AUTHOR_CRITICALITY = """
MATCH (f:File {is_deleted: false})<-[:MODIFIED]-(c:Commit)
WITH f, count(DISTINCT c) AS total_commits
MATCH (f)<-[:MODIFIED]-(c2:Commit)<-[:AUTHORED]-(a:Author)
WITH f, total_commits, a, count(DISTINCT c2) AS author_commits
WITH a, coalesce(f.risk_score, 0.0) AS risk_score, toFloat(author_commits) / total_commits AS share
WHERE share >= $concentration_threshold
WITH a, share,
     (risk_score * share * (CASE WHEN share = 1.0 THEN 1 + $sole_ownership_boost ELSE 1.0 END))
     + (CASE WHEN share = 1.0 THEN $sole_ownership_baseline ELSE 0.0 END) AS contribution
WITH a,
     sum(contribution) AS criticality_score,
     sum(CASE WHEN share = 1.0 THEN 1 ELSE 0 END) AS sole_owned_file_count
SET a.criticality_score = criticality_score, a.sole_owned_file_count = sole_owned_file_count
RETURN count(a) AS written
"""

# Every Author not touched by PRECOMPUTE_AUTHOR_CRITICALITY above (i.e. no
# file where they're concentrated enough to qualify) keeps
# criticality_score = null, so this is a plain indexed sort -- same
# read-side shape as HOTSPOTS_PRECOMPUTED.
AUTHOR_CRITICALITY_PRECOMPUTED = """
MATCH (a:Author)
WHERE a.criticality_score IS NOT NULL
RETURN a.email AS email, a.name AS name, a.criticality_score AS criticality_score,
       a.sole_owned_file_count AS sole_owned_file_count, a.last_commit_at AS last_commit_at
ORDER BY a.criticality_score DESC
LIMIT $limit
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

# Author collaboration network: everyone who has ever touched a file this
# author has also touched, weighted by how many files they share. Anchored
# on $email the same way AUTHOR_DIRECT_CONNECTION is (see the note above
# it), but that alone wasn't enough on a prolific author (800+ commits,
# 400+ files): fanning the second hop out over *every* file they've ever
# touched -- including high-traffic files like README that dozens of
# drive-by contributors have also brushed against -- measured at 8s+. The
# `WITH ... ORDER BY ... LIMIT` before the second MATCH caps the fan-out
# source to the author's own top files by their commit count on each one,
# which both bounds the cost and better reflects real collaboration (a
# shared one-line README touch is weak signal; files someone actually
# worked on repeatedly are strong signal).
AUTHOR_NETWORK = """
MATCH (a:Author {email: $email})-[:AUTHORED]->(c:Commit)-[:MODIFIED]->(f:File {is_deleted: false})
WITH f, count(DISTINCT c) AS my_commits
ORDER BY my_commits DESC
LIMIT $max_anchor_files
MATCH (f)<-[:MODIFIED]-(:Commit)<-[:AUTHORED]-(other:Author)
WHERE other.email <> $email
WITH other, count(DISTINCT f) AS shared_files
WHERE shared_files >= $min_shared
RETURN other.email AS email, other.name AS name, shared_files
ORDER BY shared_files DESC
LIMIT $limit
"""

# Files where this author is the *only* person who has ever committed to
# them -- true bus-factor-1 files, i.e. what's actually at risk if they
# leave. `c` in the first MATCH ranges over the author's own commits on f,
# so commit_count is their commit count on it and max(c.timestamp) is when
# they last touched it; the second MATCH re-walks every commit that ever
# touched f (not just this author's) to count distinct owners, so
# author_count = 1 can only mean $email is that one owner.
#
# last_touched matters as much as sole ownership: a file this author
# committed to yesterday and one they haven't touched in three years are
# both "bus-factor-1", but the stale one is the bigger risk -- nobody else
# has ever needed to learn it, and by now even the sole owner's own memory
# of it has likely faded.
AUTHOR_SOLE_OWNED_FILES = """
MATCH (a:Author {email: $email})-[:AUTHORED]->(c:Commit)-[:MODIFIED]->(f:File {is_deleted: false})
WITH f, count(DISTINCT c) AS commit_count, max(c.timestamp) AS last_touched
MATCH (f)<-[:MODIFIED]-(:Commit)<-[:AUTHORED]-(owner:Author)
WITH f, commit_count, last_touched, count(DISTINCT owner) AS author_count
WHERE author_count = 1
RETURN f.path AS path, f.module AS module, commit_count, last_touched
ORDER BY commit_count DESC
LIMIT $limit
"""

# ---------------------------------------------------------------------------
# Team topology: unanchored author network, clustered by which module they
# mostly work in (app.routers.authors.author_topology)
# ---------------------------------------------------------------------------

# Bounded to a specific email list (the already-selected top-N active
# authors from AUTHOR_LIST_PRECOMPUTED, never every author who ever made a
# drive-by commit) so this stays cheap regardless of contributor count.
#
# "Primary module" per author uses the same ORDER-BY-then-collect()[0]
# top-N-per-group idiom as REPO_MAP_TOP_FILES: order the (author, module,
# touches) rows by touches DESC before the second WITH groups by author, so
# collect(m.name)[0] is genuinely that author's most-touched module.
TEAM_TOPOLOGY_PRIMARY_MODULE = """
UNWIND $emails AS email
MATCH (a:Author {email: email})-[:AUTHORED]->(c:Commit)-[:MODIFIED]->(f:File)-[:BELONGS_TO]->(m:Module)
WITH a, m, count(DISTINCT c) AS touches
ORDER BY touches DESC
WITH a, collect(m.name)[0] AS primary_module
RETURN a.email AS email, primary_module
"""

# Two authors are an edge here if they've both done real work (>=
# $min_touches commits) on the *same file* -- "who actually works with
# whom", not just "both somewhere in a broad module like docs" (which is
# what a module-level version of this showed first: almost every active
# contributor touches docs/root eventually, so it produced a near-complete
# graph, not clusters). Starts from the small, filterable set of files any
# selected author has touched (same "start from what's small and fan out"
# shape used throughout this file) rather than an author x author
# cartesian: for each file, collect its qualifying authors (among the
# selected set only, capped at $max_authors_per_file so a file like
# README.md that half the repo has touched doesn't pair everyone with
# everyone -- the same instinct as the shotgun-commit filter elsewhere in
# this file, applied to files instead of commits), then pair up within that
# file's own (small) author list. A pair sharing several files produces one
# row per shared file, so the final WITH's grouping on (email_a, email_b)
# via count(*) is exactly "how many files this pair has in common" -- the
# edge weight, and what pulls them close together in the force layout (see
# GraphView's link-distance formula: higher weight already means shorter
# distance).
TEAM_TOPOLOGY_SHARED_FILES = """
MATCH (a:Author)-[:AUTHORED]->(c:Commit)-[:MODIFIED]->(f:File {is_deleted: false})
WHERE a.email IN $emails
WITH f, a, count(DISTINCT c) AS touches
WHERE touches >= $min_touches
WITH f, collect(a.email) AS emails
WHERE size(emails) >= 2 AND size(emails) <= $max_authors_per_file
UNWIND emails AS email_a
UNWIND emails AS email_b
WITH email_a, email_b
WHERE email_a < email_b
WITH email_a, email_b, count(*) AS shared_files
ORDER BY shared_files DESC
LIMIT $limit
RETURN email_a, email_b, shared_files
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
# Repo map: whole-repo overview (app.routers.repo.get_repo_map)
# ---------------------------------------------------------------------------

# Deliberately bounded, unlike every other graph endpoint here which is
# anchored on one file/author: this is the one *unanchored* view of the
# whole repo, so it can't just return every file or the force layout won't
# hold up.
#
# Node selection is risk-first, not coupling-first: an earlier version
# picked nodes from the top coupling *pairs*, which meant a genuinely risky
# file with weak coupling just never showed up -- exactly backwards for a
# "where are the landmines" view. HOTSPOTS_PRECOMPUTED already ranks every
# scored file by risk_score; app.routers.repo.get_repo_map fetches a
# generous slice of it and picks the top N by whichever of risk_score /
# risk_score_recent the caller asked for (both already ride along in every
# row, so no extra query for the toggle).

# Bounded to a specific path list (the already-selected risk-ranked node
# set, never the whole repo) so this stays cheap regardless of repo size --
# same author_count-over-MODIFIED-edges shape as HOTSPOTS_SIMPLE/ROLLUP, but
# for "is this file down to a single owner" specifically rather than folded
# into the risk_score formula (a file with 1 owner and one with 2 both get
# smoothed into the same continuous term there; sole ownership is a
# categorically different kind of danger worth flagging on its own).
REPO_MAP_SOLE_OWNERSHIP = """
UNWIND $paths AS p
MATCH (f:File {path: p})<-[:MODIFIED]-(:Commit)<-[:AUTHORED]-(owner:Author)
WITH f, count(DISTINCT owner) AS author_count
WHERE author_count = 1
RETURN f.path AS path
"""

# Coupling among the already-selected node set only (never the whole repo),
# and using coupling *density* -- shared_commits relative to how active the
# less-active file is -- rather than a raw shared_commits count, computed in
# Python from the commit_count each row already carries from
# HOTSPOTS_PRECOMPUTED. Raw shared_commits is biased toward files that are
# just busy in general; density is closer to "touching one of these usually
# means touching the other", the more actionable signal here.
#
# Starts from commits touching *any* selected file (same "start from the
# smaller, filterable set and fan out" shape as MODULE_COUPLING), collects
# which of the selected files each commit touched, and pairs up only within
# that per-commit list -- bounded by actual per-commit fan-out among the
# selected files, not a full cartesian product over the node set.
# min_shared_commits / limit mirror TEAM_TOPOLOGY_SHARED_FILES's min_touches
# and edge_limit -- without them this returned every pair that ever shared
# even a single commit (in this repo: 393 of 633 pairs, i.e. two-thirds,
# were a lone shared commit each), which is noise, not coupling, and drowned
# out the real pairs both visually and in the clustering layout.
REPO_MAP_COUPLING_AMONG = """
MATCH (f:File)
WHERE f.path IN $paths
MATCH (c:Commit)-[:MODIFIED]->(f)
WHERE c.files_changed <= $max_files_per_commit
WITH c, collect(DISTINCT f) AS touched
WHERE size(touched) >= 2
UNWIND touched AS f1
UNWIND touched AS f2
WITH c, f1, f2
WHERE f1.path < f2.path
WITH f1.path AS path_a, f2.path AS path_b, count(DISTINCT c) AS shared_commits
WHERE shared_commits >= $min_shared_commits
RETURN path_a, path_b, shared_commits
ORDER BY shared_commits DESC
LIMIT $edge_limit
"""

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

SEARCH_FILES = """
MATCH (f:File)
WHERE toLower(f.path) CONTAINS toLower($q)
OPTIONAL MATCH (f)<-[:MODIFIED]-(c:Commit)
WITH f, count(c) AS commit_count
RETURN f.path AS path, f.extension AS extension, f.module AS module, commit_count, f.is_deleted AS is_deleted,
       f.risk_score AS risk_score
ORDER BY commit_count DESC
LIMIT $limit
"""

# Same shape as SEARCH_FILES, ordered by risk instead -- kept as its own
# query rather than a dynamic ORDER BY so both stay plain, cacheable
# strings. Cypher treats null as the largest value, so a plain "risk_score
# DESC" would float every not-yet-scored file to the very top; sorting on
# "risk_score IS NULL" first pushes nulls to the bottom regardless of
# direction, then breaks ties by commit_count so the ordering is still
# deterministic for the (also unscored) files sharing that last spot.
SEARCH_FILES_BY_RISK = """
MATCH (f:File)
WHERE toLower(f.path) CONTAINS toLower($q)
OPTIONAL MATCH (f)<-[:MODIFIED]-(c:Commit)
WITH f, count(c) AS commit_count
RETURN f.path AS path, f.extension AS extension, f.module AS module, commit_count, f.is_deleted AS is_deleted,
       f.risk_score AS risk_score
ORDER BY f.risk_score IS NULL, f.risk_score DESC, commit_count DESC
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

# ---------------------------------------------------------------------------
# Read: function-level call graph (structural, from static source parsing --
# see backend/seed/parse/. A separate graph from every query above: none of
# these ever touch Author/Commit/File-coupling data, and vice versa.)
# ---------------------------------------------------------------------------

FUNCTIONS_FOR_FILE = """
MATCH (fn:Function {path: $path})
RETURN fn.id AS id, fn.name AS name, fn.qualname AS qualname, fn.path AS path, fn.language AS language,
       fn.start_line AS start_line, fn.end_line AS end_line, fn.is_exported AS is_exported, fn.is_method AS is_method
ORDER BY fn.start_line
"""

# Same rows as FUNCTIONS_FOR_FILE plus caller/callee fan counts -- kept as
# its own query rather than folding the aggregation into FUNCTIONS_FOR_FILE
# itself, since file_call_graph (below) uses that one purely for node ids/
# labels and has no use for the extra CALLS traversal cost. Ranked by
# caller_count so a file's function list reads as an importance ranking,
# same as FUNCTIONS_LIST does repo-wide on the Functions page.
FUNCTIONS_FOR_FILE_WITH_COUNTS = """
MATCH (fn:Function {path: $path})
OPTIONAL MATCH (fn)<-[:CALLS]-(caller:Function)
WITH fn, count(DISTINCT caller) AS caller_count
OPTIONAL MATCH (fn)-[:CALLS]->(callee:Function)
WITH fn, caller_count, count(DISTINCT callee) AS callee_count
RETURN fn.id AS id, fn.name AS name, fn.qualname AS qualname, fn.path AS path, fn.language AS language,
       fn.start_line AS start_line, fn.end_line AS end_line, fn.is_exported AS is_exported, fn.is_method AS is_method,
       caller_count, callee_count, coalesce(fn.change_count, 0) AS change_count, coalesce(fn.risk_score, 0.0) AS risk_score
ORDER BY caller_count DESC, fn.start_line
"""

# Repo-wide function browser (the Functions page's list half) -- caller/
# callee fan counts are aggregated live (cheap: bounded to $limit rows
# post-aggregation, and Function/CALLS graphs are orders of magnitude
# smaller than the git-history graph). change_count/risk_score, by
# contrast, are precomputed at ingest time (seed/load.py, right after
# parsing -- see mine_git.py::mine_function_change_counts) since they need
# a `git log` walk per file, not something a live Cypher aggregation could
# produce; coalesced to 0 for the (should-not-happen post-reingest, but
# cheap to guard) case of a Function node written before that existed.
FUNCTIONS_LIST = """
MATCH (fn:Function)
WHERE toLower(fn.qualname) CONTAINS toLower($q) OR toLower(fn.path) CONTAINS toLower($q)
OPTIONAL MATCH (fn)<-[:CALLS]-(caller:Function)
WITH fn, count(DISTINCT caller) AS caller_count
OPTIONAL MATCH (fn)-[:CALLS]->(callee:Function)
WITH fn, caller_count, count(DISTINCT callee) AS callee_count
RETURN fn.id AS id, fn.name AS name, fn.qualname AS qualname, fn.path AS path, fn.language AS language,
       fn.start_line AS start_line, fn.end_line AS end_line, fn.is_exported AS is_exported, fn.is_method AS is_method,
       caller_count, callee_count, coalesce(fn.change_count, 0) AS change_count, coalesce(fn.risk_score, 0.0) AS risk_score
ORDER BY caller_count DESC, fn.qualname
LIMIT $limit
"""

# Same rows as FUNCTIONS_LIST, ranked by the combined change-count x
# caller-count risk score instead -- kept as its own query rather than a
# dynamic ORDER BY, same idiom as SEARCH_FILES_BY_RISK next to SEARCH_FILES.
FUNCTIONS_LIST_BY_RISK = """
MATCH (fn:Function)
WHERE toLower(fn.qualname) CONTAINS toLower($q) OR toLower(fn.path) CONTAINS toLower($q)
OPTIONAL MATCH (fn)<-[:CALLS]-(caller:Function)
WITH fn, count(DISTINCT caller) AS caller_count
OPTIONAL MATCH (fn)-[:CALLS]->(callee:Function)
WITH fn, caller_count, count(DISTINCT callee) AS callee_count
RETURN fn.id AS id, fn.name AS name, fn.qualname AS qualname, fn.path AS path, fn.language AS language,
       fn.start_line AS start_line, fn.end_line AS end_line, fn.is_exported AS is_exported, fn.is_method AS is_method,
       caller_count, callee_count, coalesce(fn.change_count, 0) AS change_count, coalesce(fn.risk_score, 0.0) AS risk_score
ORDER BY risk_score DESC, fn.qualname
LIMIT $limit
"""

# Repo-wide function graph (the Functions page's graph half) -- same two-
# query shape as get_repo_map: pick a bounded, ranked candidate set first
# (here: most-called functions, MATCH rather than OPTIONAL MATCH so a
# function nobody calls doesn't clutter an overview graph, same reasoning
# repo map applies via risk_score), then find edges only among that
# already-selected set (FUNCTION_MAP_EDGES_AMONG), never the whole graph.
FUNCTION_MAP_CANDIDATES = """
MATCH (fn:Function)<-[:CALLS]-(caller:Function)
WITH fn, count(DISTINCT caller) AS caller_count
RETURN fn.id AS id, fn.name AS name, fn.qualname AS qualname, fn.path AS path, fn.language AS language, caller_count
ORDER BY caller_count DESC
LIMIT $limit
"""

FUNCTION_MAP_EDGES_AMONG = """
UNWIND $ids AS fid
MATCH (a:Function {id: fid})-[r:CALLS]->(b:Function)
WHERE b.id IN $ids
RETURN a.id AS source, b.id AS target, r.confidence AS confidence, r.call_count AS call_count
ORDER BY r.call_count DESC
LIMIT $edge_limit
"""

FUNCTION_DETAIL = """
MATCH (fn:Function {id: $id})
RETURN fn.id AS id, fn.name AS name, fn.qualname AS qualname, fn.path AS path, fn.language AS language,
       fn.start_line AS start_line, fn.end_line AS end_line, fn.is_exported AS is_exported, fn.is_method AS is_method,
       fn.source AS source
"""

FUNCTION_CALLERS = """
MATCH (caller:Function)-[r:CALLS]->(:Function {id: $id})
RETURN caller.id AS id, caller.name AS name, caller.path AS path, r.confidence AS confidence, r.call_count AS call_count
ORDER BY r.call_count DESC
LIMIT $limit
"""

FUNCTION_CALLEES = """
MATCH (:Function {id: $id})-[r:CALLS]->(callee:Function)
RETURN callee.id AS id, callee.name AS name, callee.path AS path, r.confidence AS confidence, r.call_count AS call_count
ORDER BY r.call_count DESC
LIMIT $limit
"""

# Rooted call graph around one function, one hop in each direction -- both
# callers and callees, since CALLS (unlike file coupling) is directed and a
# function's dependents matter as much as its dependencies. Bounded
# ORDER BY ... LIMIT fan-out, same idiom as BLAST_RADIUS_DIRECT.
FUNCTION_CALL_GRAPH_CALLEES_DIRECT = """
MATCH (fn:Function {id: $id})-[r:CALLS]->(callee:Function)
RETURN callee.id AS id, callee.name AS name, callee.path AS path, callee.qualname AS qualname,
       callee.language AS language, r.confidence AS confidence, r.call_count AS call_count
ORDER BY r.call_count DESC
LIMIT $limit
"""

FUNCTION_CALL_GRAPH_CALLERS_DIRECT = """
MATCH (caller:Function)-[r:CALLS]->(fn:Function {id: $id})
RETURN caller.id AS id, caller.name AS name, caller.path AS path, caller.qualname AS qualname,
       caller.language AS language, r.confidence AS confidence, r.call_count AS call_count
ORDER BY r.call_count DESC
LIMIT $limit
"""

# Second-degree propagation, one direction at a time -- callees of callees,
# and (separately) callers of callers -- same chained-MATCH-per-hop idiom as
# BLAST_RADIUS_TRANSITIVE.
FUNCTION_CALL_GRAPH_CALLEES_TRANSITIVE = """
MATCH (fn:Function {id: $id})-[:CALLS]->(direct:Function)
MATCH (direct)-[r:CALLS]->(indirect:Function)
WHERE indirect.id <> $id AND indirect <> direct
RETURN direct.id AS via, indirect.id AS id, indirect.name AS name, indirect.path AS path,
       indirect.qualname AS qualname, indirect.language AS language, r.confidence AS confidence, r.call_count AS call_count
ORDER BY r.call_count DESC
LIMIT $limit
"""

FUNCTION_CALL_GRAPH_CALLERS_TRANSITIVE = """
MATCH (fn:Function {id: $id})<-[:CALLS]-(direct:Function)
MATCH (direct)<-[r:CALLS]-(indirect:Function)
WHERE indirect.id <> $id AND indirect <> direct
RETURN direct.id AS via, indirect.id AS id, indirect.name AS name, indirect.path AS path,
       indirect.qualname AS qualname, indirect.language AS language, r.confidence AS confidence, r.call_count AS call_count
ORDER BY r.call_count DESC
LIMIT $limit
"""

# Unanchored: every same-file CALLS edge for one file's functions. A
# cross-file callee is still returned (as a boundary node carrying its own
# path) so the file's call graph shows "-> other_file.py:name" without
# pulling in that other file's internals -- modeled on REPO_MAP_COUPLING_
# AMONG's "start from an already-known candidate set" shape.
FILE_CALL_GRAPH_EDGES = """
MATCH (fn:Function {path: $path})-[r:CALLS]->(callee:Function)
RETURN fn.id AS source, callee.id AS target, callee.path AS target_path, callee.name AS target_name,
       callee.qualname AS target_qualname, callee.language AS target_language,
       r.confidence AS confidence, r.call_count AS call_count
"""
