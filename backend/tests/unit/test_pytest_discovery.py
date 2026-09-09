"""Directory conventions must not hide explicitly isolated integration coverage."""
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize('isolated,explicit_e2e,expected_e2e', [
    (True, False, False), (True, True, True), (False, False, True),
])
def test_isolated_integration_discovery_preserves_live_opt_in(request, isolated, explicit_e2e, expected_e2e):
    tests_dir = Path(__file__).resolve().parents[1]
    plugin = request.config.pluginmanager.get_plugin(str(tests_dir / 'conftest.py'))
    assert plugin is not None
    item = Mock(fspath=tests_dir / 'integration/test_example.py')
    item.keywords = {}
    if isolated:
        item.keywords['isolated'] = True
    if explicit_e2e:
        item.keywords['e2e'] = True
    item.add_marker.side_effect = lambda marker: item.keywords.update({marker.name: True})
    config = Mock()
    config.getoption.return_value = False
    plugin.pytest_collection_modifyitems(config, [item])
    assert ('e2e' in item.keywords) is expected_e2e
    assert ('skip' in item.keywords) is expected_e2e
