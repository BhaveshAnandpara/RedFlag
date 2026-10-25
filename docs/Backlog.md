# Backlog

Things to do later, not now. An item sits here until it's picked up; picking one up means moving
it into actual work (and usually discussing it first), not just starting to build.

| # | Task | Where | Status |
|---|---|---|---|
| 1 | Give a "select all" / "deselect all" for each type on the MCP tool list, not just one global toggle. | `frontend/src/components/mcp-page.tsx` (the tool list, filterable by all / reads / changes / ticked) | **Done.** The "Tick all" / "Untick all" button now acts on whichever filtered or searched set is currently shown, not always all 46 tools. It shows a count, e.g. "Untick all (2)", whenever that's narrower than the full list. Tested in `mcp-page.test.tsx`. |

