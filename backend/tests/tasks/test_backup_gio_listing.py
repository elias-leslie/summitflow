import subprocess

from app.tasks import backup_native_offsite as offsite


def test_retention_keeps_newest_and_current_verified_copy(monkeypatch):
    children = [
        {"uri": "drive/old", "display_name": "source-20200101-000000.tar.gz.age"},
        {"uri": "drive/verified", "display_name": "source-20200102-000000.tar.gz.age"},
        {"uri": "drive/newest", "display_name": "source-20200103-000000.tar.gz.age"},
        {"uri": "drive/other", "display_name": "unrelated-owner-document"},
    ]
    monkeypatch.setattr(offsite, "_list_children", lambda _uri: children)
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(offsite, "_run", run)
    assert offsite._apply_remote_retention("drive/folder", 14, "drive/verified") == ["drive/old"]
    assert calls == [["gio", "remove", "drive/old"]]


def test_gio_space_separated_attributes_do_not_become_part_of_display_name(monkeypatch):
    # Actual GVfs output uses tabs between columns but spaces between attributes.
    output = 'google-drive://account/root/id\t0\t(directory)\tstandard::display-name=SummitFlow Backups time::modified=1755955771\n'
    monkeypatch.setattr(offsite, '_run', lambda *args, **kwargs: subprocess.CompletedProcess([], 0, output, ''))
    assert offsite._find_display_child('google-drive://account/root', 'SummitFlow Backups') == 'google-drive://account/root/id'
