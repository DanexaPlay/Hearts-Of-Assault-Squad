"""Build a source-only installer ZIP from one clean, committed Git snapshot."""
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def validate_paths(names):
    banned = {'.dll','.exe','.hoi4','.pak','.scn','.sqlite','.zip','.7z','.dmp','.pem','.key','.log'}
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe release path: ' + name)
        if path.parts[0].lower() in ('sessions','runtime','backups','.git','.venv','dist','build') or path.suffix.lower() in banned:
            raise ValueError('Private/generated/game file in release tree: ' + name)
        if path.name.lower() in ('config.json','mod-connection.json','verification.json') or path.name.lower().startswith('.env'):
            raise ValueError('Machine-specific state in release tree: ' + name)


def main():
    git('diff','--exit-code');git('diff','--cached','--exit-code')
    version = git('show','HEAD:VERSION').decode('utf8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?', version):
        raise ValueError('Invalid release version')
    commit = git('rev-parse','HEAD').decode().strip()
    names = git('ls-tree','-r','--name-only','HEAD').decode('utf8').splitlines()
    validate_paths(names)
    timestamp = int(git('show','-s','--format=%ct','HEAD'))
    date = datetime.datetime.fromtimestamp(timestamp,datetime.timezone.utc)
    output = ROOT / 'dist';output.mkdir(exist_ok=True)
    archive = output / ('Hearts-Of-Assault-Squad-v' + version + '-windows-x64.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as target:
        for name in names:
            raw = git('show','HEAD:' + name)
            if len(raw) > 25 * 1024 * 1024:
                raise ValueError('Unexpectedly large release file: ' + name)
            if not name.endswith('.png') and re.search(rb'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----',raw):
                raise ValueError('Potential credential in release file: ' + name)
            info = zipfile.ZipInfo('Hearts-Of-Assault-Squad/' + name,date.timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED;info.external_attr = 0o100644 << 16
            target.writestr(info,raw)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksums = output / 'SHA256SUMS.txt'
    checksums.write_text(sha + '  ' + archive.name + '\n',encoding='ascii')
    report = {'version':version,'commit':commit,'archive':archive.name,'sha256':sha,'files':len(names),'bytes':archive.stat().st_size}
    (output / 'release-manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
