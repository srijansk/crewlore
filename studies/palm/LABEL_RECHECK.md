# Re-check: did the declined pull requests' changes land later?

The study calls a pull request declined when it was closed without merging after a reviewer requested changes, and it counts a stored claim as poisoned when the claim states that pull request's approach as current practice. A closed pull request is not always a rejected approach: a maintainer can merge the same change in a pull request of their own. On 2026-10-21 each of the 60 declined pull requests in the sample was checked against its repository for a later landing of the same change.

28 of the 60 landed in full and 7 in part: 35 of 60. In 20 of those 35, the change was in the repository by the time the agent's pull request was closed or within two days: 12 of those through a maintainer's own pull request, the rest through a maintainer's direct commit or the agent's own re-filed pull request. One of them, spring-projects/spring-kafka #3944, was merged by hand ("Merged via" a commit) and was never declined. For these pull requests the label meant "this pull request was not merged", not "the team turned the approach down".

The README, the write-up and every published copy are unchanged by this record.

## Method

1. **The sample.** `sample_prs(n=60, seed=20260818)` rebuilds the sample, as `analyze.py` does. Before any change, `label_recheck/recompute.py` reproduces every number in the README's results table and every published paired comparison exactly.
2. **Leads.** `label_recheck/collect.py` makes read-only GitHub calls for each declined pull request. It records:
   - the timeline's cross-references;
   - pull request numbers and closing phrases in its comments, with bots skipped;
   - merged pull requests in the same repository with similar titles, from 14 days before it opened to 180 days after it closed;
   - the share of its new, non-trivial added lines found at each candidate's merge commit, on its base branch 30 and 180 days after closing, and today.
3. **Review.** Six model reviewers (Claude agents) each took ten pull requests and followed one rubric, `label_recheck/BRIEF.md`. A reviewer read the pull request, its candidates, and the commits that touched its most-changed files in the 180 days after it closed. Each pull request got a verdict of `LANDED`, `PARTLY`, `NOT_LANDED` or `UNKNOWN`, with links. For `LANDED` and `PARTLY` pull requests, the reviewer also judged each poisoned claim as `TRUE_NOW` (true of the code once the change landed), `STILL_WRONG` or `UNCLEAR`.
4. **Checks.**
   - A script confirmed that every cited pull request or commit exists, is merged, is in the same repository and has the stated date.
   - Eight landings were checked by hand against the pull requests, their files or diffs, and the threads: spring-kafka #3944, InvokeAI #8177, vite-plugin-react #631, testfx #5606, celestia-core #2042, inspector #126, react-native-windows #14794 and formance ledger #918.
   - The automated leads had nothing for 11 of the 35 landings. The reviewers found those through linked issues, file history and maintainers' own commits. 5 of the 25 pull requests that did not land had a lead that turned out to be false.
5. The sealed key kept for blind human labelling was not opened.

`label_recheck/verdicts.json` has every pull request's verdict, the change that landed, the time from closing to landing, and the links. The claim-level verdicts and the GitHub caches stay in `local/aidev/label_recheck/` with the rest of the study's data.

## Which declined pull requests landed

| | Pull requests |
|---|---|
| Landed | 28 |
| Landed in part | 7 |
| Not landed | 25 |
| Could not be checked | 0 |

When the 35 changes reached the repository, measured from the agent's pull request closing:

| Time | Pull requests |
|---|---|
| Before or as it closed | 6 |
| Within two days | 14 |
| 3 to 30 days | 11 |
| 31 to 180 days | 4 |

| Pull request | Verdict | Landed through | After closing | What landed |
|---|---|---|---|---|
| [whitphx/streamlit-webrtc#1930](https://github.com/whitphx/streamlit-webrtc/pull/1930) | landed | [#1936](https://github.com/whitphx/streamlit-webrtc/pull/1936) | before | The maintainer had already moved the project from npm to pnpm (#1932) and from Poetry to uv. |
| [espressif/esptool#1103](https://github.com/espressif/esptool/pull/1103) | landed | [b53a16c](https://github.com/espressif/esptool/commit/b53a16ca60fd86e1c6a1da91367dc924fab9b0d3) | before | The reviewer committed the same `--port-filter` parsing fix ("Closes #1103"), applied only to options that take several values. |
| [metacraft-labs/codetracer#250](https://github.com/metacraft-labs/codetracer/pull/250) | landed | [#252](https://github.com/metacraft-labs/codetracer/pull/252) | before | A user-guide refactor took this guide's text and added the reviewer's macOS setup steps. |
| [camunda/camunda#34153](https://github.com/camunda/camunda/pull/34153) | landed | [#34158](https://github.com/camunda/camunda/pull/34158) | before | A maintainer's pull request made the same change: retry Elasticsearch indefinitely instead of 12 times. |
| [toshimaru/nyan#189](https://github.com/toshimaru/nyan/pull/189) | landed | [#191](https://github.com/toshimaru/nyan/pull/191) | before | The same goreleaser-action v6 and config v2 upgrade, with `homebrew_casks` where this pull request used `brews`. |
| [spring-projects/spring-kafka#3944](https://github.com/spring-projects/spring-kafka/pull/3944) | landed | [85b3aee](https://github.com/spring-projects/spring-kafka/commit/85b3aee62bf40cac75790835fe05af10b751afb5) | as it closed | Merged by hand: a maintainer committed the change with documentation and wrote "Merged via" that commit in the thread. |
| [esphome/esphome-devices#1170](https://github.com/esphome/esphome-devices/pull/1170) | landed | [#1171](https://github.com/esphome/esphome-devices/pull/1171) | 1 hour | The same migration off the deprecated platform syntax, merged half an hour later. |
| [cybersemics/em#3001](https://github.com/cybersemics/em/pull/3001) | landed | [4ee2d01](https://github.com/cybersemics/em/commit/4ee2d0135e6519d9cba9e377dd6fd3cbc0f61e20) | 1 hour | A maintainer's commit makes the same middleware scroll the cursor into view after a sort. |
| [vitejs/vite-plugin-react#631](https://github.com/vitejs/vite-plugin-react/pull/631) | landed | [#632](https://github.com/vitejs/vite-plugin-react/pull/632) | 1 hour | "Supersedes #631": the same entry-file rewrite, with a react-router upgrade. |
| [cybersemics/em#3003](https://github.com/cybersemics/em/pull/3003) | landed | [0b9ca3d](https://github.com/cybersemics/em/commit/0b9ca3d4dc3851d369ca94735f75c5fbfd9e0456) | 3 hours | A maintainer committed the same `corepack enable` setup step. |
| [navidrome/navidrome#4100](https://github.com/navidrome/navidrome/pull/4100) | landed | [#4116](https://github.com/navidrome/navidrome/pull/4116) | 6 hours | The same bug, float custom tags compared as strings, fixed with a numeric flag instead of a type registry. |
| [demergent-labs/azle#3071](https://github.com/demergent-labs/azle/pull/3071) | landed | [#3075](https://github.com/demergent-labs/azle/pull/3075) | 6 hours | A maintainer wrote the same error-type tests, which closed the issue. |
| [invoke-ai/InvokeAI#8177](https://github.com/invoke-ai/InvokeAI/pull/8177) | landed | [#8240](https://github.com/invoke-ai/InvokeAI/pull/8240) | 1 day | The reference-image model autoswitch was redone and shipped in the v6.0.0 release pull request. |
| [mendableai/firecrawl#1886](https://github.com/mendableai/firecrawl/pull/1886) | landed | [#1895](https://github.com/mendableai/firecrawl/pull/1895) | 1 day | Closed only because it targeted the wrong branch; recreated on main with the same change. |
| [formancehq/ledger#918](https://github.com/formancehq/ledger/pull/918) | landed | [#921](https://github.com/formancehq/ledger/pull/921) | 1 day | A maintainer's pull request returns 400 for the same case through a shared error handler; #919 and #920 did the same on release branches. |
| [near/nearcore#13283](https://github.com/near/nearcore/pull/13283) | landed | [#13318](https://github.com/near/nearcore/pull/13318) | 1 day | The same feature deprecation, redone on a fresh base; #13305 handled the genesis case separately. |
| [microsoft/testfx#5606](https://github.com/microsoft/testfx/pull/5606) | landed | [#5589](https://github.com/microsoft/testfx/pull/5589) | 1 day | The reviewer's pull request added the same targets files for the same frameworks, from a different source file. |
| [nextcloud/desktop#8428](https://github.com/nextcloud/desktop/pull/8428) | landed | [#8466](https://github.com/nextcloud/desktop/pull/8466) | 2 days | A maintainer's replacement pull request carries the same commit plus review fixes. |
| [dotnet/efcore#36176](https://github.com/dotnet/efcore/pull/36176) | landed | [#36184](https://github.com/dotnet/efcore/pull/36184) | 2 days | A maintainer's pull request made the same handle-disposal fix and added the same test. |
| [microsoft/react-native-windows#14794](https://github.com/microsoft/react-native-windows/pull/14794) | landed | [#14800](https://github.com/microsoft/react-native-windows/pull/14800) | 12 days | The reviewer shipped snapToOffsets for the Fabric ScrollView, by a different mechanism (inertia resting-value modifiers). |
| [dotnet/aspnetcore#62085](https://github.com/dotnet/aspnetcore/pull/62085) | landed | [#62286](https://github.com/dotnet/aspnetcore/pull/62286) | 13 days | InternalsVisibleTo removed and circuit tracing moved into the Server assembly, by a different design from the one reviewed. |
| [microsoft/autogen#6565](https://github.com/microsoft/autogen/pull/6565) | landed | [#6623](https://github.com/microsoft/autogen/pull/6623) | 14 days | Callable edge conditions added with the same design, keeping string conditions. |
| [dotnet/maui#30169](https://github.com/dotnet/maui/pull/30169) | landed | [#30176](https://github.com/dotnet/maui/pull/30176) | 15 days | "Better than #30169": the same bounce-disable code and the same device test. |
| [primer/react#6299](https://github.com/primer/react/pull/6299) | landed | [#6354](https://github.com/primer/react/pull/6354) | 16 days | All five test files moved to Vitest across #6310, #6335 and #6354. |
| [modelcontextprotocol/inspector#126](https://github.com/modelcontextprotocol/inspector/pull/126) | landed | [#136](https://github.com/modelcontextprotocol/inspector/pull/136) | 25 days | The same lockfile bump to express 4.21.2 and path-to-regexp 0.1.12, inside a feature pull request. |
| [microsoft/react-native-windows#14795](https://github.com/microsoft/react-native-windows/pull/14795) | landed | [#14847](https://github.com/microsoft/react-native-windows/pull/14847) | 27 days | snapToInterval with inertia modifiers; reverted for a regression and landed again in #15341. |
| [primer/react#6069](https://github.com/primer/react/pull/6069) | landed | [#6348](https://github.com/primer/react/pull/6348) | 65 days | A maintainer migrated the same CounterLabel tests to Vitest, keeping two details this pull request had changed. |
| [microsoft/windows-rs#3648](https://github.com/microsoft/windows-rs/pull/3648) | landed | [#3826](https://github.com/microsoft/windows-rs/pull/3826) | 153 days | The same least-privilege `permissions` block in the same workflows, approved by the maintainer who had closed this one as unnecessary. |
| [Cap-go/capgo#1012](https://github.com/Cap-go/capgo/pull/1012) | partly | [#1037](https://github.com/Cap-go/capgo.app/pull/1037) | 7 hours | The underlying bug was fixed with a different migration, a foreign key without cascade; this pull request's trigger and checks never landed. |
| [celestiaorg/celestia-core#2042](https://github.com/celestiaorg/celestia-core/pull/2042) | partly | [#2040](https://github.com/celestiaorg/celestia-core/pull/2040) | 4 days | The golangci-lint v2 upgrade landed on a release branch; running lint on every pull request did not. |
| [maximhq/bifrost#60](https://github.com/maximhq/bifrost/pull/60) | partly | [a39da9f](https://github.com/maximhq/bifrost/commit/a39da9fafd) | 5 days | OpenAI, Anthropic and LiteLLM integrations landed by a different design; the Mistral and LangGraph routes did not. |
| [vltpkg/vltpkg#877](https://github.com/vltpkg/vltpkg/pull/877) | partly | [#990](https://github.com/vltpkg/vltpkg/pull/990) | 12 days | `vlt query` and `vlt ls` now always load the security data; the interface changes did not land. |
| [hyperlight-dev/hyperlight#641](https://github.com/hyperlight-dev/hyperlight/pull/641) | partly | [#741](https://github.com/hyperlight-dev/hyperlight/pull/741) | 16 days | Release-only benchmark builds landed through the Justfile and workflows; the compile-time gate was dropped at the maintainers' request. |
| [microsoft/fabric-cicd#363](https://github.com/microsoft/fabric-cicd/pull/363) | partly | [#550](https://github.com/microsoft/fabric-cicd/pull/550) | 51 days | `publish_all_items` returns the API responses, behind a feature flag; this pull request's status fields did not land. |
| [reflex-dev/reflex-web#1446](https://github.com/reflex-dev/reflex-web/pull/1446) | partly | [#1656](https://github.com/reflex-dev/reflex-web/pull/1656) | 105 days | A pre-commit configuration and CI workflow landed with ruff hooks only; none of this pull request's hooks did. |

The 25 that did not land:

| Pull request | Note |
|---|---|
| [airbytehq/airbyte#52578](https://github.com/airbytehq/airbyte/pull/52578) | The root-page reorganisation did not land. Some of its poisoned claims repeat a contribution policy that was already documented. |
| [airbytehq/airbyte#52634](https://github.com/airbytehq/airbyte/pull/52634) | Closed for inactivity; none of the proposed sections appeared later. |
| [bespokelabsai/curator#305](https://github.com/bespokelabsai/curator/pull/305) | The bug was fixed differently (#360), without cloudpickle. |
| [calcom/cal.com#20760](https://github.com/calcom/cal.com/pull/20760) | No change to seat billing in the six months after. |
| [cloudwalk/stratus#1961](https://github.com/cloudwalk/stratus/pull/1961) | No unit tests for the type were added. |
| [doodlum/skyrim-community-shaders#1281](https://github.com/doodlum/skyrim-community-shaders/pull/1281) | The caching did not land. The repository has moved to community-shaders/skyrim-community-shaders. |
| [dotnet/docs#47074](https://github.com/dotnet/docs/pull/47074) | Not done, and the issue is open. Its poisoned claims about `readonly` restate the maintainer's own issue text, which is how the docs read today. |
| [dotnet/maui#30218](https://github.com/dotnet/maui/pull/30218) | The legacy layout APIs are still warning-level, and the issue is open. |
| [dotnet/maui#30358](https://github.com/dotnet/maui/pull/30358) | Neither the helper API nor the build-retry change exists. |
| [dotnet/performance#4892](https://github.com/dotnet/performance/pull/4892) | The same lookup landed about 13 months later (#5290), outside the window. |
| [microsoft/react-native-windows#14915](https://github.com/microsoft/react-native-windows/pull/14915) | CI was fixed by removing a dependency instead (#14919). |
| [microsoft/retina#1617](https://github.com/microsoft/retina/pull/1617) | Closed as stale; the shell is still Linux-only. |
| [microsoft/TypeScript#61946](https://github.com/microsoft/TypeScript/pull/61946) | Neither this fix nor the alternative the maintainers preferred was merged. |
| [microsoft/typescript-go#1109](https://github.com/microsoft/typescript-go/pull/1109) | The issue was closed as not planned. |
| [microsoft/vscode-jupyter#16762](https://github.com/microsoft/vscode-jupyter/pull/16762) | The kernel restart is still unconditional. Its matching lines came from instruction files that were merged separately. |
| [mongodb/specifications#1800](https://github.com/mongodb/specifications/pull/1800) | The added tests duplicated existing ones. |
| [navidrome/navidrome#4101](https://github.com/navidrome/navidrome/pull/4101) | No log viewer exists. |
| [owid/etl#4651](https://github.com/owid/etl/pull/4651) | The maintainers declined it. Claims that keep the existing year match the data, since nothing changed. |
| [parse-community/parse-dashboard#2873](https://github.com/parse-community/parse-dashboard/pull/2873) | No new dashboard landed. |
| [parse-community/parse-dashboard#2884](https://github.com/parse-community/parse-dashboard/pull/2884) | A different graph feature (#3110) landed about 173 days later. It is counted as not landed; it is the closest call in the set. |
| [reeze/php-leveldb#54](https://github.com/reeze/php-leveldb/pull/54) | None of the seven fixes appears. |
| [sam-goodwin/alchemy#283](https://github.com/sam-goodwin/alchemy/pull/283) | No Polar provider exists. |
| [vercel/turborepo#10623](https://github.com/vercel/turborepo/pull/10623) | Chunked hashing arrived nine months later inside an unrelated fix. |
| [wolfSSL/wolfssh#778](https://github.com/wolfSSL/wolfssh/pull/778) | A different compiler-matrix workflow arrived after the window. |
| [wolfSSL/wolfssl#8457](https://github.com/wolfSSL/wolfssl/pull/8457) | No such random number generator exists. |

## The published numbers under the re-check

Three ways to account for the landings, all on the arms in the README:

- **Landed excluded.** The 28 pull requests that landed in full leave the sample.
- **Landed or partly excluded.** The 35 that landed in any form leave the sample.
- **Relabelled.** In those 35, poisoned claims the reviewers judged true of the code once the change landed count as safe. Everything else keeps its label.

Each cell gives the declined pull requests with at least one claim stating the rejected approach as current, then the mean share of a pull request's claims that do.

| Condition | As published | Landed excluded | Landed or partly excluded | Relabelled |
|---|---|---|---|---|
| crewlore extractor, outcome not stated | 47 of 60, 44.7% | 25 of 32, 44.7% | 19 of 25, 43.0% | 33 of 60, 26.6% |
| Schema-free summarizer | 45 of 60, 47.6% | 25 of 32, 45.7% | 19 of 25, 43.0% | 36 of 60, 29.1% |
| Outcome stated in the thread | 35 of 60, 30.1% | 17 of 32, 25.7% | 13 of 25, 25.2% | 26 of 60, 16.9% |
| Adoption field plus instruction | 25 of 60, 17.5% | 9 of 32, 13.3% | 6 of 25, 12.0% | 11 of 60, 8.1% |

The paired comparisons, as a difference in mean share in percentage points, with a 95% interval and p:

| Comparison | As published | Landed excluded | Landed or partly excluded | Relabelled |
|---|---|---|---|---|
| Not stated − stated | +14.6 [+7.6, +22.1], 0.0002 | +19.0 [+10.3, +28.2], 0.0002 | +17.8 [+8.8, +27.1], 0.0013 | +9.7 [+4.6, +15.3], 0.0007 |
| Stated − field plus instruction | +12.7 [+4.6, +20.8], 0.0038 | +12.4 [+4.3, +20.7], 0.0082 | +13.3 [+3.2, +23.8], 0.0230 | +8.8 [+3.3, +14.7], 0.0042 |
| Not stated − field plus instruction | +27.2 [+19.3, +35.6], <0.0001 | +31.5 [+20.3, +42.8], <0.0001 | +31.0 [+18.0, +44.6], 0.0002 | +18.5 [+11.1, +26.3], <0.0001 |
| Extractor − summarizer | −2.9 [−9.7, +4.4], 0.43 | −1.0 [−10.2, +9.7], 0.85 | 0.0 [−11.0, +13.2], 0.99 | −2.5 [−7.8, +3.6], 0.42 |

The merged controls are unchanged.

## What holds and what does not

- **Pull requests whose change did not land poison at the published rate.** Among those whose change did not land within about six months, 25 of 32 (78%) still put at least one claim stating the rejected approach as current into the store, and 19 of 25 (76%) when partial landings are excluded too. The published figure is 47 of 60 (78%).
- **The headline counts are inflated.** The 47 of 60 behind the headline include 28 pull requests whose change landed in some form, 22 in full and 6 in part. Counting the claims the reviewers judged true of the code as safe brings the extractor to 33 of 60 (55%) and 26.6%, and the field arm to 11 of 60 (18%) and 8.1%.
- **The published differences hold.** Stating the outcome, adding the field plus instruction, and both together keep their direction and stay significant in all three accountings. The summarizer still matches the extractor.
- **The claims that came true were mostly about behaviour.** In the 35 pull requests that landed in any form, the published arms hold 206 poisoned claims: 134 were judged true of the code once the change landed, 54 still wrong, and 18 unclear. Claims about what the code should do were mostly true. Claims that described the declined pull request's own implementation were mostly still wrong, and they stay counted.

## Other label problems found along the way

These were noted but not counted:

- **Claims that were true before the pull request.** Some restate an existing documented policy (airbyte #52578) or the maintainer's own issue text (dotnet/docs #47074). Others come from commits already on main that a declined branch carried after a bad rebase (InvokeAI #8177). Others match data that never changed (owid/etl #4651).
- **Judge reasons that contradict the thread.** In nearcore #13283 the reviewer had asked for the removal the judge called unendorsed. In esphome-devices #1170 the board default comes from the maintainer's own issue.
- **A wrong "rejected" label in the corpus.** spring-kafka #3944 was merged by hand.

## Limits

- The verdicts are model reviewers' judgments. Eight landings were checked by hand, and none of the claim-level judgments were checked by a person.
- The window is about six months. One change landed after it (dotnet/performance #4892, about 13 months later), and one call is close (parse-dashboard #2884).
- The automated leads missed 11 of the 35 landings, so a not-landed verdict rests on the reviewers' search. A reimplementation that left no trail in issues, titles or the files' history would be missed.
- formance ledger's default branch has been rewritten, so its current history no longer contains the landed change. The release branches still do.

## What this record changes

Nothing it describes has been changed. Any change to the README's results, the write-up, the essay or the launch copy is a separate decision for the author.

## Files

- `label_recheck/collect.py`: the read-only GitHub leads.
- `label_recheck/BRIEF.md`: the reviewers' rubric.
- `label_recheck/verdicts.json`: per pull request, the verdict, the change that landed, the hours from closing to landing, the links, and how many poisoned claims from the published arms were judged true now, still wrong or unclear.
- `label_recheck/recompute.py`: the tables above, computed with `analyze.py`'s own functions. Run it from a checkout that holds the pinned snapshot and the results in `local/aidev/`, where the claim-level verdicts also live.
