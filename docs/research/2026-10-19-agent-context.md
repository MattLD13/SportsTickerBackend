# Agent context review

Reviewed on October 19, 2026.

## Decision

Keep one short shared guide and scoped domain guides.
Prepare task packets before source exploration.
Use native hooks for supported clients and the shared startup command for instruction-only clients.
Keep mechanical validation in code and CI.
Keep recipes and research outside startup instructions.

## Evidence and adoption

| Evidence | Observation | Repository decision |
|---|---|---|
| [OpenAI instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | Codex loads repository guidance through its instruction hierarchy. | Keep `AGENTS.md` as the canonical guide. |
| [OpenAI hooks](https://learn.chatgpt.com/docs/hooks) | Trusted repository hooks can inject context at session and prompt boundaries. | Prepare scope before planning and restore packet references after compaction. |
| [Claude memory](https://code.claude.com/docs/en/memory) | Imports load their content at startup. Splitting an unconditional import does not reduce context. | Import only the short shared guide. Keep detailed guides on demand. |
| [Claude hooks](https://code.claude.com/docs/en/hooks) | Prompt hooks receive task text and can return additional context. | Use static hook commands and JSON input. Never interpolate task text into commands. |
| [Gemini context](https://geminicli.com/docs/cli/gemini-md/) | Gemini supports file imports and scoped context. | Use a small `GEMINI.md` bridge. |
| [Gemini hooks](https://geminicli.com/docs/hooks/reference/) | `BeforeAgent` runs before planning and accepts additional context. | Use the same task router with Gemini's event name. |
| [Cursor rules](https://cursor.com/docs/rules) | Cursor supports root and nested `AGENTS.md` files. | Use the existing guide rather than another duplicate rules directory. |
| [Copilot support](https://docs.github.com/en/copilot/reference/custom-instructions-support) | Supported instruction formats differ across Copilot products. | Add a small repository instruction bridge. |
| [Reddit: managing AGENTS.md](https://www.reddit.com/r/codex/comments/1t248sh/managing_your_agentsmd/) | Practitioners report less exploration with short routing guides and targeted references. | Use a task packet and scoped search. Treat the reported benefits as anecdotal. |
| [Reddit: generated guides](https://www.reddit.com/r/ClaudeCode/comments/1x3zhlj/are_generated_claudemd_files_good_or_bad_practice/) | Recent discussion favors short indexes and focused domain instructions. | Remove duplicated Claude rules and shorten the testing guide. |
| [Repository context study](https://arxiv.org/abs/2602.11988) | The study found no general task-success improvement and higher inference cost in its evaluated settings. | Keep instructions minimal. Measure this repository separately. |

## X research limits

Search identified Boris Cherny's [setup thread](https://x.com/bcherny/status/2007179832300581177) and [team thread](https://x.com/bcherny/status/2017742741636321619).
Direct retrieval failed for both posts.
A [Reddit repost](https://www.reddit.com/r/AgentsOfAI/comments/1q2s83g/boris_cherny_creator_of_claude_code_shares_his/) links the original setup thread.
Community copies describe shared project guidance, reusable validation, and learned corrections.
Those copies do not verify an internal Anthropic configuration.
This change uses official hook contracts and repository checks, not an unverified copied configuration.

## Excluded practices

- Mandatory broad repository scans before every task.
- Unconditional imports of every domain guide.
- Permission bypasses or changes to user-level agent configuration.
- Automatic deployment, firmware flashes, or test runs from prompt hooks.
- Unlimited additions to a shared memory file after each task.
- Arbitrary read limits that prevent investigation of a real dependency.
- Automatic delegation without user authorization.

## Measurement limits

The checks measure instruction size, selected files, Git safety, and hook output.
They do not measure model task success, inference tokens, or response speed.
No agent performance multiplier follows from these checks.
An existing conversation keeps its earlier context.
