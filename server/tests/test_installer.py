import os
from pathlib import Path
import pytest
from scripts.install import validate_media_path,install

@pytest.mark.skipif(os.name != 'posix', reason='Linux installer requires POSIX paths and permissions')
def test_paths(tmp_path):
    a=tmp_path/'media A';b=tmp_path/'media-b';a.mkdir();b.mkdir()
    assert validate_media_path(str(a))==a
    assert validate_media_path(str(b))==b

@pytest.mark.parametrize('bad',['etc/passwd','/','/etc','/proc','/tmp/foo:$BAR','/tmp/hello\nNOVA_GID=0','/tmp/a#b','/tmp/q"evil','/tmp/evil$var'])
def test_reject_bad_paths(bad):
    with pytest.raises((ValueError,FileNotFoundError)):validate_media_path(bad)

@pytest.mark.skipif(os.name != 'posix', reason='Linux installer requires POSIX paths and permissions')
def test_create_config_and_secrets(tmp_path):
    a=tmp_path/'media a';b=tmp_path/'media-b';a.mkdir();b.mkdir()
    root=tmp_path/'pkg';root.mkdir()
    result=install(str(a),str(b),root=root,uid=1000,gid=1000)
    env=root/'.env'
    assert env.exists()
    assert 'NOVA_UID=1000' in env.read_text()
    assert 'NOVA_MEDIA_A=' in env.read_text()
    token=root/'state/nova/bootstrap.token'
    assert len(token.read_text().strip())>50
    assert env.stat().st_mode&0o777==0o600
    assert token.stat().st_mode&0o777==0o600
    with pytest.raises(FileExistsError):install(str(a),str(b),root=root,uid=1000,gid=1000)

@pytest.mark.skipif(os.name != 'posix', reason='Must reach the nested-directory check on Linux')
def test_nested_dirs_rejected(tmp_path):
    p=tmp_path/'p';q=p/'q';q.mkdir(parents=True)
    root=tmp_path/'pkg';root.mkdir()
    with pytest.raises(ValueError, match='conter um ao outro'):install(str(p),str(q),root=root,uid=1000,gid=1000)

@pytest.mark.skipif(os.name != 'posix', reason='Must reach the UID check on Linux')
def test_root_disallowed(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir()
    root=tmp_path/'pkg';root.mkdir()
    with pytest.raises(ValueError, match='root'):install(str(a),str(b),root=root,uid=0,gid=0)

@pytest.mark.skipif(os.name != 'posix', reason='Linux paths')
def test_private_state_cannot_be_inside_media(tmp_path):
    a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir()
    root=a/'nova'; root.mkdir()
    with pytest.raises(ValueError, match='separados'):
        install(str(a),str(b),root=root,uid=1000,gid=1000)
    assert not (root/'.env').exists()

@pytest.mark.skipif(os.name != 'posix', reason='Linux paths')
def test_partial_existing_state_is_preserved(tmp_path):
    a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir()
    root=tmp_path/'package'; (root/'state/nova').mkdir(parents=True)
    database=root/'state/nova/nova.sqlite3'; database.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        install(str(a),str(b),root=root,uid=1000,gid=1000)
    assert database.read_bytes() == b'existing'
    assert not (root/'.env').exists()
