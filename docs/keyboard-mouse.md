---
title: Keyboard & Mouse
parent: Reference
nav_order: 3
description: "All mouse and keyboard controls in ScoreSight's viewer, field list, panes and Training Dojo."
---

# Keyboard & Mouse

## Viewer

| Action | Control |
|---|---|
| Zoom in / out | **Ctrl + mouse wheel** (**⌘ Cmd + mouse wheel** on macOS), or **Ctrl+=** and **Ctrl+-**, up to 400% |
| Fit picture to window | **Fit**, or **Ctrl+0** |
| Scroll | Mouse wheel; scroll bars when zoomed in |
| Pan | Hold the **middle mouse button** and drag |
| Place the selected field's box | With a field that isn't on the picture selected (the pointer is a crosshair), **left-drag** over its numbers. A drag of a few pixels counts as a click; **Esc** cancels the drag |
| Place the selected field's box at a point | **Double-click** the picture: the box, at its default size, is centred there |
| Select a box | **Left-click** the box (also while a field without a box is selected) |
| Move a box | **Left-drag** the box |
| Resize a box | **Left-drag** an edge or a corner handle of the selected box |
| Draw the selected box again | **Alt + left-drag** (**⌥ Option + drag** on macOS) on the picture |
| The box's actions | **Right-click** the box: Remove from picture, Rename..., Hold value... (and Release held value), Zoom to box |
| Take the selected box off the picture | **Del** (**Backspace** on a Mac) while the viewer has the keyboard; asks first if you changed its settings |
| Rename the selected custom field | **F2** while the viewer has the keyboard |
| Nudge the selected box | **Arrow keys**: 1 pixel; **Shift + arrow keys**: 10 pixels (the viewer must have the keyboard: click the picture or the box) |
| Deselect | **Left-click** empty space, or press **Esc** (while a field without a box is selected, a click keeps it selected: press **Esc**) |
| Set 4-corner points | After clicking **4-corner** (or **Redo corners…** in its menu), **left-click** four corners. **Esc** cancels and keeps the previous correction |
| Crop with the mouse | After clicking **Drag to crop** (in the crop panel, with **Crop** on), **left-drag** around the part of the picture to keep, on the whole picture. **Esc** cancels and keeps the current crop |
| Add a per-character sub-box | With **Per-character sub-boxes** on (in the Box tab's **Image cleanup**), click the green **+** in the box (experimental) |

Box positions and sizes are saved automatically. While picking 4-corner points or the crop, a drag or a click picks: it doesn't draw boxes. The middle mouse button always pans.

## Field list

| Action | Control |
|---|---|
| Select a field (and its box) | Click its name or its value |
| The selected field's actions | **Right-click** it: Place on picture or Remove from picture, Rename..., Delete field..., Reset settings to defaults, Copy value, Hold value... (and Release held value), Zoom to box |
| Put a field's box on the picture | **Double-click** a field that isn't on the picture: its box appears in the middle of the part of the picture you see (or drag on the picture, see [Viewer](#viewer)) |
| Rename a custom field | **F2**, or double-click a custom field that is on the picture |
| Add a custom field | **+** at the top of the list, or **Ctrl+N** |
| Take the selected field's box off the picture | **Del** (**Backspace** on a Mac); asks first if you changed its settings |
| Delete the selected custom field | **Delete field** under the list, or **Del** (**Backspace** on a Mac) when it isn't on the picture (asks first) |
| Copy the selected field's value | **Ctrl+C** |
| Hold the selected field's value (send a value you type instead of its readings) | **Ctrl+H** (**⌃ Control+H** on a Mac), or right-click > **Hold value...** |
| Release a held value | **Release** in its row, or right-click > **Release held value** |
| Put the selected field on the picture, with the keyboard | **Place on picture** under the list (in ScoreSight 0.1.x: **Add to Scene**) |
| Take the selected field off the picture, with the keyboard | **Remove from picture** under the list (in 0.1.x: **Remove Selected**) |
| Deselect | **Esc** |

**F2**, **Del** and **Ctrl+C** work while the field list has the focus (click a field first); **F2** and **Del** also while the viewer has it. **Del** takes the box off the picture when the field has one, and otherwise deletes a custom field. **Ctrl+H** works anywhere in the window, on the selected field. The Live layout hides the buttons under the list: their actions are in the right-click menu, and drawing on the picture works as in the Setup layout.

## Panes

| Action | Control |
|---|---|
| Make the field list, the picture or the inspector wider | Drag the dividers between them |
| Hide or show the field list or the inspector | Double-click the divider next to it, or drag it to the window's edge |
| Setup layout: the field list, the picture with its adjustments, the inspector | **View > Setup layout**, or **Ctrl+1** |
| Live layout: large readings and the outputs' state, for the game | **View > Live layout**, or **Ctrl+2** |

ScoreSight remembers the layout, the widths and which panes are hidden. The Setup layout gets back the widths it had; the Live layout keeps the width of its field list. A click on an output in the status bar shows the inspector's **Outputs** tab, also when the inspector was hidden.

## Main window shortcuts

On macOS, use **⌘ Cmd** wherever this table says **Ctrl** (except **Ctrl + H**: **⌃ Control + H** on a Mac, as ⌘H hides the app). The tooltips of the buttons show their shortcut, and **Help > Keyboard shortcuts** lists them all.

| Key | Action |
|---|---|
| **Ctrl + 1** / **Ctrl + 2** | Setup layout / Live layout |
| **Ctrl + Shift + P** | Pause outputs / Resume outputs |
| **Ctrl + B** | Binary View on or off (once a source is open) |
| **Ctrl + 0** | Fit the picture to the window (the **Fit** button) |
| **Ctrl + =** / **Ctrl + -** | Zoom in / out |
| **F5** | Reload the sources (cameras and NDI) |
| **Ctrl + N** | New custom field |
| **Ctrl + H** | Hold value... of the selected field |
| **Ctrl + O** / **Ctrl + Shift + S** | Import field layout... / Export field layout... |
| **Ctrl + Shift + L** | View log |
| **F1** | User guide (this site) |
| **Ctrl + Q** | Quit |
| **Esc** | Cancel a drag on the picture, picking 4-corner points or Drag to crop, or deselect the box |

## Training Dojo

On macOS, use **⌘ Cmd** wherever this table says **Ctrl**. The shortcuts work while you type in the annotation box.

| Key | Action |
|---|---|
| **Enter** | Approve and go to the next image |
| **Shift + Enter** | Previous image |
| **Up** / **Down** | Previous / next image |
| **Ctrl + Up** / **Ctrl + Down** | Previous / next unapproved image |
| **Ctrl + N** / **Ctrl + B** | Next / back |
| **Ctrl + U** | Remove the approval |

See [OCR Training Data](data_annotation.md).

## Menus

On Windows and Linux, the menus are at the top of the main window. On macOS they are in the system menu bar. Menu items show their shortcuts.

**File**: **Import field layout...** (Ctrl+O) and **Export field layout...** (Ctrl+Shift+S) (in 0.1.x: Import/Export Configuration, see [Import and export layouts](boxes.md#import-and-export-layouts)), **Open settings folder**, **Ask before closing** and **Quit** (Ctrl+Q). With **Ask before closing** on (the default), closing ScoreSight while a source is open asks first, because it stops the reading and the outputs; **Don't ask again** in that question turns it off. Ctrl+C or a `kill` of a headless ScoreSight, and **Update now**, close without asking.

**View**:

- **Setup layout** (Ctrl+1) and **Live layout** (Ctrl+2), see [Setup and Live layouts](boxes.md#setup-and-live-layouts)
- **Binary View** (Ctrl+B), **Fit picture to window** (Ctrl+0), **Zoom in** (Ctrl+=), **Zoom out** (Ctrl+-), [Smooth preview](view-tools.md#smooth-preview) and **Statistics overlay**
- **Show unused fields**: the fields that aren't on the picture in the field list, remembered for each layout (shown in the Setup layout, hidden in the Live layout at first)
- **Appearance**: System, Light or Dark colour scheme. The choice is remembered
- **Language**: each language is listed in its own language: English (US), Français, Español, Deutsch, Italiano, 日本語, 한국어, Nederlands, Polski, Português (Brasil), Português (Portugal), Русский and 简体中文. The current one is ticked, and the choice is remembered

**Tools**: **Pause outputs** (Ctrl+Shift+P), **Reload sources** (F5), **Collect OCR training data** (on or off), **OCR training data setup...** (see [OCR Training Data](data_annotation.md)) and **View log** (Ctrl+Shift+L).

**Help**: **User guide** (F1, opens this site), **Keyboard shortcuts**, **Check for updates...** (asks GitHub for the latest release and always shows the result) and **About**.

In ScoreSight 0.1.x, Check for Updates, About, View Current Log, OCR Training Data Setup and Language were in the **File** menu. On macOS, **About** and **Quit** are in the **ScoreSight** application menu (next to the Apple menu).
