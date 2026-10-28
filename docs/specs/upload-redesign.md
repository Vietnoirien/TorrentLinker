# Upload workspace, desktop and WebUI

The selected design is Workspace: a searchable list of Local Drafts beside the editor. Desktop and WebUI use the same navigation, section order, action labels and save/review/send sequence.

## Decisions

- Upload opens on Local drafts. The other top-level view is c411 drafts.
- New draft selects a Library item for preparation. Manual preparation saves a Local Draft; there is no direct-to-c411 button.
- The saved editor has Details, Files & NFO, Description, Artwork and Review sections. Details includes editable category, subcategory, source and category options.
- Incomplete drafts can be saved. Review reads the saved revision. Editing clears the review acknowledgement and disables sending until the changes are saved and reviewed again.
- Send to c411 is available in Review only, and still confirms the exact saved revision. Refusals, missing fields, changed files and uncertain sends remain subject to the shared service's checks.
- Draft actions group preview, local removal and explicitly confirmed retry. Removing a local record leaves files and remote drafts intact.
- Existing model tools, image hosting, archive extraction, category checks and seeding workflows remain available. Desktop model tools open the preparation editor for the same saved record; saving updates that record rather than creating a duplicate.
- Use the established button roles and theme colors. Desktop remembers sidebar widths. Web stacks the sidebar above the editor at narrow widths.
- Final publication remains manual on c411. Desktop retains its existing verification/seeding workflow; WebUI offers seeding separately after a successful send.

## Validation

Test the existing Qt widget and authenticated WebUI boundaries with temporary files, fake clients and a mock tracker. Verify default navigation, saving incomplete drafts without sending, preservation of unsaved edits during queue refresh, revocation of review after edits, saved-revision sending and both languages/themes. Capture actual Qt and browser screens with example data.
