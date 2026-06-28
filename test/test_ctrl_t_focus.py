"""ctrl+t must cycle tabs regardless of where keyboard focus currently sits.

Regression: when focus was on a widget inside the active pane (e.g. the filter
box, the normal state once you start interacting), TabbedContent silently
reverted the `active` change, so ctrl+t appeared to do nothing until a tab was
clicked.
"""

import pytest
from textual.widgets import Input, TabbedContent

from ros_tui.ros.bridge import RosBridge
from ros_tui.ui.app import RosTuiApp


@pytest.mark.asyncio
async def test_ctrl_t_cycles_with_focus_inside_pane():
    bridge = RosBridge(node_name='ctrl_t_focus_inside_pane')
    bridge.start()
    app = RosTuiApp(bridge)
    try:
        async with app.run_test() as pilot:
            tabbed = app.query_one(TabbedContent)
            assert tabbed.active == 'topics'
            # Put focus inside the active pane, as happens once you filter/select.
            app.query_one('#topics-tab').query_one(Input).focus()
            await pilot.pause()
            await pilot.press('ctrl+t')
            assert tabbed.active == 'services'
            await pilot.press('ctrl+t')
            assert tabbed.active == 'actions'
    finally:
        bridge.shutdown()


@pytest.mark.asyncio
async def test_ctrl_t_cycles_with_no_focus():
    bridge = RosBridge(node_name='ctrl_t_focus_no_focus')
    bridge.start()
    app = RosTuiApp(bridge)
    try:
        async with app.run_test() as pilot:
            tabbed = app.query_one(TabbedContent)
            app.set_focus(None)
            await pilot.pause()
            await pilot.press('ctrl+t')
            assert tabbed.active == 'services'
    finally:
        bridge.shutdown()


@pytest.mark.asyncio
async def test_ctrl_t_wraps_around():
    bridge = RosBridge(node_name='ctrl_t_focus_wraps_around')
    bridge.start()
    app = RosTuiApp(bridge)
    try:
        async with app.run_test() as pilot:
            tabbed = app.query_one(TabbedContent)
            for expected in ('services', 'actions', 'nodes', 'topics'):
                await pilot.press('ctrl+t')
                assert tabbed.active == expected
    finally:
        bridge.shutdown()
