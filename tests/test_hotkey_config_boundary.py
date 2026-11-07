import pytest
from core.config import validate
from voice.hotkey import GlobalHotkey

@pytest.mark.parametrize('value',[{'modifiers':0},{'key':255}])
def test_config_rejects_the_same_invalid_hotkey_as_native_constructor(value):
    with pytest.raises(ValueError):validate({'hotkey':value})
    with pytest.raises(ValueError):GlobalHotkey(lambda:None,**value)

@pytest.mark.parametrize('modifiers,key',[(1,1),(15,254),(1,77)])
def test_hotkey_valid_boundaries_agree(modifiers,key):
    assert validate({'hotkey':{'modifiers':modifiers,'key':key}})['hotkey']['key']==key
    GlobalHotkey(lambda:None,modifiers,key)
