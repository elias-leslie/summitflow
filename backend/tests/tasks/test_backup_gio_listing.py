import subprocess

from app.tasks import backup_native_offsite as offsite


def test_gio_space_separated_attributes_do_not_become_part_of_display_name(monkeypatch):
    # Actual GVfs output uses tabs between columns but spaces between attributes.
    output = 'google-drive://account/root/id\t0\t(directory)\tstandard::display-name=SummitFlow Backups time::modified=1755955771\n'
    monkeypatch.setattr(offsite, '_run', lambda *args, **kwargs: subprocess.CompletedProcess([], 0, output, ''))
    assert offsite._find_display_child('google-drive://account/root', 'SummitFlow Backups') == 'google-drive://account/root/id'
