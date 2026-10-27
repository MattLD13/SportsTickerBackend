# Writing and change rules

## Writing

Write documentation, comments, docstrings, and commit messages in Simplified Technical English.
Use at most 20 words for an instruction sentence and 25 words for an explanation sentence.
Put a condition before its command.
Use only the modals `can`, `will`, and `must`.
Use active voice. Use no semicolons. Use one word for each concept.
Keep code, identifiers, commands, file paths, and quoted errors exact.

## Change evidence

Before a commit, record these facts:

1. The owner of the changed fact or behavior.
2. The former path removed or simplified.
3. The real input and output that prove the new path.

If a test fails, find the cause before changing its assertion.
Do not add skips, dummy modules, or broad exception handlers to conceal failures.
If an assertion is wrong, explain the contract and replace the assertion with direct evidence.

## Context maintenance

Keep rules that apply to every task in the root `AGENTS.md`.
Keep domain rules in the nearest scoped `AGENTS.md`.
Keep recipes, research, history, and long explanations in `docs/`.
Update the existing owner when a rule changes. Do not duplicate rules across agent products.
If a repeated mistake reveals a stable invariant, add a focused check and one short instruction at its owner.
Do not append every task outcome or temporary workaround to startup instructions.

## Publishing

Workspace selection and deployment selection have separate owners.
An isolated task workspace does not prove that only one deployed component changes.
Run full repository CI before publishing through the existing workflow.
The task context hooks do not publish, deploy, run tests, or change hardware state.
