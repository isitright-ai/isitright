"""The data-analysis pack: audit agents that write and run Python over data files.

Two modes from one subject. Frozen: the code an agent executed is replayed on generated worlds.
Live: frozen candidates are confirmed with the agent itself. Needs the ``data`` extra (pandas);
importing this package does not import pandas.
"""
