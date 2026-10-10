"""Web Images Extractor for Lumen: browse the web in a tab and pull any image into your project."""


def register(api):
    from .browser import WebImagesWorkspace
    ws = WebImagesWorkspace(api)
    api.add_workspace("Web Images Extractor", ws, icon="globe")
    api.add_menu_action("Plugins", "Web Images Extractor", lambda: api.show_workspace(ws), needs_document=False)
    register.workspace = ws
