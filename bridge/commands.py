"""Keep long effects in a batch file instead of the game's console input field."""
from pathlib import Path

def write_apply_files(session,battle,command):
    session=Path(session)
    filename='hmb_'+battle['id']+'.txt'
    batch=session/filename
    batch.write_text(command+'\n',encoding='utf8')
    (session/'apply_command.txt').write_text(command,encoding='utf8')
    (session/'run_command.txt').write_text('run '+filename,encoding='utf8')
    return batch,'run '+filename
