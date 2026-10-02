# GraphQL snippets and the measured ProjectV2 capability model

Every query and mutation the skill issues, copy-pasteable, plus what the API
genuinely can and cannot do.

All capability claims below were measured on **2026-09-16 with gh 2.96.0**
against real boards, not read from docs. Re-run
[Capability re-check](#capability-re-check) before trusting them after a GitHub
API change.

## Contents

- [What the API can and cannot do](#what-the-api-can-and-cannot-do)
- [The single-select option `id` trap](#the-single-select-option-id-trap)
- [Resolve owner and repo node ids](#resolve-owner-and-repo-node-ids)
- [Inspect a ProjectV2](#inspect-a-projectv2)
- [Copy a project](#copy-a-project)
- [Link a ProjectV2 to a repo](#link-a-projectv2-to-a-repo)
- [Update a single-select field's options](#update-a-single-select-fields-options)
- [Create and update views](#create-and-update-views)
- [Workflows](#workflows)
- [Capability re-check](#capability-re-check)

## What the API can and cannot do

| Thing | Mutation | Status |
|---|---|---|
| Create a project | `createProjectV2` | ✅ |
| Copy a project | `copyProjectV2` / `gh project copy` | ✅ |
| Create / update / delete a field | `createProjectV2Field`, `updateProjectV2Field`, `deleteProjectV2Field` | ✅ (see the `id` trap) |
| Create / update / delete a **view** | `createProjectV2View`, `updateProjectV2View`, `deleteProjectV2View` | ✅ name, layout, filter, visible fields only |
| Board **columns** (`verticalGroupByFields`) | — | ❌ read-only |
| **Swimlanes** (`groupByFields`) | — | ❌ read-only |
| View sort order (`sortByFields`) | — | ❌ read-only |
| Add / archive / delete items | `addProjectV2ItemById`, `archiveProjectV2Item`, … | ✅ |
| Link to a repo or team | `linkProjectV2ToRepository`, `linkProjectV2ToTeam` | ✅ |
| Create or enable a **workflow** | — | ❌ only `deleteProjectV2Workflow` exists |
| Mark as template | `markProjectV2AsTemplate` | ⚠️ org-owned projects only — on a user-owned project it fails with *"Only projects owned by an Organization can be marked as a template"* |

`ProjectV2ViewConfigurationInput` accepts exactly one field, `visibleFieldIds`.
That is why columns and swimlanes cannot be set: there is no input for them.
**A copy is the only way to reproduce a grouped board.**

`ProjectV2Workflow` exposes only `id`, `name`, `number`, `enabled`, `createdAt`,
`updatedAt`, `project`. The rule body and any filter string are not readable, so
no tool can inspect or rewrite a workflow's filter.

### What `gh project copy` actually carries

Measured by copying a board and diffing it, then comparing against a bare
`gh project create`:

| Carried | Not carried |
|---|---|
| All fields and their dataTypes | **Every workflow** |
| Single-select options: name, colour, description | Items (unless `--include-draft-issues`) |
| Views: name, layout, filter | |
| Board **columns** and **swimlanes** | |

The six workflows that appear on a copy — `Item added to project`,
`Item closed`, `Pull request merged`, `Pull request linked to issue`,
`Auto-close issue`, `Auto-add sub-issues to project` — are **GitHub defaults,
enabled on every new project**, including an empty `gh project create`. They are
project-scoped and carry no repo filter, so there is nothing to rewrite on them
after a copy.

`Auto-add to project` is the only repo-scoped workflow. It is not a default, it
never survives a copy, and no mutation can create it. **Enabling it is the one
unavoidable manual step**, at:

- user project: `https://github.com/users/<owner>/projects/<n>/workflows`
- org project:  `https://github.com/orgs/<owner>/projects/<n>/workflows`

with filter `repo:<owner>/<repo> is:issue,pr is:open`.

## The single-select option `id` trap

`updateProjectV2Field` **replaces** the option list.
`ProjectV2SingleSelectFieldOptionInput` has an optional `id`, documented as
*"Include this to preserve the option's identity during updates, preventing item
field values from being cleared."*

Omitting `id` does more damage than that doc string suggests. Measured on a
fresh board carrying the 6 default workflows:

| Call | Workflows left enabled |
|---|---|
| `updateProjectV2Field` with options **lacking** `id` | **1 of 6** |
| The same call with each option's existing `id` | **6 of 6** |

Recreating the options orphans every workflow action that referenced them
(`Item closed` → set Status to Done, and so on), and GitHub silently disables
those workflows. Because `deleteProjectV2Workflow` is the only workflow
mutation, **this cannot be undone via the API** — it is a UI-only repair.

Always fetch the existing options first and echo their ids back.

## Resolve owner and repo node ids

```graphql
query($login: String!) { user(login: $login) { id } }
query($login: String!) { organization(login: $login) { id } }
query($login: String!, $name: String!) {
  repository(owner: $login, name: $name) { id nameWithOwner }
}
```

## Inspect a ProjectV2

Used by `inspect-template.sh`. `verticalGroupByFields` and `groupByFields` are
selected by **name**, not `totalCount` — a count cannot prove a copy carried the
right column or swimlane field.

```graphql
query($login: String!, $number: Int!) {
  user(login: $login) {
    projectV2(number: $number) {
      id number title public closed url
      views(first: 50) {
        nodes {
          id name number layout filter
          verticalGroupByFields(first: 10) { nodes { ... on ProjectV2FieldCommon { name } } }  # columns
          groupByFields(first: 10)         { nodes { ... on ProjectV2FieldCommon { name } } }  # swimlanes
          sortByFields(first: 10)          { nodes { direction field { ... on ProjectV2FieldCommon { name } } } }
        }
      }
      workflows(first: 50) { nodes { id name number enabled } }
      fields(first: 50) {
        nodes {
          ... on ProjectV2Field             { id name dataType }
          ... on ProjectV2SingleSelectField { id name dataType options { id name color description } }
          ... on ProjectV2IterationField    { id name dataType configuration { duration startDay iterations { id title duration startDate } } }
        }
      }
    }
  }
}
```

Swap `user(login: $login)` for `organization(login: $login)` when the owner is
an org. `gh api graphql` exits 0 on a `data: null` + `errors` envelope, so check
for `.errors` before trusting a response.

## Copy a project

```bash
gh project copy <source-number> \
  --source-owner <login> --target-owner <login> \
  --title "<new title>" --format json
```

```graphql
mutation($src: ID!, $owner: ID!, $title: String!) {
  copyProjectV2(input: { projectId: $src, ownerId: $owner, title: $title }) {
    projectV2 { id number url }
  }
}
```

Copying between different owners requires admin on both sides.

## Link a ProjectV2 to a repo

```graphql
mutation($pid: ID!, $rid: ID!) {
  linkProjectV2ToRepository(input: { projectId: $pid, repositoryId: $rid }) {
    repository { nameWithOwner }
  }
}
```

## Update a single-select field's options

Fetch ids first, then send them back — see [the `id` trap](#the-single-select-option-id-trap).

```graphql
query($login: String!, $number: Int!) {
  user(login: $login) {
    projectV2(number: $number) {
      fields(first: 50) {
        nodes { ... on ProjectV2SingleSelectField { id name options { id name color description } } }
      }
    }
  }
}
```

```graphql
mutation($fid: ID!) {
  updateProjectV2Field(input: {
    fieldId: $fid
    singleSelectOptions: [
      { id: "<existing-id>", name: "Todo",                 color: GRAY,   description: "Accepted, not started" }
      { id: "<existing-id>", name: "Up Next",              color: BLUE,   description: "Queued for the current milestone" }
      { id: "<existing-id>", name: "In Progress",          color: YELLOW, description: "Actively being worked on" }
      { id: "<existing-id>", name: "Development Complete", color: ORANGE, description: "Merged to develop, awaiting release" }
      { id: "<existing-id>", name: "Done",                 color: PURPLE, description: "Shipped to main" }
    ]
  }) { projectV2Field { ... on ProjectV2SingleSelectField { options { id name color } } } }
}
```

`gh api graphql -F opts=<json>` **cannot** pass a list of input objects — it
sends the array as a string and the request fails with *"Expected … to be a
key-value object"*. Inline the option literals into the query text, or send a
full JSON body with `gh api graphql --input`.

Valid colours: `GRAY BLUE GREEN YELLOW ORANGE RED PINK PURPLE`.

## Create and update views

Real, but limited to name, layout, filter and visible fields. Neither mutation
can set columns or swimlanes.

```graphql
mutation($pid: ID!) {
  createProjectV2View(input: { projectId: $pid, name: "Kanban", layout: BOARD_LAYOUT }) {
    projectV2View { id name layout }
  }
}

mutation($vid: ID!) {
  updateProjectV2View(input: { viewId: $vid, name: "Kanban", filter: "is:open" }) {
    projectV2View { id name layout filter }
  }
}
```

Layouts: `BOARD_LAYOUT`, `TABLE_LAYOUT`, `ROADMAP_LAYOUT`.

A view created this way lands ungrouped: no columns, no swimlanes, and no way to
add them. Prefer copying the template.

## Workflows

There is no mutation to create, enable or disable a workflow. The schema exposes
only:

```graphql
mutation($wid: ID!) {
  deleteProjectV2Workflow(input: { workflowId: $wid }) { clientMutationId }
}
```

Read current state with:

```graphql
query($login: String!, $number: Int!) {
  user(login: $login) {
    projectV2(number: $number) { workflows(first: 50) { nodes { id name number enabled } } }
  }
}
```

## Capability re-check

Re-run these before trusting anything above after a GitHub API change:

```bash
# Which ProjectV2 mutations exist at all
gh api graphql -f query='{ __schema { mutationType { fields { name } } } }' \
  --jq '.data.__schema.mutationType.fields[].name' | grep -i projectv2 | sort

# Whether view configuration ever gains a grouping input
gh api graphql -f query='{ __type(name: "ProjectV2ViewConfigurationInput") { inputFields { name } } }' \
  --jq '.data.__type.inputFields[].name'

# Whether a bare new project still ships the six default workflows
gh project create --owner <login> --title ZZ-probe --format json
```
