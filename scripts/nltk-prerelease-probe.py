"""Offline fixed-source path containment assessment, never a dependency promotion."""

import contextlib
import inspect
import json
import os
import sys
from pathlib import Path

SOURCE = Path('/nltk-source')


def assess():
    if (sys.platform != 'linux' or os.geteuid() != 10001 or not (SOURCE / 'nltk/VERSION').is_file()
            or os.environ.get('EXTRIO_NLTK_ASSESSMENT') != '1'):
        raise RuntimeError('Requires the isolated non-root assessment container')
    sys.path.insert(0, str(SOURCE))
    import nltk
    import nltk.data
    import numpy as np
    from nltk import pathsec
    from nltk.classify.maxent import load_maxent_params, save_maxent_params
    from nltk.parse.transitionparser import TransitionParser
    from nltk.tag.perceptron import AveragedPerceptron, PerceptronTagger

    if not Path(nltk.__file__).resolve().is_relative_to(SOURCE):
        raise RuntimeError('prerelease source was not actually loaded')
    root = Path.home() / 'nltk_data'
    outside = Path.home() / 'outside'
    root.mkdir(mode=0o700)
    outside.mkdir(mode=0o700)
    canary = outside / 'weights.json'
    initial = b'{"probe":{"NN":1.0}}'
    canary.write_bytes(initial)
    (root / 'linked').symlink_to(outside, target_is_directory=True)
    nltk.data.path = [str(root)]
    pathsec.ENFORCE = True
    pathsec._ALLOWED_ROOTS_CACHE = None
    pathsec._LAST_DATA_PATHS = None
    tagger = PerceptronTagger(load=False)
    refused = []
    for name, directory in [('absolute', outside), ('traversal', root / '..' / 'outside'),
                            ('symlink', root / 'linked')]:
        filename = str(directory / 'weights.json')
        calls = {
            'negativeControl': lambda p=filename: pathsec.open(p),
            'AveragedPerceptron.save': lambda p=filename: AveragedPerceptron().save(p),
            'AveragedPerceptron.load': lambda p=filename: AveragedPerceptron().load(p),
            'PerceptronTagger.save_to_json': lambda d=str(directory): tagger.save_to_json(lang='probe', loc=d),
            'save_maxent_params': lambda d=str(directory): save_maxent_params(np.array([0.5]), {}, [], {}, tab_dir=d),
            'TransitionParser.parse': lambda p=filename: TransitionParser.__new__(TransitionParser).parse([], p),
        }
        for api, call in calls.items():
            try:
                call()
            except PermissionError:
                refused.append({'vector': name, 'api': api})
            else:
                raise AssertionError('outside-root access was not refused: ' + api)
            assert canary.read_bytes() == initial
            assert sorted(p.name for p in outside.iterdir()) == ['weights.json']
    model = AveragedPerceptron()
    model.weights = {'probe': {'NN': 1.0}}
    model.save(str(root / 'positive.json'))
    restored = AveragedPerceptron()
    restored.load(str(root / 'positive.json'))
    assert restored.weights == model.weights
    weights = np.array([0.5, -1.25])
    destination = save_maxent_params(weights, {}, [], {})
    loaded = load_maxent_params(str(destination))
    assert np.allclose(loaded[0], weights)
    train_source = inspect.getsource(TransitionParser.train)
    assert 'pathsec_open(modelfile' in train_source
    return {
        'sourceCommit': 'ba6b259aa94a85168c031ad60e4072538c30b513',
        'sourceVersion': nltk.__version__, 'modulePath': nltk.__file__,
        'guardRefusals': refused, 'roundTripChecks': ['AveragedPerceptron', 'maxent parameters'],
        'transitionTrain': 'source review only; optional scikit-learn training is not exercised',
        'scope': 'five affected APIs, three escape vectors and controls; not full prerelease qualification',
        'stableDependencyChanged': False, 'riskWaiver': False,
    }


if __name__ == '__main__':
    with contextlib.redirect_stdout(sys.stderr):
        result = assess()
    print(json.dumps(result, indent=2))
