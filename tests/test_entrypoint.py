from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).parents[1]

def test_cli_help_without_loading_voice_or_gui():
    completed=subprocess.run([sys.executable,str(ROOT/'main.py'),'--help'],capture_output=True,text=True,encoding='utf8',timeout=10)
    assert completed.returncode==0,completed.stderr
    assert '--no-voice' in completed.stdout and '--smoke-output' in completed.stdout

def test_entrypoint_does_not_import_gui_for_config_failure(tmp_path):
    (tmp_path/'config.json').write_text('{invalid',encoding='utf8')
    completed=subprocess.run([sys.executable,str(ROOT/'main.py'),'--data-dir',str(tmp_path),'--text','cpu'],capture_output=True,text=True,encoding='utf8',timeout=10)
    assert completed.returncode==2
    assert 'config.json' in completed.stderr
    assert (tmp_path/'config.json').read_text(encoding='utf8')=='{invalid'
