# AGENTS.md

Repository-specific workflow instructions for coding agents

## Language Policy

- Write implementation code in English-oriented naming where practical.
- Use English for new function names, class names, variable names, and public
  API names unless compatibility requires otherwise.
- Write implementation-facing documentation in English.
- Write code comments in English.
- Use English for notebook-facing technical guidance, parameter descriptions,
  and developer notes unless the user explicitly asks for another language.

## Implementation Documentation Workflow

Every non-trivial implementation change must be documented in two steps:

1. Before editing source code, create or update an implementation plan in
   `implementation_plan/`.
2. After implementation and verification, create or update a change log entry in
   `change_log/`.

Small typo fixes, pure formatting, and mechanical documentation-only edits do
not require a new implementation plan, but they should still update existing
documentation if they change the meaning of an implemented feature.

## Paperflow-To-Implementation Workflow

When the user asks a research or design question and explicitly instructs the
agent to use paperflow, use the repository's paperflow workflow before making
implementation changes.

Required sequence:

```text
paperflow -> discussion -> implementation plan -> implementation -> notebook/API updates -> change log
```

Use this sequence as follows:

1. `paperflow`: create or update `paperflow/<request-slug>/request.md`,
   `run-manifest.yaml`, `run-log.md`, `literature_add_candidates.md`,
   per-paper summaries, and review artifacts as needed.
2. Google Drive connector: when paperflow is used, check the user's Google Drive
   library/Paperpile materials through the Google Drive connector when available,
   especially the canonical `Paperpile/paperpile.bib`, before falling back to
   free web search.
3. `discussion`: capture the research conclusion, design options, rejected
   alternatives, and implementation recommendation in the relevant paperflow
   review/proposal/discussion artifact.
4. `implementation plan`: create or update a dated file in
   `implementation_plan/` before changing source code.
5. `implementation`: make the code change according to the accepted plan.
6. `notebook/API updates`: update notebooks, analysis helpers, public exports,
   or API-facing docs needed to exercise the new behavior.
7. `change log`: after verification, create or update a dated file in
   `change_log/` and link back to both the paperflow discussion and the
   implementation plan.

Do not use paperflow automatically for every implementation. Use it when the
user asks for it, when the question depends on literature-grounded design, or
when the task explicitly starts from a paperflow request.

## Implementation Plan Requirements

Create a dated Markdown file:

```text
implementation_plan/YYYY-MM-DD-short-topic.md
```

The plan should include:

- goal and motivation;
- current problem at the time of planning;
- why this implementation is needed now;
- relevant git base, branch, or worktree state when useful;
- affected modules/files;
- public parameters or API changes;
- update equations or algorithm details for model changes;
- expected behavior;
- tests or notebook checks that will verify the change;
- explicit non-goals when scope could otherwise expand.

If the implementation is a continuation of an existing plan, update that plan
instead of creating a duplicate.

The current-problem section should be concrete. Prefer observed failures,
diagnostic results, missing API/notebook support, confusing model behavior, or
research conclusions that make the implementation necessary. Avoid only stating
the desired feature.

## Change Log Requirements

After the implementation is complete, create or update a dated Markdown file:

```text
change_log/YYYY-MM-DD-short-topic.md
```

The change log should include:

- date and relevant git commit hash, or note that the change is still
  uncommitted;
- what changed in code, notebooks, tests, and documentation;
- why the change was made;
- verification performed, including exact test commands when run;
- result or observed behavior;
- known limitations and next steps.

If a change implements a prior plan, link the plan from the change log. If the
implementation changes direction, update the plan or state why the final design
differs.

## Index Maintenance

When adding a new implementation plan or change log:

- update `implementation_plan/README.md`;
- update `change_log/README.md`;
- keep links relative and valid after moving files.

## Source And Notebook Separation

This repository separates reusable source code from execution-facing jupyter notebook
work.

- Keep research and simulation logic in the Python package under `src/`.
- Treat notebooks as execution clients of the package rather than as the home
  of core logic.
- When adding exploratory or runnable analysis artifacts, prefer `marimo`
  notebooks under `notebooks/` so the execution side stays reproducible and
  scriptable.
- Structure new notebook work so it imports from `src/` instead of duplicating
  model code, numerical kernels, or data-processing logic inside notebook cells.
- If a notebook reveals a reusable helper, promote that logic back into `src/`
  and keep the notebook focused on orchestration, parameter selection,
  visualization, and experiment-specific commentary.
- When implementation changes affect how experiments are run, update the
  relevant jupyter notebook entrypoints or notebook-facing documentation along
  with the source code.


## Git And Worktree Safety

- Do not revert unrelated user changes.
- Before editing, check `git status --short`.
- If notebooks or generated outputs are already modified and unrelated to the
  task, leave them untouched.
- Prefer source, test, and documentation changes over committing generated logs
  or large output artifacts.

## Command Approval Hygiene

To reduce repeated execution-approval prompts in this repository:

- Prefer `rg`, `sed`, and `jq` for code search, text inspection, and notebook or
  JSON metadata checks.
- For `.ipynb` inspection, use `jq` against the notebook JSON directly by
  default.
- Avoid reading JSON or notebook structure through `python - <<'PY'` and
  similar heredoc-style arbitrary Python execution when a standard shell tool or
  an existing script can answer the question.
- Prefer existing approved test and verification entrypoints over ad hoc
  one-off scripts.
- Treat arbitrary script execution as a last resort, and keep any required
  approval request narrowly scoped to the exact command family being used.
