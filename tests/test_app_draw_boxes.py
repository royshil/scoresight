"""Drawing a field's box on the picture, the field list's double-click, the
box's menu on the picture, Del, the Fields footer's hints and Drag to crop.

The viewer is the real ImageViewer (source_view.py) without a capture thread:
the frames are handed to it as the thread would."""

import sys

import numpy as np
import pytest

pytestmark = pytest.mark.qt
pytest.importorskip("tesserocr")  # MainWindow imports the OCR pipeline

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSizeF, Qt  # noqa: E402
from PySide6.QtGui import QContextMenuEvent, QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import camera_thread  # noqa: E402
from camera_info import CameraInfo  # noqa: E402
from storage import fetch_data, store_data  # noqa: E402
import test_app_mainwindow_smoke as smoke  # noqa: E402

# the keys as a Mac writes them (⌥ Option, ⌦)
MAC = sys.platform == "darwin"

# the main window's fixtures (with its FakeViewer: the tests open a real viewer
# themselves)
patched = smoke.patched
make_window = smoke.make_window
main_window = smoke.main_window
windows_do_not_outlive_their_test = smoke.windows_do_not_outlive_their_test
box_name_item = smoke.box_name_item

LEFT = Qt.MouseButton.LeftButton
NO_BUTTON = Qt.MouseButton.NoButton
NO_MODIFIER = Qt.KeyboardModifier.NoModifier
ALT = Qt.KeyboardModifier.AltModifier


def file_source():
    return CameraInfo("stub", "stub", "stub", CameraInfo.CameraType.FILE)


def show_frame(viewer, width=1280, height=720, value=60):
    """Hand the viewer a frame, as its capture thread does (frame_size is the
    source's frame, before the rotation)."""
    frame = np.full((height, width, 3), value, np.uint8)
    viewer.update_pixmap(frame)


def mouse(viewer, kind, position, button=LEFT, buttons=None, modifiers=NO_MODIFIER):
    viewport = viewer.viewport()
    local = QPointF(position)
    if buttons is None:
        buttons = NO_BUTTON if kind == QEvent.Type.MouseButtonRelease else button
    event = QMouseEvent(
        kind, local, QPointF(viewport.mapToGlobal(local)), button, buttons, modifiers
    )
    QApplication.sendEvent(viewport, event)
    return event


def drag(viewer, start, end, modifiers=NO_MODIFIER, button=LEFT, release=True):
    """Press at start, move to end in a few steps (viewport pixels), release."""
    start, end = QPoint(*start), QPoint(*end)
    mouse(viewer, QEvent.Type.MouseButtonPress, start, button, modifiers=modifiers)
    for step in range(1, 5):
        point = start + (end - start) * (step / 4)
        mouse(viewer, QEvent.Type.MouseMove, point, NO_BUTTON, button, modifiers)
    if release:
        mouse(viewer, QEvent.Type.MouseButtonRelease, end, button, modifiers=modifiers)


def double_click(viewer, position):
    position = QPoint(*position)
    mouse(viewer, QEvent.Type.MouseButtonPress, position)
    mouse(viewer, QEvent.Type.MouseButtonRelease, position)
    mouse(viewer, QEvent.Type.MouseButtonDblClick, position)
    mouse(viewer, QEvent.Type.MouseButtonRelease, position)


def key(widget, key_code, modifiers=NO_MODIFIER):
    event = QKeyEvent(QEvent.Type.KeyPress, key_code, modifiers)
    QApplication.sendEvent(widget, event)
    return event


def expected_rect(viewer, start, end):
    """The rectangle a drag from start to end draws: the viewport points on
    the picture, within it, on whole pixels."""
    from source_view import drawn_rect

    return drawn_rect(
        viewer.mapToScene(QPoint(*start)),
        viewer.mapToScene(QPoint(*end)),
        viewer.pictureRect(),
    )


def on_screen(viewer, rect: QRectF) -> QRect:
    return viewer.mapFromScene(rect).boundingRect()


def assert_near(actual: QRect, expected: QRect, tolerance: int):
    for a, b in (
        (actual.left(), expected.left()),
        (actual.top(), expected.top()),
        (actual.right(), expected.right()),
        (actual.bottom(), expected.bottom()),
    ):
        assert abs(a - b) <= tolerance, (actual, expected)


# --- the viewer on its own ----------------------------------------------------------


@pytest.fixture
def viewer(qtbot, memory_storage):
    """A shown ImageViewer with a 1280x720 picture; .selected records the
    fields it selects (None: deselected)."""
    from source_view import ImageViewer

    selected = []
    view = ImageViewer(
        file_source(),
        lambda corners: None,
        memory_storage,
        selected.append,
        start=False,
    )
    view.selected = selected
    view.resize(800, 450)
    with qtbot.waitExposed(view):
        view.show()
    view.timerThread.frame_size = (1280, 720)
    show_frame(view)
    yield view
    view.close()
    view.deleteLater()


def signals(view):
    """The viewer's drawing signals, recorded."""
    recorded = {"drawn": [], "place": [], "menu": [], "crop": []}
    view.box_drawn.connect(lambda name, rect: recorded["drawn"].append((name, rect)))
    view.place_requested.connect(
        lambda name, point: recorded["place"].append((name, point))
    )
    view.box_menu_requested.connect(
        lambda name, point: recorded["menu"].append((name, point))
    )
    view.crop_drawn.connect(lambda rect, size: recorded["crop"].append((rect, size)))
    return recorded


def test_a_drag_draws_the_box_of_a_field_without_one(viewer):
    recorded = signals(viewer)
    assert viewer.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
    viewer.setPlacementField("Home Fouls")
    # a crosshair, and a hint over the picture
    assert viewer.viewport().cursor().shape() == Qt.CursorShape.CrossCursor
    assert viewer.placementHint.isVisible()
    assert viewer.placementHint.text() == "Drag over the numbers to place Home Fouls"
    hint = viewer.placementHint.geometry()
    assert hint.top() < 20 and abs(hint.center().x() - viewer.width() / 2) < 20

    drag(viewer, (100, 120), (300, 200))
    [(name, rect)] = recorded["drawn"]
    assert name == "Home Fouls"
    assert rect == expected_rect(viewer, (100, 120), (300, 200))
    # in picture pixels (the picture is shown smaller)
    assert rect.width() == pytest.approx(200 / viewer.zoomLevel(), abs=2)
    assert viewer.zoomLevel() < 1
    assert viewer.drawing is None
    assert viewer.scene.items() and not any(
        type(item).__name__ == "RubberBand" for item in viewer.scene.items()
    )


def test_the_drawn_box_is_right_when_zoomed_in_and_panned(viewer, qapp):
    recorded = signals(viewer)
    viewer.setPlacementField("Time")
    viewer.zoomIn()
    viewer.zoomIn()
    qapp.processEvents()
    viewer.horizontalScrollBar().setValue(viewer.horizontalScrollBar().value() + 130)
    viewer.verticalScrollBar().setValue(viewer.verticalScrollBar().value() + 40)
    drag(viewer, (420, 90), (250, 260))  # up and to the left: the same box
    [(name, rect)] = recorded["drawn"]
    assert rect == expected_rect(viewer, (250, 90), (420, 260))
    # it covers what was dragged over, on screen
    assert_near(
        on_screen(viewer, rect),
        QRect(QPoint(250, 90), QPoint(420, 260)),
        round(viewer.zoomLevel()) + 1,
    )


def test_a_drag_while_dragging_shows_a_rubber_band(viewer):
    from source_view import RubberBand

    viewer.setPlacementField("Time")
    drag(viewer, (100, 100), (260, 180), release=False)
    [band] = [item for item in viewer.scene.items() if isinstance(item, RubberBand)]
    assert band.isVisible()
    assert band.rect() == expected_rect(viewer, (100, 100), (260, 180))
    mouse(viewer, QEvent.Type.MouseButtonRelease, QPoint(260, 180))
    assert band.scene() is None


def test_a_tiny_drag_is_a_click(viewer):
    recorded = signals(viewer)
    viewer.setPlacementField("Home Fouls")
    drag(viewer, (100, 100), (102, 101))
    # a box at least DRAW_MIN_PX wide and tall only
    drag(viewer, (100, 100), (300, 102))
    assert recorded["drawn"] == []
    # and the field stays selected, to be placed
    assert viewer.selected == []
    assert viewer.placementField == "Home Fouls"
    # (the rubber band shows only when the release would draw it)
    from source_view import RubberBand

    drag(viewer, (100, 100), (300, 102), release=False)
    [band] = [item for item in viewer.scene.items() if isinstance(item, RubberBand)]
    assert not band.isVisible()
    mouse(viewer, QEvent.Type.MouseButtonRelease, QPoint(300, 102))


def test_a_drag_right_after_a_click_draws(viewer):
    # Qt makes the second press of a quick pair a double-click
    recorded = signals(viewer)
    viewer.setPlacementField("Time")
    mouse(viewer, QEvent.Type.MouseButtonPress, QPoint(100, 100))
    mouse(viewer, QEvent.Type.MouseButtonRelease, QPoint(100, 100))
    mouse(viewer, QEvent.Type.MouseButtonDblClick, QPoint(102, 101))
    for x, y in ((150, 140), (240, 200)):
        mouse(viewer, QEvent.Type.MouseMove, QPoint(x, y), NO_BUTTON, LEFT)
    mouse(viewer, QEvent.Type.MouseButtonRelease, QPoint(240, 200))
    [(name, rect)] = recorded["drawn"]
    assert rect == expected_rect(viewer, (102, 101), (240, 200))
    assert recorded["place"] == []


def test_a_lost_release_ends_the_drawing(viewer):
    # e.g. a dialog opened during the drag: the release went to it
    recorded = signals(viewer)
    viewer.setPlacementField("Time")
    drag(viewer, (100, 100), (300, 200), release=False)
    # the next move without the button
    mouse(viewer, QEvent.Type.MouseMove, QPoint(320, 220), NO_BUTTON, NO_BUTTON)
    assert not viewer.isDrawing()
    # or the next press: a new drag from there
    drag(viewer, (100, 100), (300, 200), release=False)
    drag(viewer, (400, 300), (500, 380))
    [(name, rect)] = recorded["drawn"]
    assert rect == expected_rect(viewer, (400, 300), (500, 380))
    # a hidden viewer stops drawing
    drag(viewer, (100, 100), (300, 200), release=False)
    viewer.hide()
    assert not viewer.isDrawing()


def test_esc_cancels_the_drawing(viewer):
    recorded = signals(viewer)
    viewer.setPlacementField("Home Fouls")
    drag(viewer, (100, 100), (300, 200), release=False)
    assert viewer.isDrawing()
    assert key(viewer, Qt.Key.Key_Escape).isAccepted()
    assert not viewer.isDrawing()
    mouse(viewer, QEvent.Type.MouseButtonRelease, QPoint(300, 200))
    assert recorded["drawn"] == []
    # the field is still selected: a second Esc deselects it
    assert viewer.selected == []
    key(viewer, Qt.Key.Key_Escape)
    assert viewer.selected == [None]


def test_a_drag_selects_and_moves_boxes_as_before(viewer, memory_storage, make_target):
    # a field on the picture: a drag on the empty picture draws nothing (it
    # deselects, as before), and a press on a box selects it
    recorded = signals(viewer)
    memory_storage.add_item(make_target("Home Score", rect=(100, 100, 200, 120)))
    viewer.selectBox("Home Score")
    drag(viewer, (500, 300), (650, 400))
    assert recorded["drawn"] == []
    assert viewer.selected == [None]

    # a field without a box selected: a press on a box selects that box
    viewer.setPlacementField("Home Fouls")
    box_center = on_screen(viewer, QRectF(100, 100, 200, 120)).center()
    drag(
        viewer, (box_center.x(), box_center.y()), (box_center.x() + 40, box_center.y())
    )
    assert recorded["drawn"] == []
    assert viewer.selected[-1] == "Home Score"
    # (and moves it)
    assert memory_storage.find_item_by_name("Home Score").x() > 100


def test_alt_drag_draws_the_selected_box_again(viewer, memory_storage, make_target):
    recorded = signals(viewer)
    memory_storage.add_item(make_target("Home Score", rect=(100, 100, 200, 120)))
    viewer.selectBox("Home Score")
    # with Alt, the crosshair
    mouse(viewer, QEvent.Type.MouseMove, QPoint(600, 400), NO_BUTTON, NO_BUTTON, ALT)
    assert viewer.viewport().cursor().shape() == Qt.CursorShape.CrossCursor
    # also from a press on a box
    start = on_screen(viewer, QRectF(100, 100, 200, 120)).center()
    drag(viewer, (start.x(), start.y()), (500, 350), modifiers=ALT)
    [(name, rect)] = recorded["drawn"]
    assert name == "Home Score"
    assert rect == expected_rect(viewer, (start.x(), start.y()), (500, 350))
    # nothing selected: Alt+drag draws nothing
    viewer.selectBox(None)
    drag(viewer, (100, 100), (300, 300), modifiers=ALT)
    assert len(recorded["drawn"]) == 1


def test_a_double_click_on_the_picture_places_the_box_there(
    viewer, memory_storage, make_target
):
    recorded = signals(viewer)
    double_click(viewer, (400, 200))
    assert recorded["place"] == []  # no field to place
    viewer.setPlacementField("Period")
    double_click(viewer, (400, 200))
    [(name, point)] = recorded["place"]
    assert name == "Period"
    assert point == viewer.mapToScene(QPoint(400, 200))
    assert recorded["drawn"] == []
    # on a box: that box, as before
    memory_storage.add_item(make_target("Home Score", rect=(100, 100, 200, 120)))
    center = on_screen(viewer, QRectF(100, 100, 200, 120)).center()
    double_click(viewer, (center.x(), center.y()))
    assert len(recorded["place"]) == 1
    assert viewer.selected[-1] == "Home Score"


def test_middle_drag_pans_without_drawing(viewer, qapp):
    recorded = signals(viewer)
    viewer.setPlacementField("Time")
    viewer.zoomIn()
    viewer.zoomIn()
    qapp.processEvents()
    before = viewer.horizontalScrollBar().value()
    drag(viewer, (400, 200), (300, 200), button=Qt.MouseButton.MiddleButton)
    assert viewer.horizontalScrollBar().value() == before + 100
    assert recorded["drawn"] == []
    assert viewer.viewport().cursor().shape() == Qt.CursorShape.CrossCursor


def test_four_corner_picking_wins_over_drawing(viewer):
    recorded = signals(viewer)
    viewer.setPlacementField("Time")
    viewer.startFourCornerSelection()
    assert not viewer.placementHint.isVisible()
    drag(viewer, (100, 100), (300, 200))
    assert recorded["drawn"] == []
    assert viewer.fourCornersPicked() == 1
    # double-clicks too
    double_click(viewer, (400, 300))
    assert recorded["place"] == []
    viewer.cancelFourCornerSelection()
    assert viewer.placementHint.isVisible()


def test_a_right_click_on_a_box_asks_for_its_menu(viewer, memory_storage, make_target):
    recorded = signals(viewer)
    memory_storage.add_item(make_target("Home Score", rect=(100, 100, 200, 120)))
    center = on_screen(viewer, QRectF(100, 100, 200, 120)).center()
    mouse(viewer, QEvent.Type.MouseButtonPress, center, Qt.MouseButton.RightButton)
    assert viewer.selected == ["Home Score"]  # selected, not deselected
    menu_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, center, viewer.viewport().mapToGlobal(center)
    )
    QApplication.sendEvent(viewer.viewport(), menu_event)
    [(name, point)] = recorded["menu"]
    assert name == "Home Score"
    assert point == viewer.viewport().mapToGlobal(center)
    # on the empty picture: no menu
    menu_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, QPoint(700, 400), QPoint(700, 400)
    )
    QApplication.sendEvent(viewer.viewport(), menu_event)
    assert len(recorded["menu"]) == 1


# --- the main window with a real viewer ------------------------------------------------


def open_picture(window, qtbot, width=1280, height=720):
    """Open a real viewer (without capture) in the window, with a picture."""
    from source_view import ImageViewer

    view = ImageViewer(
        file_source(),
        window.fourCornersApplied,
        window.detectionTargetsStorage,
        window.itemSelected,
        start=False,
    )
    window.image_viewer = view
    window.connectViewer()
    window.ui.frame_firstRun.hide()
    window.ui.frame_for_source_view_label.layout().addWidget(view, 0, 0)
    window.resize(1366, 768)
    with qtbot.waitExposed(window):
        window.show()
    QApplication.processEvents()
    view.timerThread.frame_size = (width, height)
    show_frame(view, width, height)
    window.cameraConnectedEnableUI()
    QApplication.processEvents()
    return view


def field_role(window, name):
    return box_name_item(window, name).data(Qt.ItemDataRole.UserRole)


def test_a_box_drawn_on_the_picture_is_placed(main_window, qtbot):
    ui = main_window.ui
    view = open_picture(main_window, qtbot)
    main_window.itemSelected("Home Fouls")
    assert view.placementField == "Home Fouls"
    assert view.placementHint.isVisible()
    ui.tabWidget_inspector.setCurrentIndex(1)  # Outputs
    drag(view, (200, 150), (320, 230))
    storage = main_window.detectionTargetsStorage
    box = storage.find_item_by_name("Home Fouls")
    assert QRectF(box) == expected_rect(view, (200, 150), (320, 230))
    # the field is on the picture, selected with its box, and its settings shown
    assert field_role(main_window, "Home Fouls") == "checked"
    assert main_window.currentFieldItem().text() == "Home Fouls"
    assert view.selectedBoxName == "Home Fouls"
    assert view.findBox("Home Fouls").selected
    assert ui.tabWidget_inspector.currentWidget() is ui.tab_box
    assert ui.label_selectedInfo.text() == "Home Fouls"
    # with the field's default settings, as Place on picture gives
    from defaults import default_info_for_box_name, normalize_settings_dict

    assert box.settings == normalize_settings_dict(
        {}, default_info_for_box_name("Home Fouls")
    )
    # the crosshair and the hint are gone: the field has its box
    assert view.placementField is None
    assert not view.placementHint.isVisible()
    # the box is saved
    main_window.saveBoxes()
    [stored] = fetch_data("scoresight.json", "boxes")
    assert stored["name"] == "Home Fouls"
    assert stored["rect"]["width"] == box.width()

    # Alt+drag draws it again
    drag(view, (400, 300), (480, 340), modifiers=ALT)
    assert QRectF(box) == expected_rect(view, (400, 300), (480, 340))
    assert view.findBox("Home Fouls").sceneBoxRect() == QRectF(box)
    assert len(storage.get_data()) == 1


def test_a_double_click_places_the_box_in_the_middle_of_what_is_shown(
    main_window, qtbot, monkeypatch
):
    import mainwindow
    from defaults import default_info_for_box_name

    ui = main_window.ui
    view = open_picture(main_window, qtbot)
    view.zoomIn()
    view.zoomIn()
    QApplication.processEvents()
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().value() + 150)
    shown = view.visiblePictureRect()
    table = ui.tableWidget_boxes

    # a field without a box: its box, at its default size, in the middle
    item = box_name_item(main_window, "Time")
    table.itemDoubleClicked.emit(item)
    box = main_window.detectionTargetsStorage.find_item_by_name("Time")
    info = default_info_for_box_name("Time")
    assert (box.width(), box.height()) == (info["width"], info["height"])
    assert abs(box.center().x() - shown.center().x()) <= 1
    assert abs(box.center().y() - shown.center().y()) <= 1
    assert main_window.currentFieldItem().text() == "Time"
    assert view.selectedBoxName == "Time"

    # a field on the picture: renamed (a custom field only)
    renames = []
    monkeypatch.setattr(
        mainwindow.QInputDialog,
        "getText",
        lambda *args, **kwargs: renames.append(kwargs.get("text")) or ("", False),
    )
    table.itemDoubleClicked.emit(box_name_item(main_window, "Time"))
    assert renames == []  # a standard field isn't renamed
    main_window.addBox()
    [name] = fetch_data("scoresight.json", "custom_boxes_names")
    table.itemDoubleClicked.emit(box_name_item(main_window, name))
    assert main_window.detectionTargetsStorage.find_item_by_name(name) is not None
    assert renames == []
    table.itemDoubleClicked.emit(box_name_item(main_window, name))
    assert renames == [name]
    # the double-click on its value too
    table.itemDoubleClicked.emit(table.item(box_name_item(main_window, name).row(), 1))
    assert renames == [name, name]

    # the tooltips say so
    assert "double-click" in box_name_item(main_window, "Period").toolTip()
    assert "Drag over its numbers" in box_name_item(main_window, "Period").toolTip()
    assert "rename" in box_name_item(main_window, name).toolTip()
    assert "rename" not in box_name_item(main_window, "Time").toolTip()
    alt_drag = "⌥ Option+drag" if MAC else "Alt+drag"
    assert alt_drag in box_name_item(main_window, "Time").toolTip()


def test_a_double_click_on_the_picture_places_the_selected_field(main_window, qtbot):
    from defaults import default_info_for_box_name

    view = open_picture(main_window, qtbot)
    main_window.itemSelected("Period")
    double_click(view, (300, 200))
    box = main_window.detectionTargetsStorage.find_item_by_name("Period")
    info = default_info_for_box_name("Period")
    point = view.mapToScene(QPoint(300, 200))
    assert (box.width(), box.height()) == (info["width"], info["height"])
    assert abs(box.center().x() - point.x()) <= 1
    assert abs(box.center().y() - point.y()) <= 1
    assert view.selectedBoxName == "Period"
    # near the edge: inside the picture
    main_window.itemSelected("Time")
    double_click(view, (1, 1))
    box = main_window.detectionTargetsStorage.find_item_by_name("Time")
    assert (box.left(), box.top()) == (0, 0)


def test_place_on_picture_puts_the_box_in_the_middle(main_window, qtbot):
    ui = main_window.ui
    view = open_picture(main_window, qtbot)
    main_window.itemSelected("Home Score")
    ui.pushButton_makeBox.click()
    box = main_window.detectionTargetsStorage.find_item_by_name("Home Score")
    assert abs(box.center().x() - 640) <= 1 and abs(box.center().y() - 360) <= 1
    assert view.selectedBoxName == "Home Score"


def test_del_removes_the_box_or_deletes_the_field(main_window, qtbot):
    from PySide6.QtTest import QTest

    ui = main_window.ui
    view = open_picture(main_window, qtbot)
    storage = main_window.detectionTargetsStorage
    asked = []
    answer = [False]
    main_window.confirm = lambda title, text, action: asked.append(title) or answer[0]
    table = ui.tableWidget_boxes

    main_window.itemSelected("Home Score")
    main_window.placeOnPicture()
    # Del is Remove from picture's key while the field has a box
    assert ui.actionRemoveFromPicture.shortcut().toString() == "Del"
    assert ui.actionDeleteField.shortcut().isEmpty()
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Delete)
    # its settings are kept: no question
    assert asked == []
    assert storage.find_item_by_name("Home Score") is None
    assert field_role(main_window, "Home Score") == "unchecked"
    assert ui.actionRemoveFromPicture.shortcut().isEmpty()
    # a standard field without a box: Del does nothing
    QTest.keyClick(table, Qt.Key.Key_Delete)
    assert "Home Score" in [table.item(r, 0).text() for r in range(table.rowCount())]

    # on the picture too, without asking even with changed settings
    main_window.placeOnPicture()
    ui.horizontalSlider_dilate.setValue(3)
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert asked == []
    assert storage.find_item_by_name("Home Score") is None

    # a custom field: Del removes its box, then (asking) deletes it
    answer[0] = True
    main_window.addBox()
    [name] = fetch_data("scoresight.json", "custom_boxes_names")
    main_window.placeOnPicture()
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Delete)
    assert storage.find_item_by_name(name) is None
    assert name in [table.item(r, 0).text() for r in range(table.rowCount())]
    assert ui.actionDeleteField.shortcut().toString() == "Del"
    QTest.keyClick(table, Qt.Key.Key_Delete)
    assert asked[-1] == "Delete field"
    assert fetch_data("scoresight.json", "custom_boxes_names") == []


def test_the_box_menu_on_the_picture(main_window, qtbot, make_result):
    ui = main_window.ui
    view = open_picture(main_window, qtbot)
    storage = main_window.detectionTargetsStorage
    main_window.itemSelected("Home Score")
    main_window.placeOnPicture()
    main_window.itemSelected(None)
    box = storage.find_item_by_name("Home Score")
    center = on_screen(view, QRectF(box)).center()

    mouse(view, QEvent.Type.MouseButtonPress, center, Qt.MouseButton.RightButton)
    QApplication.sendEvent(
        view.viewport(),
        QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, center, view.viewport().mapToGlobal(center)
        ),
    )
    menu = QApplication.activePopupWidget()
    try:
        assert menu is not None
        names = [
            action.objectName() for action in menu.actions() if action.objectName()
        ]
        assert names == [
            "actionRemoveFromPicture",
            "actionRenameField",
            "actionHoldValue",
            "actionZoomToBox",
        ]
    finally:
        if menu is not None:
            menu.close()
    # its field is selected
    assert main_window.currentFieldItem().text() == "Home Score"
    assert ui.actionRemoveFromPicture.isEnabled()
    assert ui.actionHoldValue.isEnabled() and ui.actionZoomToBox.isEnabled()
    # a standard field isn't renamed, and the menu says why
    assert not ui.actionRenameField.isEnabled()
    assert "custom fields" in ui.actionRenameField.toolTip()
    # a held value: Release too
    main_window.heldValues.hold("Home Score", "7")
    main_window.updateHeldUi()
    menu = main_window.boxContextMenu()
    assert ui.actionReleaseValue in menu.actions()
    menu.deleteLater()
    # the actions work from there
    main_window.confirm = lambda *args: True
    ui.actionRemoveFromPicture.trigger()
    assert storage.find_item_by_name("Home Score") is None


def test_the_footer_says_what_to_do(main_window, qtbot):
    ui = main_window.ui
    hint = ui.label_fieldActionHint
    # before a source: the list's hint says to open one
    assert not hint.isVisibleTo(main_window)
    open_picture(main_window, qtbot)
    assert hint.isVisible()
    assert hint.text() == "Select a field, then drag over its numbers on the picture."
    # quieter than the list: flat buttons
    assert ui.pushButton_makeBox.isFlat() and ui.pushButton_removeBox.isFlat()

    main_window.itemSelected("Home Score")
    assert hint.text() == "Drag on the picture to place it, or double-click the field"
    assert ui.pushButton_makeBox.isVisible() and ui.pushButton_makeBox.isEnabled()
    main_window.placeOnPicture()
    delete = "⌦" if MAC else "Del"
    assert hint.text() == f"Drag the box to move it · {delete} removes it"
    assert ui.pushButton_removeBox.isVisible()
    assert f"({delete})" in ui.pushButton_removeBox.toolTip()

    main_window.addBox()
    ui.checkBox_templatefield.setChecked(True)
    assert hint.text().startswith("This field is built from other fields")
    assert not ui.pushButton_makeBox.isVisible()
    assert not ui.pushButton_removeBox.isVisible()


def test_the_first_run_step_counts_boxes_on_the_picture(main_window, make_target):
    assert main_window.firstRunSteps()[1] is False
    assert (
        main_window.ui.label_firstRunBoxesHint.text()
        == "Select a field, then drag over its numbers on the picture."
    )
    storage = main_window.detectionTargetsStorage
    # a template field has no box, nor does a box without an area
    storage.add_item(make_target("Custom 1", templatefield=True))
    storage.add_item(make_target("Custom 2", rect=(10, 10, 0, 0)))
    assert main_window.firstRunSteps()[1] is False
    storage.add_item(make_target("Home Score", rect=(10, 10, 80, 40)))
    assert main_window.firstRunSteps()[1] is True
    main_window.refreshLiveStatus()
    assert main_window.ui.label_firstRunStep2.accessibleName() == "Step 2: done"


def test_drawing_works_in_the_live_layout(main_window, qtbot):
    ui = main_window.ui
    view = open_picture(main_window, qtbot)
    main_window.setLayoutMode("live")
    assert not ui.widget_fieldsFooter.isVisible()
    main_window.itemSelected("Home Fouls")
    # the hint over the picture (the footer is hidden)
    assert view.placementHint.isVisible()
    drag(view, (150, 100), (260, 180))
    assert main_window.detectionTargetsStorage.find_item_by_name("Home Fouls")
    assert field_role(main_window, "Home Fouls") == "checked"
    main_window.setLayoutMode("setup")


def test_esc_in_the_window_cancels_the_drawing(main_window, qtbot):
    view = open_picture(main_window, qtbot)
    main_window.itemSelected("Home Fouls")
    drag(view, (150, 100), (260, 180), release=False)
    assert view.isDrawing()
    # (the key reaches the window when the focused widget doesn't use it)
    main_window.eventFilter(
        main_window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NO_MODIFIER)
    )
    assert not view.isDrawing()
    mouse(view, QEvent.Type.MouseButtonRelease, QPoint(260, 180))
    assert main_window.detectionTargetsStorage.find_item_by_name("Home Fouls") is None
    assert main_window.currentFieldItem().text() == "Home Fouls"


def test_the_shortcuts_dialog_lists_the_mouse(main_window):
    rows = [row for _, group in main_window.keyboardShortcutGroups() for row in group]
    names = {name: keys for name, keys in rows}
    # a Mac also deletes with the key labelled "delete", which is Backspace
    delete_keys = "⌦, ⌫" if MAC else "Del"
    assert names["Remove the selected field's box from the picture"] == delete_keys
    assert names["Delete the selected custom field (not on the picture)"] == (
        delete_keys
    )
    assert names["Put a field's box on the picture, or rename a custom field"] == (
        "Double-click the field"
    )
    assert names["Place the selected field's box"] == (
        "Drag over its numbers on the picture"
    )
    assert names["Draw the selected box again"] == (
        "⌥ + drag on the picture" if MAC else "Alt + drag on the picture"
    )
    assert names["The selected box's actions"] == "Right-click the box"


# --- Drag to crop ---------------------------------------------------------------------


def test_the_preview_is_uncropped_while_the_crop_is_picked(memory_storage):
    # the whole frame, after the rotation; the OCR reads the cropped one
    thread = camera_thread.TimerThread(file_source(), memory_storage)
    try:
        previews = []
        thread.update_signal.connect(previews.append)
        thread.crop.rotation = 90
        thread.crop.isCropSet = True
        thread.crop.cropLeft, thread.crop.cropTop = 10, 20
        thread.crop.cropRight, thread.crop.cropBottom = 5, 6
        frame = np.zeros((48, 64, 3), np.uint8)
        frame[:, 32:] = 255
        thread.process_frame(frame.copy())
        assert previews[-1].shape[:2] == (64 - 26, 48 - 15)
        thread.preview_uncropped = True
        thread.requestPreview()
        thread.process_frame(frame.copy())
        assert np.array_equal(previews[-1], np.rot90(frame, -1))
        assert thread.adjust_frame(frame).shape[:2] == (64 - 26, 48 - 15)
    finally:
        thread.cleanup()


def test_readings_of_frames_cropped_as_before_are_dropped(memory_storage, make_target):
    # The OCR reads a frame on its own thread, after the frame was cropped: a
    # crop change meanwhile moves the boxes, which would read other pixels.
    from text_detection_target import TextDetectionResult, TextDetectionTargetWithResult

    class Detector:
        def __init__(self):
            self.calls = 0
            self.on_call = None

        def detect_multi_text(self, binary, gray, rects, display=None, color=None):
            self.calls += 1
            if self.on_call is not None:
                self.on_call()
            return [
                TextDetectionResult(
                    "7", TextDetectionTargetWithResult.ResultState.Success
                )
                for _ in rects
            ]

    thread = camera_thread.TimerThread(file_source(), memory_storage)
    try:
        clock = [100.0]
        thread._clock = lambda: clock[0]
        thread.textDetector = Detector()
        results = []
        thread.ocr_result_signal.connect(results.append)
        memory_storage.add_item(make_target("Home Score"))
        frame = np.zeros((48, 64, 3), np.uint8)
        thread.run_ocr_cycle(frame, 99.0)
        assert len(results) == 1
        # the boxes moved after the frame was read: not even read
        thread.boxesMoved()
        thread.run_ocr_cycle(frame, 99.5)
        assert len(results) == 1 and thread.textDetector.calls == 1
        # ... or while it was read: not published
        clock[0] = 101.0
        thread.textDetector.on_call = thread.boxesMoved
        thread.run_ocr_cycle(frame, 100.5)
        assert len(results) == 1
        thread.textDetector.on_call = None
        thread.run_ocr_cycle(frame, 101.5)
        assert len(results) == 2
    finally:
        thread.cleanup()


@pytest.fixture
def cropping_window(main_window, qtbot):
    """The window with a real viewer on a 1280x720 frame, Crop on (no
    margins), and a box over (500, 300)."""
    ui = main_window.ui
    view = open_picture(main_window, qtbot)
    ui.toolButton_topCrop.click()
    main_window.itemSelected("Home Score")
    main_window.placeFieldBox("Home Score", QRectF(500, 300, 100, 60))
    main_window.itemSelected(None)
    return main_window, view


def pick_crop(window, view, width=1280, height=720):
    """Drag to crop, and the whole frame as the next preview."""
    window.ui.toolButton_dragCrop.click()
    show_frame(view, width, height)


def test_drag_to_crop_sets_the_crop_and_keeps_the_boxes_on_their_digits(
    cropping_window,
):
    window, view = cropping_window
    ui = window.ui
    storage = window.detectionTargetsStorage
    box = storage.find_item_by_name("Home Score")
    view.timerThread.homography = None
    store_data(
        "scoresight.json",
        "four_corners",
        [[400, 200], [900, 200], [900, 600], [400, 600]],
    )

    pick_crop(window, view)
    assert view.cropSelectionMode and view.timerThread.preview_uncropped
    assert ui.toolButton_dragCrop.isChecked()
    assert ui.frame_cropBanner.isVisible()
    assert "Esc cancels" in ui.label_cropBanner.text()
    # the boxes are hidden: they sit on the cropped picture
    assert not view.findBox("Home Score").isVisible()
    view.zoomIn()
    QApplication.processEvents()
    start, end = (60, 40), (700, 380)
    rect = expected_rect(view, start, end)
    drag(view, start, end)
    assert not view.cropSelectionMode and not view.timerThread.preview_uncropped
    assert not ui.frame_cropBanner.isVisible()
    left, top = int(rect.left()), int(rect.top())
    right, bottom = int(1280 - rect.right()), int(720 - rect.bottom())
    assert (
        ui.spinBox_leftCrop.value(),
        ui.spinBox_topCrop.value(),
        ui.spinBox_rightCrop.value(),
        ui.spinBox_bottomCrop.value(),
    ) == (left, top, right, bottom)
    assert [
        fetch_data("scoresight.json", key, 0)
        for key in ("left_crop", "top_crop", "right_crop", "bottom_crop", "crop_mode")
    ] == [left, top, right, bottom, True]
    # the boxes stay over the same pixels of the frame (and the 4-corner
    # correction's corners)
    assert (box.x(), box.y()) == (500 - left, 300 - top)
    assert fetch_data("scoresight.json", "four_corners")[0] == [400 - left, 200 - top]
    assert view.findBox("Home Score").isVisible()
    # the view is fitted
    assert view.fitted


def test_esc_keeps_the_crop(cropping_window):
    window, view = cropping_window
    ui = window.ui
    ui.spinBox_leftCrop.setValue(30)
    box = window.detectionTargetsStorage.find_item_by_name("Home Score")
    position = (box.x(), box.y())
    pick_crop(window, view)
    drag(view, (60, 40), (300, 200), release=False)
    key(view, Qt.Key.Key_Escape)  # the drag
    assert view.cropSelectionMode
    key(view, Qt.Key.Key_Escape)  # the picking
    assert not view.cropSelectionMode and not view.timerThread.preview_uncropped
    assert not ui.toolButton_dragCrop.isChecked()
    mouse(view, QEvent.Type.MouseButtonRelease, QPoint(300, 200))
    assert fetch_data("scoresight.json", "left_crop") == 30
    assert (box.x(), box.y()) == position
    # Cancel in the banner too
    pick_crop(window, view)
    ui.pushButton_cancelCrop.click()
    assert not view.cropSelectionMode


def test_a_tiny_drag_doesnt_crop(cropping_window):
    window, view = cropping_window
    pick_crop(window, view)
    drag(view, (100, 100), (102, 300))
    assert view.cropSelectionMode
    assert fetch_data("scoresight.json", "left_crop", 0) == 0


def test_the_crop_is_clamped_to_the_picture(cropping_window):
    window, view = cropping_window
    ui = window.ui
    pick_crop(window, view)
    picture = on_screen(view, view.pictureRect())
    # from outside the picture to beyond its other corner
    drag(
        view,
        (picture.left() - 30, picture.center().y()),
        (picture.right() + 50, picture.bottom() + 50),
    )
    assert ui.spinBox_leftCrop.value() == 0
    assert ui.spinBox_rightCrop.value() == 0
    assert ui.spinBox_bottomCrop.value() == 0
    assert 300 < ui.spinBox_topCrop.value() < 420


def test_the_crop_under_rotation(cropping_window):
    window, view = cropping_window
    ui = window.ui
    window.rotateImage()  # 90°: the frame is 720 wide, 1280 tall
    assert view.uncroppedFrameSize() == QSizeF(720, 1280)
    ui.toolButton_dragCrop.click()
    # the cropped picture is still shown: a drag waits for the whole frame
    show_frame(view, 600, 400)
    drag(view, (300, 50), (400, 300))
    assert view.cropSelectionMode
    # the whole rotated frame
    show_frame(view, 720, 1280)
    view.zoomIn()
    QApplication.processEvents()
    rect = expected_rect(view, (300, 50), (450, 300))
    drag(view, (300, 50), (450, 300))
    assert ui.spinBox_leftCrop.value() == int(rect.left())
    assert ui.spinBox_rightCrop.value() == int(720 - rect.right())
    assert ui.spinBox_bottomCrop.value() == int(1280 - rect.bottom())


def test_the_crop_values_move_the_boxes_too(cropping_window):
    # The boxes are placed on the cropped picture: a new left or top crop used
    # to leave them over other digits.
    window, view = cropping_window
    ui = window.ui
    box = window.detectionTargetsStorage.find_item_by_name("Home Score")
    assert view.timerThread.boxes_moved_at is None
    ui.spinBox_leftCrop.setValue(100)
    ui.spinBox_topCrop.setValue(50)
    assert (box.x(), box.y()) == (400, 250)
    # the readings of the frames cropped as before are dropped
    assert view.timerThread.boxes_moved_at is not None
    # right and bottom don't move the picture's corner
    ui.spinBox_rightCrop.setValue(80)
    ui.spinBox_bottomCrop.setValue(40)
    assert (box.x(), box.y()) == (400, 250)
    # Crop off: the whole frame again, the box over the same pixels
    ui.toolButton_topCrop.click()
    assert (box.x(), box.y()) == (500, 300)
    ui.toolButton_topCrop.click()
    assert (box.x(), box.y()) == (400, 250)
    assert window.boxesOutsidePicture() == []
    assert not ui.label_cropWarning.isVisible()


def test_reset_crop_reads_the_whole_picture_with_the_boxes_on_their_digits(
    cropping_window,
):
    window, view = cropping_window
    ui = window.ui
    box = window.detectionTargetsStorage.find_item_by_name("Home Score")
    store_data(
        "scoresight.json",
        "four_corners",
        [[400, 200], [900, 200], [900, 600], [400, 600]],
    )
    # nothing to reset yet
    assert not ui.toolButton_resetCrop.isEnabled()
    ui.spinBox_leftCrop.setValue(100)
    ui.spinBox_topCrop.setValue(50)
    ui.spinBox_rightCrop.setValue(80)
    assert ui.toolButton_resetCrop.isEnabled()
    assert (box.x(), box.y()) == (400, 250)

    # it asks first: Cancel keeps the crop
    asked = []
    window.confirm = lambda title, text, action: asked.append(action) or False
    ui.toolButton_resetCrop.click()
    assert asked == ["Reset crop"]
    assert window.cropValues() == (100, 50, 80, 0)
    assert ui.toolButton_topCrop.isChecked()

    window.confirm = lambda title, text, action: True
    pick_crop(window, view)
    ui.toolButton_resetCrop.click()
    assert window.cropValues() == (0, 0, 0, 0)
    assert [
        fetch_data("scoresight.json", key, 0)
        for key in ("left_crop", "top_crop", "right_crop", "bottom_crop", "crop_mode")
    ] == [0, 0, 0, 0, False]
    # the crop is off, its panel closed, and Drag to crop stopped
    assert not ui.toolButton_topCrop.isChecked()
    assert not ui.widget_cropPanel.isVisibleTo(window)
    assert not view.cropSelectionMode and not ui.frame_cropBanner.isVisible()
    # the boxes (and the 4-corner corners) are back over the same pixels
    assert (box.x(), box.y()) == (500, 300)
    assert fetch_data("scoresight.json", "four_corners")[0] == [400, 200]
    assert not ui.toolButton_resetCrop.isEnabled()
    # Crop on again starts from the whole picture
    ui.toolButton_topCrop.click()
    assert (box.x(), box.y()) == (500, 300)


def test_a_box_outside_the_crop_stays_and_is_named(cropping_window):
    window, view = cropping_window
    ui = window.ui
    box = window.detectionTargetsStorage.find_item_by_name("Home Score")
    pick_crop(window, view)
    # keep the top-left part only: the box (at 500, 300) is left outside
    corner = on_screen(view, QRectF(0, 0, 400, 250))
    drag(view, (corner.left() + 1, corner.top() + 1), (corner.right(), corner.bottom()))
    assert ui.spinBox_rightCrop.value() > 800
    # kept where it is, over the same pixels: a wider crop brings it back
    assert (box.x(), box.y()) == (
        500 - ui.spinBox_leftCrop.value(),
        300 - ui.spinBox_topCrop.value(),
    )
    assert window.boxesOutsidePicture() == ["Home Score"]
    assert ui.label_cropWarning.isVisible()
    assert "Home Score" in ui.label_cropWarning.text()
    # (not in the Live layout)
    window.setLayoutMode("live")
    assert not ui.label_cropWarning.isVisible()
    window.setLayoutMode("setup")
    ui.spinBox_rightCrop.setValue(0)
    ui.spinBox_bottomCrop.setValue(0)
    assert window.boxesOutsidePicture() == []
    assert not ui.label_cropWarning.isVisible()


def test_the_hidden_boxes_dont_move_while_the_crop_is_picked(cropping_window):
    window, view = cropping_window
    box = window.detectionTargetsStorage.find_item_by_name("Home Score")
    view.selectBox("Home Score")
    pick_crop(window, view)
    key(view, Qt.Key.Key_Right)
    assert (box.x(), box.y()) == (500, 300)


def test_crop_and_four_corner_picking_exclude_each_other(cropping_window):
    window, view = cropping_window
    ui = window.ui
    pick_crop(window, view)
    ui.pushButton_fourCorner.click()
    assert view.fourCornerSelectionMode and not view.cropSelectionMode
    assert not ui.toolButton_dragCrop.isChecked()
    assert not ui.frame_cropBanner.isVisible()
    ui.toolButton_dragCrop.click()
    assert view.cropSelectionMode and not view.fourCornerSelectionMode
    assert not ui.frame_fourCornerBanner.isVisible()
    # the Live layout stops it (the crop panel is hidden there)
    window.setLayoutMode("live")
    assert not view.cropSelectionMode
    window.setLayoutMode("setup")
    # Crop off stops it too
    ui.toolButton_dragCrop.click()
    ui.toolButton_topCrop.click()
    assert not view.cropSelectionMode
