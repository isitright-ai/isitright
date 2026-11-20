Written by isitright 0.8.0 (commit `d1d2abe`) with:

    isitright research check examples/research/corpus --task examples/research/task.json \
        --output <dir> --stand-in credulous --depth 1

`report.json` is the report (schema 0.8) and `N.replay.json` the replay artifacts it names. One
edit was made after the run: the label of the stand-in agent names no model (a text substitution
in `report.json` and the replay artifacts), and the artifact digests in `report.json` were
recomputed. `tests/test_legacy_artifacts.py` checks that the current code loads the
report, replays each artifact and exports the report's cases.
