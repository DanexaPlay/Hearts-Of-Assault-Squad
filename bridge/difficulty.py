"""Use shipped AS2 difficulty coefficients, selected by HOI4 campaign."""
from .core import BridgeError,digest

MAPPING={'very_easy':'easy','easy':'easy','normal':'normal','hard':'hard','very_hard':'heroic'}


def install_profiles(b,dest,archive):
    source=b.get('difficulty','normal')
    if source not in MAPPING:raise BridgeError('Unsupported HOI4 difficulty: '+str(source))
    selected=MAPPING[source]
    raw=archive.read('set/difficulty/'+selected+'.dl')
    folder=dest/'resource/set/difficulty';folder.mkdir(parents=True,exist_ok=True)
    # The regular-game UI may retain its last difficulty. Make every selectable
    # SP profile resolve to the campaign's native rules, including manual load.
    for name in ('easy','normal','hard','heroic'):(folder/(name+'.dl')).write_bytes(raw)
    (folder/'difficulty_generic.inc').write_bytes(archive.read('set/difficulty/difficulty_generic.inc'))
    return {'hoi4':source,'mow':selected,'rules_sha256':digest(raw),
        'method':'generated mod overrides all four single-player difficulty profiles',
        'scope':'all single-player missions while this generated bridge mod is active',
        'ui_selection':'may retain its previous label; effective coefficients use mapped rules',
        'engine_verified':False}
