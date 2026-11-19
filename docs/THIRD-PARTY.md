# Third-party sources

Checked through the GitHub REST API on 2026-11-19 (license = SPDX id reported by GitHub; stars and last push are
a rough activity signal, not a trust rating). Re-check each source in the research step of the phase that uses
it, including a manual read of its license file and a review of the code before any reuse.

Reuse classes are defined in [DESIGN.md](DESIGN.md) section 8.

| Repository | License | Stars | Last push | Language | Class | Used by |
|---|---|---|---|---|---|---|
| NousResearch/hermes-agent | MIT | 264715 | 2026-11-19 | Python | vendor-ok | all |
| open-world-project/model-router | MIT | 33 | 2026-05-10 | Python | vendor-ok | M3 |
| Zelray/hermes-model-router | MIT | 2 | 2026-05-26 | Python | vendor-ok | M3 |
| Waylish/hermes-smart-model-routing | MIT | 3 | 2026-06-07 | Python | vendor-ok | M3 |
| Shaf2665/Hermes-router | MIT | 111 | 2026-11-12 | Python | vendor-ok | M3 |
| 0xzr/freellmpool | MIT | 152 | 2026-11-06 | Python | vendor-ok | M3 |
| kerpopule/hermes-jev-skills | MIT | 1353 | 2026-11-18 | Python | vendor-ok | M7 |
| 42-evey/hermes-plugins | MIT | 556 | 2026-10-24 | Python | vendor-ok | M6 |
| tashfeenahmed/freellmapi | MIT | 55147 | 2026-11-19 | TypeScript | vendor-ok, run as process | M3 |
| cheaper-inference/OmniRoute | MIT | 88898 | 2026-11-19 | TypeScript | vendor-ok, run as process | M3 |
| decolua/9router | MIT | 32641 | 2026-11-16 | JavaScript | vendor-ok, run as process | M3 |
| zaber-dev/free-ai-gateway | MIT | 18 | 2026-09-21 | TypeScript | vendor-ok, run as process | M3 |
| ihuzaifashoukat/free-ai-router | none | 22 | 2026-03-28 | TypeScript | reference-only | M3 |
| mnfst/awesome-free-llm-apis | CC0-1.0 | 13725 | 2026-11-19 | JavaScript | vendor-ok (data) | M2 |
| open-free-llm-api/awesome-freellm-apis | MIT | 5824 | 2026-11-19 | n/a | vendor-ok (data) | M2 |
| mvalentsev/awesome-free-ai-coding | MIT | 250 | 2026-11-19 | Python | vendor-ok (data) | M2 |
| ClawLabsAI/free-ai-models | MIT | 279 | 2026-11-19 | JavaScript | vendor-ok (data) | M2 |
| raullenchai/free-llm-api-resources | none | 316 | 2026-04-17 | n/a | reference-only | M2 |
| ZeroPointRepo/awesome-hermes-skills | MIT | 687 | 2026-11-02 | n/a | vendor-ok (index) | research |
| BkashJEE/hermes-bot-forge | MIT | 152 | 2026-11-13 | Python | vendor-ok | M7 |
| UmLyrithyreach/orchestrator | MIT | 0 | 2026-11-03 | n/a | vendor-ok | M7 |
| mattpocock/skills | MIT | 328038 | 2026-11-19 | Shell | vendor-ok | M7 |
| marlandoj/zouroboros-swarm-executors | none | 1 | 2026-09-28 | TypeScript | reference-only | M11 |
| outsourc-e/hermes-workspace | MIT | 6833 | 2026-11-05 | JavaScript | vendor-ok | M9 |
| h4dex/opc-nexus | MIT | 241 | 2026-09-03 | TypeScript | vendor-ok | M11 |
| ogallotti/rtk-hermes | MIT | 304 | 2026-05-04 | Python | vendor-ok | M8 |
| vincentkoc/tokenjuice | MIT | 544 | 2026-11-18 | TypeScript | vendor-ok, run as process | M8 |
| SGavrl/hermes-plugin-obscura | Apache-2.0 | 50 | 2026-09-11 | Python | vendor-ok | M8 (optional) |
| danbiocchi/hermes-vcc-engine | Apache-2.0 | 30 | 2026-11-13 | Python | vendor-ok | M8 |
| OthmanAdi/planning-with-files | MIT | 28144 | 2026-11-11 | Shell | vendor-ok | M8 |
| ChrisLamDev/hermes-core-skills | MIT | 13 | 2026-07-01 | Python | vendor-ok | M8 |
| DietrichGebert/ponytail | MIT | 194752 | 2026-10-29 | JavaScript | vendor-ok | build practice |
| WolfMark-Ltd/spendsense | GPL-3.0 | 62 | 2026-11-19 | Python | process-only | M4 |
| Hiutaky/token-saver | MIT | 4 | 2026-09-05 | Python | vendor-ok | M4 |
| Diabloluo/hermes-hud | MIT | 11 | 2026-11-10 | Python | vendor-ok | M9 |
| Kori-x/hermes-dashboard | MIT | 68 | 2026-04-08 | TypeScript | vendor-ok | M5, M9 |
| willingning-coder/eagle-eye | MIT | 47 | 2026-06-01 | Python | vendor-ok | M5 |
| freehul/progressive-skill | MIT | 10 | 2026-10-14 | Python | vendor-ok | M5 |
| jiangyuxue666/skill-auto-maintain | MIT | 5 | 2026-05-18 | Python | vendor-ok | M5 |
| MyAiFreedomSystems/hooks-guide | MIT | 0 | 2026-08-14 | n/a | vendor-ok | M0 |
| JerryLiu369/hermes-proactive-agent | unverified | | | | reference-only until resolved | M6 |
| Rainhoole/hermes-agent-acp-skill | not found | | | | reference-only until resolved | M11 |

## Findings that need action

- **JerryLiu369/hermes-proactive-agent** returned "Moved Permanently". Follow the redirect and re-check owner,
  license and history before use (M6 research).
- **Rainhoole/hermes-agent-acp-skill** returned "Not Found". Treat the name as unconfirmed; find the real source
  or build the ACP connector from the protocol specification (M11 research).
- **WolfMark-Ltd/spendsense** is GPL-3.0. Do not copy or import it into this Apache-2.0 project.
- Three sources have no license. No license means no permission to copy.
- Several sources have very few stars or no recent activity. Low adoption means less outside review: read the
  code fully and prefer re-implementing small ideas over taking a dependency.

## Rules for adding a dependency

1. License is on the allow-list; license file read, not just the API field.
2. Maintained (release or commit within 12 months) or small enough to own.
3. No open critical advisory (OSV, GitHub Advisory Database).
4. Pinned by version and hash; added to the SBOM and `NOTICE`.
5. Recorded in the phase Q&A with the alternative considered, including "write it ourselves".
