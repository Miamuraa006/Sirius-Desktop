from pathlib import Path
import pytest
from core.engine import Engine
from core.models import Command

@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('answer',['подтверждаю','отмена','давай','не надо'])
def test_nested_roots_share_policy_and_handler_grant(tmp_path,reverse,answer):
    root=tmp_path/'files';child=root/'nested';child.mkdir(parents=True)
    source=root/'a.txt';source.write_text('fixture',encoding='utf8')
    destination=child/'b.txt'
    roots=[str(root),str(child)]
    if reverse:roots.reverse()
    config={'_resource_root':str(Path(__file__).resolve().parents[1]),'history':{'enabled':False},
            'files':{'root':str(root),'allowed_roots':roots}}
    engine=Engine(config,tmp_path/'profile')
    try:
        result=engine.execute(Command(f'перемести "{source}" в "{destination}"'))
        assert result.status=='needs_confirmation'
        assert 'desktop' in engine.policy.pending, 'Handler requested confirmation but no policy approval exists'
        assert source.exists() and not destination.exists()
        completed=engine.execute(Command(answer))
        assert completed.verified
        assert destination.exists()==(answer in ('подтверждаю','давай'))
        assert source.exists()==(answer in ('отмена','не надо'))
        assert not engine.execute(Command('подтверждаю')).verified
    finally:engine.close()
