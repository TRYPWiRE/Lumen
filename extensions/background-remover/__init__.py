"""Background Remover for Lumen: its own tab, plus Layer ▸ Remove Background and Select ▸ Subject."""
from PyQt6.QtWidgets import QProgressDialog, QMessageBox
from PyQt6.QtCore import Qt


def register(api):
    from .workspace import BackgroundRemoverWorkspace
    from . import ai

    ws = BackgroundRemoverWorkspace(api)
    api.add_workspace("Background Remover", ws, icon="cutout")
    register.workspace = ws

    def open_tab():
        api.show_workspace(ws)

    def edit_layer():
        if ws.from_active_layer():
            api.show_workspace(ws)

    def run_ai(img, done, label):
        """Download the model if needed, then run U²-Net on img in the background."""
        from lumen import net
        name = list(ai.MODELS.values())[int(api.setting("model", 0) or 0)]
        folder = api.data_dir("models")
        prog = QProgressDialog(label, "Cancel", 0, 0, api.window())
        prog.setWindowTitle("Lumen")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(200)

        def job(progress=None, cancelled=None):
            return ai.subject_alpha(img, ai.download_model(folder, name, progress, cancelled))
        task = net.Task(job, with_progress=True)
        prog.canceled.connect(task.cancel)
        task.progress.connect(lambda d, t: (prog.setRange(0, 100), prog.setValue(int(d * 100 / t))) if t else None)

        def ok(mask):
            prog.close()
            done(mask)

        def fail(msg):
            prog.close()
            if msg != "Cancelled":
                QMessageBox.warning(api.window(), "Lumen", f"Couldn't find the subject.\n\n{msg}")
        task.succeeded.connect(ok)
        task.failed.connect(fail)
        task.start()
        register.last_task = task
        return task

    def remove_background():
        """Photoshop's Remove Background: cut the subject out of the active layer (undoable)."""
        doc = api.current_document()
        if doc is None:
            return
        L = doc.try_target("remove the background")
        if L is None:
            return
        r = doc.rect() if L.background else L.rect().intersected(doc.rect())
        if r.isEmpty():
            return
        img = L.region(r)

        def done(mask):
            import numpy as np
            from lumen.layers import Layer
            if L not in doc.layers:
                return
            arr = api.imageops.straight_array(img)
            arr[..., 3] = np.minimum(arr[..., 3], mask)
            out = api.imageops.from_array(arr, api.imageops.STRAIGHT).convertToFormat(api.imageops.PREMUL)
            doc.undo.beginMacro("Remove Background")
            if L.background:
                doc.background_to_layer(L)
            doc.apply_patch("Remove Background", r, out, layer=L)
            doc.undo.endMacro()
        return run_ai(img, done, "Removing the background…")

    def select_subject():
        """Photoshop's Select ▸ Subject: AI selection of the main subject of the whole image."""
        doc = api.current_document()
        if doc is None:
            return
        img = doc.flattened()

        def done(mask):
            doc.selection_from_mask(mask >= 128, "Select Subject")
        return run_ai(img, done, "Finding the subject…")

    register.remove_background = remove_background
    register.select_subject = select_subject
    api.add_menu_action("Plugins", "Background Remover", open_tab, needs_document=False)
    api.add_menu_action("Layer", "Remove Background", remove_background)
    api.add_menu_action("Layer", "Edit in Background Remover…", edit_layer)
    api.add_menu_action("Select", "Subject", select_subject)
