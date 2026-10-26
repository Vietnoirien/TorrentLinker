# Beta release and stabilization decision

Agreed with the user on 2026-10-26.

The accepted longer-term criteria are recorded in the
[1.0.0 readiness decision](1.0.0-readiness-decision.md).

TorrentLinker as a whole will be presented as a public beta. The intended next
release label is `0.13.0-beta.1`, subject to the final publication checks. This
decision does not itself authorize publishing or changing the version.

## Sequence

1. Finish the currently authorized implementation and resolve review findings.
2. Run final automated and real-workflow tests before publication. Record failures,
   fixes and known limitations; do not describe untested behavior as verified.
3. Publish only when the user requests publication and the final checks are ready.
4. After publication, plan the stabilization work with the user.

The beta designation applies to the whole application. The assistant can remain
explicitly experimental. Core workflows should remain usable without it.

## Topics for the later stabilization plan

- Reliable progress, cancellation, retry behavior and restart recovery.
- Desktop, web and MCP capability and validation consistency.
- Accurate previews of uploads, queued downloads and proposed changes.
- Actionable errors and redacted diagnostic exports.
- Upgrade and migration checks for settings, drafts, queues and conversations.
- Windows, Linux, Docker, remote Torrent Clients, permissions and model-provider
  coverage.

These are planning topics, not a new implementation assignment. Finish the current
scope before starting another feature expansion. Reserve release-candidate labels
for a version believed ready, with only final release blockers under evaluation.

## Recommendations recorded for release preparation

These recommendations guide the final checks and later planning; they do not
authorize additional implementation or publication.

- Freeze feature scope after the currently authorized work. Resolve defects before
  adding another round of capabilities.
- Run the combined automated suite against the final integrated changes, including
  typechecking, lint and relevant frontend checks. Keep the results tied to the
  tested revision.
- Exercise core workflows with real files across films, music, ebooks and 3D models.
  Test the configured local model, and record what its endpoint actually supports.
  Do not treat a successful setup probe as a guarantee of later model behavior.
- Check RSS restart recovery, concurrent refreshes, duplicate prevention, waiting
  for alternatives and replacement of pending entries. Started downloads must not
  be silently replaced.
- Verify that app-queue mode neither starts downloads nor sends torrents to a
  Torrent Client. A saved queue can exceed disk capacity or a daily allowance;
  actual downloads must honor the chosen client, folder, schedule and download
  constraints.
- Compare desktop and web workflows for subscription setup, preferences, previews,
  errors and recovery. Check that MCP uses the same validation and permissions.
- Test upgrades from `0.12.2`, including preservation of settings, conversations,
  Local Drafts and queues. Test backup/recovery procedures before recommending them.
- Default new feeds to review-only. Automatic queueing and downloading require an
  explicit mode choice. Show why a release matched, why alternatives were rejected
  and which required facts remain unknown.
- Publish known limitations alongside the beta. Recheck current evidence for c411
  feed coverage, large-mesh rendering limits and provider vision support before
  describing those limitations in release notes.
- Invite feedback from real installations during the beta, then prioritize
  recurring failures and data-loss or unintended-action risks in stabilization.

For stabilization, prioritize reliable operations and recovery first, then parity,
preview accuracy, diagnostics and upgrade confidence. Define the platform and
provider test matrix with the user after publication. A release candidate should
represent a specific version believed ready, with only final blockers being checked.

## Versioning

Update accepted on 2026-10-26: the next release is `1.0.0-beta.1`, establishing
the baseline for polish and stabilization after the Media Center addition. The
earlier `0.13.0` target below records the initial beta decision and is superseded
by this target. The [1.0 readiness criteria](1.0.0-readiness-decision.md) remain
required for the eventual stable release.

The user explicitly confirmed that TorrentLinker will continue to follow Semantic
Versioning. Beta is a release maturity label, not a replacement for SemVer.

- Use `MAJOR.MINOR.PATCH`, with optional prerelease identifiers. The intended next
  public beta is `0.13.0-beta.1`.
- Increment the numeric beta suffix for successive prereleases of that same target,
  for example `0.13.0-beta.2`. If a release-candidate phase is useful, use
  `0.13.0-rc.1`, followed by `0.13.0` when ready. Do not reset the base version while
  progressing through these stages.
- Choose the target version from the change's compatibility and scope. Backward
  compatible fixes normally take a patch increment; backward compatible features
  take a minor increment. After `1.0.0`, incompatible public API changes require a
  major increment.
- During `0.x`, SemVer identifies the public API as unstable. Our proposed project
  convention is to keep patch releases backward compatible and put intentional
  incompatible changes in a new minor release, with explicit migration notes.
  This convention is stricter than SemVer's guarantees for initial development.
- Define the supported public compatibility contracts during stabilization,
  including documented MCP/HTTP interfaces and configuration formats. Track stored
  data migrations and desktop/web behavior changes explicitly as well.
- Do not call `0.13.0` a promise that the whole application has reached `1.0`
  stability. Decide readiness for `1.0.0` separately, based on supported contracts,
  operational reliability and upgrade evidence.
- Keep published releases immutable. Corrections require a new version. Confirm
  that tags, application metadata, packages and update checks consistently handle
  prerelease versions before publishing the beta; stable installations should not
  be moved onto beta updates unintentionally.

The `0.x` compatibility convention and prerelease update-channel behavior above are
recommendations to confirm during release preparation, not claims about behavior
already implemented.
