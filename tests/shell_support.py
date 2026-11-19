"""Operate the shared shell through its visible desktop or narrow controls."""


def shell_navigate(page, view):
    page.locator("#workspace").wait_for(state="visible")
    sidebar = page.locator("#app-sidebar")
    if not sidebar.is_visible():
        page.locator("#navigation-toggle").click()
    frame = page.frame_locator("#shell-navigation-frame")
    frame.locator("#page-select option").first.wait_for(state="attached")
    selector = frame.locator("#page-select")
    if selector.is_visible():
        selector.select_option(view)
    else:
        frame.locator(f'[data-view="{view}"]').click()
    page.locator(f"#view-{'search' if view == 'queue' else view}").wait_for(state="visible")


def shell_close_navigation(page):
    if page.locator("#app-sidebar").is_visible():
        page.locator("#navigation-toggle").click()
