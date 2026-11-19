# Pre-work Q&A: <phase id> <name>

Date: YYYY-MM-DD. Previous phase: <id>, tag <vX.Y.Z>.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Hermes API changes since last phase | | |
| Each upstream source in `MODULES.md` for this phase | | |
| Advisories for planned dependencies | | |
| Current best practice for this problem | | |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | What is the smallest scope that meets the acceptance criteria? | | | |
| 2 | Which capabilities does the module need, and which can be dropped? | | | |
| 3 | Reuse, adapt or write: which upstream code, under which reuse class? | | | |
| 4 | New dependencies: are all five rules in `THIRD-PARTY.md` met? | | | |
| 5 | What can go wrong for security (inputs, secrets, spend, egress)? How is each tested? | | | |
| 6 | State schema and migration; what is removed on uninstall? | | | |
| 7 | Control surface: tools, commands, panel, config keys | | | |
| 8 | Logs, metrics, report section, alerts | | | |
| 9 | Update source and rollback check | | | |
| 10 | Does anything need a core contract change (ADR)? | | | |
| 11 | Operator input needed (names only for secrets)? | | | |

## 4. Acceptance tests (written before code)

- [ ] 

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
