# GitHub Projects V2 GraphQL Snippets

Reference for the queries and mutations used by `promote-shipped`. The skill's
scripts already wrap these — this file exists for debugging, schema exploration, and
when you need to vary a field outside the script defaults.

## Required token scopes

```bash
gh auth refresh -s read:project,project
```

`read:project` is enough to discover/inventory; `project` is required to mutate
(`updateProjectV2ItemFieldValue`).

## 1. Discover boards linked to a repository

```graphql
query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) {
    projectsV2(first:50) {
      nodes { id title number url closed }
    }
  }
}
```

```bash
gh api graphql -f query="$QUERY" -f owner=OWNER -f name=REPO
```

Use `-f` for `String!`/`ID!` variables and reserve `-F` for real `Int!`/`Boolean!`
ones: `-F` type-infers, so an all-numeric owner or repo name would be sent as an
`Int` and rejected.

Filter out `closed: true` boards — they're archived and won't accept mutations.

## 2. Inventory items + fields

Two queries: one for the project metadata + Status field options, one paged for items.

### Metadata + fields

```graphql
query($id:ID!) {
  node(id:$id) {
    ... on ProjectV2 {
      id title number
      fields(first:50) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id name
            options { id name }
          }
        }
      }
    }
  }
}
```

Status field selection heuristic (in order):
1. Single-select field whose name is exactly "status" (case-insensitive)
2. First single-select field that contains an option matching `done|released|shipped`

### Items (paged, 100 per call)

```graphql
query($id:ID!, $cursor:String) {
  node(id:$id) {
    ... on ProjectV2 {
      items(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          fieldValues(first:30) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                field { ... on ProjectV2SingleSelectField { id name } }
                name optionId
              }
            }
          }
          content {
            __typename
            ... on Issue {
              number title state stateReason url
              repository { nameWithOwner }
              closedByPullRequestsReferences(first:10, includeClosedPrs:true) {
                nodes { number title url merged mergedAt baseRefName state
                        mergeCommit { oid }
                        repository { nameWithOwner } }
              }
            }
            ... on PullRequest {
              number title state url merged mergedAt baseRefName
              mergeCommit { oid }
              repository { nameWithOwner }
            }
            ... on DraftIssue { title }
          }
        }
      }
    }
  }
}
```

`closedByPullRequestsReferences` returns PRs that referenced the issue with a
`Closes #N`-style keyword OR were manually linked via the "Linked pull requests"
sidebar. It does NOT include PRs that merely mention `#N` without a closing keyword.

Three fields here are load-bearing for `find-promotable.sh` and must not be dropped
when trimming this query: `stateReason` on the Issue (separates `wontfix` from
`nopr`) and `mergeCommit { oid }` on **both** the linked-PR nodes and the top-level
PullRequest fragment (the SHA the reachability check compares against the base
branch — without it every candidate resolves `no-sha` and nothing is promotable).

### Fallback: discovering the closing PR from the issue timeline

Git Flow merges the PR to `develop`, and GitHub records the closing link only on
default-branch merges — so `closedByPullRequestsReferences` is empty for the normal
case. `find-promotable.sh` falls back to the timeline:

```graphql
query($owner:String!,$repo:String!,$num:Int!){
  repository(owner:$owner,name:$repo){
    issue(number:$num){
      timelineItems(last:80, itemTypes:[CLOSED_EVENT, CONNECTED_EVENT, CROSS_REFERENCED_EVENT]){
        nodes{
          __typename
          ... on ClosedEvent { closer { __typename ... on PullRequest { number merged baseRefName mergedAt body mergeCommit{oid} } } }
          ... on ConnectedEvent { subject { __typename ... on PullRequest { number merged baseRefName mergedAt body mergeCommit{oid} } } }
          ... on CrossReferencedEvent { source { __typename ... on PullRequest { number merged baseRefName mergedAt body mergeCommit{oid} } } }
        }
      }
    }
  }
}
```

A cross-referenced PR is kept only when its `body` carries a closing keyword for
that exact issue; connected/closer PRs are kept directly. If this query FAILS, the
result is `hold-discovery-failed` — never an empty PR list, which would be read as
positive evidence of a no-PR closure and promote the item.

## 3. Mutation — set Status to Done

```graphql
mutation($pid:ID!, $iid:ID!, $fid:ID!, $oid:String!) {
  updateProjectV2ItemFieldValue(input:{
    projectId:$pid
    itemId:$iid
    fieldId:$fid
    value:{singleSelectOptionId:$oid}
  }) {
    projectV2Item { id }
  }
}
```

Variables:
- `pid` — `ProjectV2.id` (PVT_…)
- `iid` — `ProjectV2Item.id` (PVTI_…)
- `fid` — `ProjectV2SingleSelectField.id` (PVTSSF_…)
- `oid` — option id from `field.options[].id` (string, not ID!)

Idempotent: re-running with the same option ID is a no-op.

## Common debugging recipes

```bash
# Show all field types on a board (not just single-select)
gh api graphql -f query='query($id:ID!){node(id:$id){...on ProjectV2{fields(first:50){nodes{__typename ... on ProjectV2FieldCommon{id name}}}}}}' -f id="$BOARD_ID" | jq

# Count items by status without parsing
gh api graphql -f query='query($id:ID!){node(id:$id){...on ProjectV2{items(first:100){nodes{fieldValues(first:30){nodes{...on ProjectV2ItemFieldSingleSelectValue{name field{...on ProjectV2SingleSelectField{name}}}}}}}}}}' -f id="$BOARD_ID" \
  | jq '[.data.node.items.nodes[].fieldValues.nodes[]?|select(.field.name=="Status")|.name]|group_by(.)|map({status:.[0],count:length})'

# Find an item's project linkage from an issue number
gh api graphql -f query='query($owner:String!,$name:String!,$num:Int!){repository(owner:$owner,name:$name){issue(number:$num){projectItems(first:10){nodes{id project{title}}}}}}' \
  -f owner=OWNER -f name=REPO -F num=741
```

## Status option name conventions seen in the wild

| Pattern | Treat as Done? |
|---------|----------------|
| `Done` | ✓ |
| `✅ Done` / `✅ done` | ✓ |
| `Released` / `Shipped` / `Live` | ✓ |
| `Done in develop` / `Dev complete` / `In develop` | ✗ — these are the SOURCE columns the skill promotes FROM |
| `In review` / `Ready for release` / `Staged` | ✗ — also source columns |
| `Backlog` / `Todo` / `Ready` / `In progress` | ✗ — pre-merge states; skill ignores these via the `state == CLOSED` filter on issues |

The skill's heuristic picks the option matching `^(done|✅ ?done|released|shipped)$`
case-insensitive, falling back to any option containing `done|released|shipped`. If
your board uses something exotic (e.g. `🚀 Launched`), you'll need to tweak the
regex in `inventory-board.sh` or supply `--done-option-name` (future enhancement).
